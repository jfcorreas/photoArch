"""Modal dialogs (screens) for the photoArch TUI.

Self-contained pop-ups: they never import the main app. app.py imports
these names so tests can keep using `from photoarch.app import ...`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    OptionList,
    RadioSet,
    RadioButton,
)

from . import archiver

# --------------------------------------------------------------------------
# Directory browser modal
# --------------------------------------------------------------------------

class DirectoryScreen(ModalScreen[Optional[Path]]):
    """Modal folder picker: browse directories, return the selected one."""

    def __init__(self, initial: Optional[Path] = None) -> None:
        super().__init__()
        start = (initial or Path.home()).expanduser()
        self.current = start if start.is_dir() else Path.home()
        # Maps each OptionList row to the folder it opens (None = parent row)
        self._entries: list[Optional[Path]] = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("📁  Select a folder", id="dir-title"),
            OptionList(id="dir-list"),
            Horizontal(
                Button("⬆️  Parent", id="dir-up"),
                Button("✅  Select this folder", variant="primary", id="dir-select"),
                Button("✖  Cancel", id="dir-cancel"),
                id="dir-buttons",
            ),
            id="dir-dialog",
        )

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        listing = self.query_one("#dir-list", OptionList)
        listing.clear_options()
        self.query_one("#dir-title", Label).update(f"📁  {self.current}")
        # Row 0 is always "parent directory"; the rest are subfolders
        self._entries = [None]  # None -> go to parent
        listing.add_options(["..  (parent directory)"])
        try:
            subdirs = sorted(
                (p for p in self.current.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            subdirs = []
        for subdir in subdirs:
            self._entries.append(subdir)
            listing.add_options([f"📁  {subdir.name}/"])
        if not subdirs:
            self._entries.append(None)  # placeholder row: do nothing
            listing.add_options(["(no subdirectories)"])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx < 0 or idx >= len(self._entries):
            return
        target = self._entries[idx]
        if target is None:
            # Row 0 is the parent; placeholder rows are listed as None too
            if idx == 0 and self.current.parent != self.current:
                self.current = self.current.parent
                self._refresh()
            return
        self.current = target
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "dir-up":
            self.current = self.current.parent
            self._refresh()
        elif bid == "dir-select":
            self.dismiss(self.current)
        elif bid == "dir-cancel":
            self.dismiss(None)


# --------------------------------------------------------------------------
# Conflict resolution modal
# --------------------------------------------------------------------------

class ConflictScreen(ModalScreen[str]):
    """Shows all conflicts (across every destination) and asks what to do.

    groups: list of (dest_root, conflicts) — one entry per destination
    (primary, and cold storage when set). Returns "rename", "overwrite",
    "skip" or "cancel"; the choice is applied independently per destination.
    """

    def __init__(self, groups: list[tuple[Path, list[archiver.Conflict]]]) -> None:
        super().__init__()
        self.groups = groups

    def compose(self) -> ComposeResult:
        count = sum(len(conflicts) for _root, conflicts in self.groups)
        plural = "s" if count != 1 else ""
        yield Vertical(
            Label(f"⚠️  {count} conflict{plural} at destination", id="conflict-title"),
            DataTable(id="conflict-table"),
            Label("Choose what to do with the conflicting files:", id="conflict-question"),
            RadioSet(
                RadioButton("🔀  Keep both — auto-rename (file_1.ext, file_2.ext…)", value=True, id="act-rename"),
                RadioButton("♻️  Overwrite destination file", id="act-overwrite"),
                RadioButton("⏭️  Skip conflicting files", id="act-skip"),
                id="conflict-actions",
            ),
            Horizontal(
                Button("✔  Apply to all", variant="primary", id="conflict-apply"),
                Button("✖  Cancel operation", id="conflict-cancel"),
                id="conflict-buttons",
            ),
            id="conflict-dialog",
        )

    def on_mount(self) -> None:
        table = self.query_one("#conflict-table", DataTable)
        table.add_columns("📄 Source file", "📁 Destination", "🔎 Reason")
        for root, conflicts in self.groups:
            for c in conflicts:
                dest = root / c.item.dest_dir / c.item.name
                reason = "exists at destination" if c.dest_exists else "duplicate in batch"
                table.add_row(c.item.src.name, str(dest), reason)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "conflict-apply":
            rs = self.query_one("#conflict-actions", RadioSet)
            pressed = rs.pressed_button
            action = {
                "act-rename": "rename",
                "act-overwrite": "overwrite",
                "act-skip": "skip",
            }.get((pressed.id if pressed else "") or "", "rename")
            self.dismiss(action)
        elif event.button.id == "conflict-cancel":
            self.dismiss("cancel")


# --------------------------------------------------------------------------
# New-device naming modal
# --------------------------------------------------------------------------

class DeviceNamingScreen(ModalScreen[Optional[dict[str, str]]]):
    """Ask a friendly name for each newly found device.

    NAMING IS MANDATORY: every input is prefilled with the raw EXIF name,
    so "Save" always produces an entry per device (empty field = raw name
    stored as-is). Returns {raw_device: friendly_name}, or None when the
    user cancels the whole operation.
    """

    def __init__(self, devices_found: list[str]) -> None:
        super().__init__()
        self.devices_found = devices_found

    def compose(self) -> ComposeResult:
        fields = []
        for i, raw in enumerate(self.devices_found):
            fields.append(Label(f"📷  {raw}", classes="dev-raw"))
            fields.append(Input(value=raw, placeholder=raw, id=f"dev-input-{i}"))
        yield Vertical(
            Label("🆕  New device(s) found — choose a friendly name", id="dev-title"),
            Label(
                "The friendly name is used in the destination folders "
                "and saved in devices.json.",
                id="dev-hint",
            ),
            VerticalScroll(Vertical(*fields, id="dev-fields"), id="dev-scroll"),
            Horizontal(
                Button("💾  Save names", variant="primary", id="dev-save"),
                Button("✖  Cancel operation", id="dev-cancel"),
                id="dev-buttons",
            ),
            id="dev-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dev-save":
            mapping: dict[str, str] = {}
            for i, raw in enumerate(self.devices_found):
                value = self.query_one(f"#dev-input-{i}", Input).value.strip()
                mapping[raw] = value or raw  # empty field -> raw name (still stored)
            self.dismiss(mapping)
        elif event.button.id == "dev-cancel":
            self.dismiss(None)
