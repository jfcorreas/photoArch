"""photoArch TUI application (Textual)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RadioSet,
    RadioButton,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from . import archiver, devices, settings
from .organizer import FORMATS, IMAGE_EXTS, VIDEO_EXTS


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


# --------------------------------------------------------------------------
# Stats table rows: (label, key)
# --------------------------------------------------------------------------

STAT_ROWS = [
    ("🗂️ Mode", "mode"),
    ("📂 Source", "source"),
    ("🎯 Destination", "dest"),
    ("🗂️ Format", "format"),
    ("", None),  # spacer
    ("🔎 Files scanned", "scanned"),
    ("🖼️ Media files found", "media"),
    ("📸 Images", "images"),
    ("🎬 Videos", "videos"),
    ("⏭️ Non-media skipped", "non_media"),
    ("📋 Files planned", "planned"),
    ("", None),
    ("✅ Files copied", "copied"),
    ("📁 Folders created", "folders"),
    ("💾 Data copied", "bytes"),
    ("🗄️ Cold copies", "cold_copies"),
    ("🗄️ Cold storage bytes", "cold_bytes"),
    ("", None),
    ("⚠️ Conflicts detected", "conflicts"),
    ("⏭️ Conflicts skipped", "conflicts_skipped"),
    ("❌ Errors", "errors"),
]


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{n} B"


# --------------------------------------------------------------------------
# Main application
# --------------------------------------------------------------------------

class PhotoArchApp(App):
    TITLE = "photoArch"
    SUB_TITLE = "Archive & organize photos"

    CSS = """
    #sidebar {
        width: 48;
        padding: 1 2;
        border-right: solid $accent;
    }
    #sidebar Label { width: 100%; }
    #sidebar Select { width: 100%; margin-bottom: 1; }
    #sidebar RadioSet { width: 100%; }
    #sidebar Button { width: 100%; margin-bottom: 1; }
    .section { margin-top: 1; text-style: bold; color: $accent; }

    #content { padding: 1 2; width: 1fr; }
    #path-summary { height: auto; margin-bottom: 1; }
    #tabs { height: 1fr; }
    #tabs ContentSwitcher { height: 1fr; }
    #tab-devices { height: 100%; }
    #stats-panel { height: 100%; }
    #stats-table { height: auto; }
    #results-log, #errors-log { height: 100%; }

    #dir-dialog {
        width: 80%;
        height: 80%;
        border: thick $accent;
        padding: 1;
        background: $surface;
    }
    #dir-list { height: 1fr; }
    #dir-buttons Button { margin: 1 1 0 0; width: auto; }

    #conflict-dialog {
        width: 92%;
        height: auto;
        max-height: 85%;
        border: thick $warning;
        padding: 1;
        background: $surface;
    }
    #conflict-table { height: 12; }
    #conflict-actions { margin: 1 0; }
    #conflict-buttons Button { margin: 0 1 0 0; width: auto; }

    #dev-dialog {
        width: 70%;
        height: auto;
        max-height: 85%;
        border: thick $accent;
        padding: 1;
        background: $surface;
    }
    #dev-hint { margin: 1 0; }
    #dev-scroll { height: auto; max-height: 24; }
    .dev-raw { margin-top: 1; text-style: bold; color: $accent; }
    #dev-fields Input { margin-bottom: 1; }
    #dev-buttons Button { margin: 1 1 0 0; width: auto; }

    #devices-table { height: 1fr; margin-bottom: 1; }
    #devices-hint { width: 100%; height: auto; margin-bottom: 1; }
    #dev-manage-row { height: auto; }
    #dev-manage-row Input { width: 1fr; }
    #dev-manage-row Button { width: auto; margin-left: 1; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "dry_run", "Dry run"),
        ("a", "archive", "Archive"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._source: Optional[Path] = None
        self._dest: Optional[Path] = None
        self._cold: Optional[Path] = None  # optional second destination (cold storage)
        self._stat_values: dict[str, str] = {}
        # media counts per extension, rendered as extra rows in the stats table
        self._ext_counts: dict[str, int] = {}
        # Where the device->friendly-name JSON is stored (tests override this)
        self.devices_path: Path = devices.DEVICES_FILE
        # Where last-used run settings are stored (tests override this)
        self.settings_path: Path = settings.SETTINGS_FILE
        # Last mapping shown in the Devices tab (raw device -> friendly name)
        self._devices_map: dict[str, str] = {}

    # ---- layout ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with VerticalScroll(id="sidebar"):
                yield Label("🖼️  photoArch", id="app-title")
                yield Label("📂  Source folder (never modified)", classes="section")
                yield Button("📁  Select source folder…", id="pick-source")
                yield Label("🎯  Destination folder", classes="section")
                yield Button("📁  Select destination folder…", id="pick-dest")
                yield Label("🗄️  Cold Storage (optional 2nd copy)", classes="section")
                yield Button("🗄️  Select cold storage folder…", id="pick-cold")
                yield Button("✖  Clear cold storage", id="clear-cold")
                yield Label("🗂️  Destination folder format", classes="section")
                yield Select(
                    [(label, key) for key, (label, _tpl) in FORMATS.items()],
                    value="year_month",
                    allow_blank=False,
                    id="fmt-select",
                )
                yield Label("🧩  When a file name conflicts", classes="section")
                yield RadioSet(
                    RadioButton("💬  Ask me each time", value=True, id="cf-ask"),
                    RadioButton("🔀  Always auto-rename", id="cf-rename"),
                    RadioButton("♻️  Always overwrite", id="cf-overwrite"),
                    RadioButton("⏭️  Always skip", id="cf-skip"),
                    id="conflict-policy",
                )
                yield Button("🧪  Dry run", id="btn-dry")
                yield Button("📦  Archive now", id="btn-archive", variant="primary")
            with Vertical(id="content"):
                yield Static("Select a source and destination folder to begin.", id="path-summary")
                yield TabbedContent(id="tabs")
        yield Footer()

    async def on_mount(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        await tabs.add_pane(TabPane("📊 Statistics", DataTable(id="stats-table"), id="tab-stats"))
        await tabs.add_pane(TabPane("📋 Results", RichLog(id="results-log", wrap=True), id="tab-results"))
        await tabs.add_pane(TabPane("❌ Errors", RichLog(id="errors-log", wrap=True), id="tab-errors"))
        await tabs.add_pane(
            TabPane(
                "📇 Devices",
                DataTable(id="devices-table"),
                Label(
                    "Rename the selected device (empty field = keep the raw name) or remove it. "
                    "Removal only forgets the name — the device is asked again on the next run. "
                    "Renaming does not move folders created by earlier runs.",
                    id="devices-hint",
                ),
                Horizontal(
                    Input(placeholder="friendly name of the selected device", id="dev-manage-input"),
                    Button("💾  Save name", variant="primary", id="dev-save-name"),
                    Button("🗑  Remove", id="dev-remove"),
                    id="dev-manage-row",
                ),
                id="tab-devices",
            )
        )
        self._reset_stats()
        self._restore_settings()
        self._update_summary()
        self._refresh_devices_table()

    # ---- persisted settings ---------------------------------------------

    def _restore_settings(self) -> None:
        """Prefill folders/format/conflict from the last run (tolerant load).

        A saved folder that no longer exists is restored as-is; it is
        validated when a run starts (and the picker falls back to $HOME).
        """
        cfg = settings.load(self.settings_path)
        if cfg["source"]:
            self._source = Path(cfg["source"])
            self.query_one("#pick-source", Button).label = f"📁  {self._source}"
        if cfg["dest"]:
            self._dest = Path(cfg["dest"])
            self.query_one("#pick-dest", Button).label = f"📁  {self._dest}"
        if cfg["cold_dest"]:
            self._cold = Path(cfg["cold_dest"])
            self.query_one("#pick-cold", Button).label = f"🗄️  {self._cold}"
        self.query_one("#fmt-select", Select).value = cfg["format"]
        radio_id = {
            "ask": "cf-ask",
            "rename": "cf-rename",
            "overwrite": "cf-overwrite",
            "skip": "cf-skip",
        }[cfg["conflict"]]
        self.query_one(f"#{radio_id}", RadioButton).value = True

    def _save_settings(self) -> None:
        """Persist the current folders/format/conflict (called on run start)."""
        policy = self.query_one("#conflict-policy", RadioSet).pressed_button
        policy_id = (policy.id if policy else "cf-ask") or "cf-ask"
        data = {
            "source": str(self._source) if self._source else "",
            "dest": str(self._dest) if self._dest else "",
            "cold_dest": str(self._cold) if self._cold else "",
            "format": str(self.query_one("#fmt-select", Select).value),
            "conflict": {
                "cf-ask": "ask",
                "cf-rename": "rename",
                "cf-overwrite": "overwrite",
                "cf-skip": "skip",
            }.get(policy_id, "ask"),
        }
        if not settings.save(data, self.settings_path):
            self.notify(f"⚠️ Could not save {self.settings_path}.", severity="warning")

    # ---- stats helpers ---------------------------------------------------

    def _render_stats(self) -> None:
        table = self.query_one("#stats-table", DataTable)
        table.clear()
        if not table.columns:
            table.add_columns("📊 Metric", " value")
            table.cursor_type = "none"
        # which format rows belong under which stats row
        ext_groups = {"images": (IMAGE_EXTS, "  🖼️ "), "videos": (VIDEO_EXTS, "  🎬 ")}
        for label, key in STAT_ROWS:
            if key is None:
                table.add_row("", "")
                continue
            table.add_row(label, self._stat_values.get(key, "—"))
            # image formats under Images, video formats under Videos
            group = ext_groups.get(key)
            if group:
                ext_set, prefix = group
                for ext, count in sorted(
                    self._ext_counts.items(), key=lambda kv: (-kv[1], kv[0])
                ):
                    if ext in ext_set:
                        table.add_row(f"{prefix}{ext}", str(count))

    def _reset_stats(self) -> None:
        self._stat_values = {}
        self._ext_counts = {}
        self._render_stats()

    def _set_stat(self, key: str, value: str) -> None:
        self._stat_values[key] = value
        self._render_stats()

    # ---- logging ---------------------------------------------------------

    def _log(self, message: str, kind: str = "info") -> None:
        colors = {"copied": "green", "would": "cyan", "folder": "blue", "error": "red"}
        color = colors.get(kind, "white")
        self.query_one("#results-log", RichLog).write(f"[{color}]{message}[/{color}]")

    def _log_error(self, message: str) -> None:
        self.query_one("#errors-log", RichLog).write(f"[red]{message}[/red]")

    # ---- misc ------------------------------------------------------------

    def _update_summary(self) -> None:
        fmt = str(self.query_one("#fmt-select", Select).value)
        label = FORMATS.get(fmt, next(iter(FORMATS.values())))[0]
        self.query_one("#path-summary", Static).update(
            f"📂 Source: [bold]{self._source or '—'}[/bold]\n"
            f"🎯 Destination: [bold]{self._dest or '—'}[/bold]\n"
            f"🗄️ Cold storage: [bold]{self._cold or '— (none)'}[/bold]\n"
            f"🗂️ Format: [bold]{label}[/bold]"
        )

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        # Keep the Devices tab in sync with devices.json every time it is opened
        if event.pane.id == "tab-devices":
            self._refresh_devices_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "fmt-select":
            self._update_summary()

    # ---- devices panel ---------------------------------------------------

    def _refresh_devices_table(self) -> None:
        """Reload devices.json into the Devices tab (raw name -> friendly name)."""
        table = self.query_one("#devices-table", DataTable)
        table.clear()
        if not table.columns:
            table.add_columns("📷 Device (raw)", "✏️ Friendly name")
            table.cursor_type = "row"
        self._devices_map = devices.load(self.devices_path)
        for raw in sorted(self._devices_map):
            table.add_row(raw, self._devices_map[raw], key=raw)
        if not self._devices_map:
            table.add_row("(no known devices yet)", "")
        self.query_one("#dev-manage-input", Input).value = ""

    def _selected_raw_device(self) -> Optional[str]:
        """Raw device name under the table cursor, or None (nothing usable)."""
        table = self.query_one("#devices-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        raw = str(row_key.value)  # str(row_key) is the object repr, not the key
        return raw if raw in self._devices_map else None  # placeholder row -> None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Other tables (stats) either have no row cursor or use other ids
        if event.data_table.id != "devices-table":
            return
        raw = str(event.row_key.value)
        self.query_one("#dev-manage-input", Input).value = self._devices_map.get(raw, "")

    def _save_device_name(self) -> None:
        raw = self._selected_raw_device()
        if raw is None:
            self.notify("⚠️ Select a device first.", severity="error")
            return
        value = self.query_one("#dev-manage-input", Input).value.strip() or raw
        mapping = devices.load(self.devices_path)
        mapping[raw] = value
        if not devices.save(mapping, self.devices_path):
            self.notify(f"⚠️ Could not save {self.devices_path}.", severity="error")
            return
        self.notify(f"✅ {raw} → {value}")
        self._refresh_devices_table()

    def _remove_device(self) -> None:
        raw = self._selected_raw_device()
        if raw is None:
            self.notify("⚠️ Select a device first.", severity="error")
            return
        mapping = devices.load(self.devices_path)
        mapping.pop(raw, None)
        if not devices.save(mapping, self.devices_path):
            self.notify(f"⚠️ Could not save {self.devices_path}.", severity="error")
            return
        self.notify(f"🗑 Removed {raw} — it will be asked again on the next run.")
        self._refresh_devices_table()

    # ---- folder picking --------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "pick-source":
            def got_source(path: Optional[Path]) -> None:
                if path is not None:
                    self._source = path
                    event.button.label = f"📁  {path}"
                    self._update_summary()
            self.push_screen(DirectoryScreen(self._source), got_source)
        elif bid == "pick-dest":
            def got_dest(path: Optional[Path]) -> None:
                if path is not None:
                    self._dest = path
                    event.button.label = f"📁  {path}"
                    self._update_summary()
            self.push_screen(DirectoryScreen(self._dest), got_dest)
        elif bid == "pick-cold":
            def got_cold(path: Optional[Path]) -> None:
                if path is not None:
                    self._cold = path
                    event.button.label = f"🗄️  {path}"
                    self._update_summary()
            self.push_screen(DirectoryScreen(self._cold), got_cold)
        elif bid == "clear-cold":
            self._cold = None
            self.query_one("#pick-cold", Button).label = "🗄️  Select cold storage folder…"
            self._update_summary()
        elif bid == "btn-dry":
            self.action_dry_run()
        elif bid == "btn-archive":
            self.action_archive()
        elif bid == "dev-save-name":
            self._save_device_name()
        elif bid == "dev-remove":
            self._remove_device()

    # ---- run logic -------------------------------------------------------

    def action_dry_run(self) -> None:
        self._run(dry_run=True)

    def action_archive(self) -> None:
        self._run(dry_run=False)

    def _run(self, dry_run: bool) -> None:
        if self._source is None or self._dest is None:
            self.notify("⚠️ Select both source and destination folders first.", severity="error")
            return
        src = self._source.expanduser()
        dst = self._dest.expanduser()
        if not src.is_dir():
            self.notify(f"⚠️ Source folder does not exist: {src}", severity="error")
            return
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.notify(f"⚠️ Cannot create destination: {exc}", severity="error")
            return

        src_r, dst_r = src.resolve(), dst.resolve()
        if src_r == dst_r or src_r in dst_r.parents:
            self.notify("⚠️ Destination must not be inside the source folder.", severity="error")
            return

        # optional cold storage: same restrictions as the primary destination
        cold_r: Optional[Path] = None
        if self._cold is not None:
            cold = self._cold.expanduser()
            cold_r = cold.resolve()
            # validate BEFORE mkdir so a rejected path never touches the source tree
            if cold_r == src_r or src_r in cold_r.parents:
                self.notify("⚠️ Cold storage must not be inside the source folder.", severity="error")
                return
            if cold_r == dst_r or dst_r in cold_r.parents or cold_r in dst_r.parents:
                self.notify(
                    "⚠️ Cold storage must differ from the destination and not contain it (or be inside it).",
                    severity="error",
                )
                return
            try:
                cold.mkdir(parents=True, exist_ok=True)  # mirror primary (also on dry run)
            except OSError as exc:
                self.notify(f"⚠️ Cannot create cold storage: {exc}", severity="error")
                return

        self._save_settings()  # run started -> remember for the next launch

        fmt = str(self.query_one("#fmt-select", Select).value)
        device_map = devices.load(self.devices_path)

        self._reset_stats()
        self.query_one("#results-log", RichLog).clear()
        self.query_one("#errors-log", RichLog).clear()
        self._set_stat("mode", "🧪 dry run" if dry_run else "📦 real archive")
        self._set_stat("source", str(src_r))
        self._set_stat("dest", str(dst_r))
        self._set_stat("format", FORMATS.get(fmt, next(iter(FORMATS.values())))[0])
        self.notify("🔎 Scanning source folder…")
        self._scan_and_plan(src_r, dst_r, cold_r, fmt, dry_run, device_map)

    @work(thread=True, exclusive=True, group="archive")
    def _scan_and_plan(
        self,
        src: Path,
        dst: Path,
        cold: Optional[Path],
        fmt: str,
        dry_run: bool,
        device_map: dict[str, str],
    ) -> None:
        # Scan once against the primary destination (cold reuses these items)
        plan = archiver.scan(src, dst, fmt, device_map)
        self.app.call_from_thread(self._after_scan, plan, dst, cold, fmt, dry_run, device_map)

    def _after_scan(
        self,
        plan: archiver.ScanResult,
        dst: Path,
        cold: Optional[Path],
        fmt: str,
        dry_run: bool,
        device_map: dict[str, str],
    ) -> None:
        for err in plan.errors:
            self._log_error(err)
        self._set_stat("scanned", str(len(plan.items) + plan.skipped))
        self._set_stat("media", str(len(plan.items)))
        self._set_stat("images", str(plan.images))
        self._set_stat("videos", str(plan.videos))
        self._set_stat("non_media", str(plan.skipped))
        self._ext_counts = dict(plan.by_ext)
        self._render_stats()
        self._set_stat("planned", str(len(plan.items)))
        self._set_stat("bytes", human_size(plan.total_size))

        if not plan.items:
            self.notify("ℹ️ No media files found in the source folder.", severity="information")
            return

        if plan.unknown_devices:
            def got(mapping: Optional[dict[str, str]]) -> None:
                self._after_device_names(plan, dst, cold, fmt, dry_run, device_map, mapping)
            self.push_screen(DeviceNamingScreen(plan.unknown_devices), got)
            return

        self._begin_resolution(plan, device_map, fmt, dst, cold, dry_run)

    def _after_device_names(
        self,
        plan: archiver.ScanResult,
        dst: Path,
        cold: Optional[Path],
        fmt: str,
        dry_run: bool,
        device_map: dict[str, str],
        mapping: Optional[dict[str, str]],
    ) -> None:
        if mapping is None:
            self.notify("🚫 Operation cancelled by user.")
            return
        merged = devices.load(self.devices_path)
        merged.update(mapping)
        if not devices.save(merged, self.devices_path):
            self._log_error(
                f"⚠️ Could not save {self.devices_path}; names apply to this run only."
            )
        self._refresh_devices_table()  # Devices tab may be open behind the modal
        # dest_dir changes -> rebuild both destinations with friendly names
        self._begin_resolution(plan, merged, fmt, dst, cold, dry_run)

    def _begin_resolution(
        self,
        raw_plan: archiver.ScanResult,
        device_map: dict[str, str],
        fmt: str,
        dst: Path,
        cold: Optional[Path],
        dry_run: bool,
    ) -> None:
        """Build one plan per destination (reusing the scanned items) and resolve.

        apply_device_names recomputes dest_dir from the friendly names AND
        rebuilds the conflict list against the given root — so each destination
        gets its own conflicts without re-walking the source.
        """
        roots = [dst] + ([cold] if cold is not None else [])
        targets = [
            (archiver.apply_device_names(raw_plan, device_map, fmt, root), root)
            for root in roots
        ]
        self._set_stat("folders", str(targets[0][0].folders_to_create))  # primary
        self._set_stat(
            "conflicts", str(sum(len(plan.conflicts) for plan, _root in targets))
        )
        self._resolve_conflicts(targets, dry_run)

    def _resolve_conflicts(
        self, targets: list[tuple[archiver.ScanResult, Path]], dry_run: bool
    ) -> None:
        groups = [(root, plan.conflicts) for plan, root in targets if plan.conflicts]
        if groups:
            policy = self.query_one("#conflict-policy", RadioSet).pressed_button
            policy_id = (policy.id if policy else "cf-ask") or "cf-ask"
            if policy_id == "cf-ask":
                def got(action: str) -> None:
                    self._after_conflicts(targets, dry_run, action)
                self.push_screen(ConflictScreen(groups), got)
                return
            action = {"cf-rename": "rename", "cf-overwrite": "overwrite", "cf-skip": "skip"}[policy_id]
        else:
            action = "rename"  # no conflicts; action is irrelevant
        self._after_conflicts(targets, dry_run, action)

    def _after_conflicts(
        self, targets: list[tuple[archiver.ScanResult, Path]], dry_run: bool, action: str
    ) -> None:
        if action == "cancel":
            self.notify("🚫 Operation cancelled by user.")
            return
        try:
            resolved = [
                (archiver.apply_resolution(plan, action, root), root)
                for plan, root in targets
            ]
        except ValueError:
            self.notify("⚠️ Unknown conflict action.", severity="error")
            return
        if action == "skip":
            # skipped across every destination (a file can conflict in one root only)
            self._set_stat(
                "conflicts_skipped",
                str(sum(len(plan.conflicts) for plan, _root in targets)),
            )
        self._do_copy(resolved, dry_run)

    @work(thread=True, exclusive=True, group="archive")
    def _do_copy(
        self,
        resolved: list[tuple[archiver.ScanResult, Path]],
        dry_run: bool,
    ) -> None:
        reports = [
            archiver.execute(plan, root, dry_run, on_progress=self._progress_from_thread)
            for plan, root in resolved
        ]
        primary = reports[0]
        cold_report = reports[1] if len(reports) > 1 else None
        self.app.call_from_thread(self._after_copy, primary, cold_report, dry_run)

    def _progress_from_thread(self, message: str, kind: str) -> None:
        self.app.call_from_thread(self._log, message, kind)

    def _after_copy(
        self,
        report: archiver.CopyReport,
        cold_report: Optional[archiver.CopyReport],
        dry_run: bool,
    ) -> None:
        for r in (report, cold_report):
            if r is None:
                continue
            for _src, err in r.errors:
                self._log_error(err)
        # existing rows reflect the primary destination (option b)
        self._set_stat("copied", str(report.copied))
        self._set_stat("folders", str(report.folders_created))
        self._set_stat("bytes", human_size(report.bytes_copied))
        total_errors = len(report.errors) + (len(cold_report.errors) if cold_report else 0)
        self._set_stat("errors", str(total_errors))
        if cold_report is not None:
            self._set_stat("cold_copies", str(cold_report.copied))
            self._set_stat("cold_bytes", human_size(cold_report.bytes_copied))
        verb = "would be copied" if dry_run else "copied"
        icon = "🧪" if dry_run else "📦"
        msg = f"{icon} {'Dry run complete' if dry_run else 'Archive complete'} — {report.copied} files {verb}"
        if cold_report is not None:
            msg += f" (+{cold_report.copied} to cold storage)"
        self.notify(msg + ".")
