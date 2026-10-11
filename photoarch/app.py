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

from . import archiver
from .organizer import FORMATS


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
    """Shows all conflicts and asks the user what to do.

    Returns "rename", "overwrite", "skip" or "cancel".
    """

    def __init__(self, conflicts: list[archiver.Conflict], dest_root: Path) -> None:
        super().__init__()
        self.conflicts = conflicts
        self.dest_root = dest_root

    def compose(self) -> ComposeResult:
        count = len(self.conflicts)
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
        for c in self.conflicts:
            dest = self.dest_root / c.item.dest_dir / c.item.name
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
    ("⏭️ Non-media skipped", "non_media"),
    ("📋 Files planned", "planned"),
    ("", None),
    ("✅ Files copied", "copied"),
    ("📁 Folders created", "folders"),
    ("💾 Data copied", "bytes"),
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

    #content { padding: 1 2; width: 100%; }
    #path-summary { height: auto; margin-bottom: 1; }
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
        self._stat_values: dict[str, str] = {}

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
        self._reset_stats()
        self._update_summary()

    # ---- stats helpers ---------------------------------------------------

    def _render_stats(self) -> None:
        table = self.query_one("#stats-table", DataTable)
        table.clear()
        if not table.columns:
            table.add_columns("📊 Metric", " value")
            table.cursor_type = "none"
        for label, key in STAT_ROWS:
            if key is None:
                table.add_row("", "")
            else:
                table.add_row(label, self._stat_values.get(key, "—"))

    def _reset_stats(self) -> None:
        self._stat_values = {}
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
            f"🗂️ Format: [bold]{label}[/bold]"
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "fmt-select":
            self._update_summary()

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
        elif bid == "btn-dry":
            self.action_dry_run()
        elif bid == "btn-archive":
            self.action_archive()

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

        fmt = str(self.query_one("#fmt-select", Select).value)

        self._reset_stats()
        self.query_one("#results-log", RichLog).clear()
        self.query_one("#errors-log", RichLog).clear()
        self._set_stat("mode", "🧪 dry run" if dry_run else "📦 real archive")
        self._set_stat("source", str(src_r))
        self._set_stat("dest", str(dst_r))
        self._set_stat("format", FORMATS.get(fmt, next(iter(FORMATS.values())))[0])
        self.notify("🔎 Scanning source folder…")
        self._scan_and_plan(src_r, dst_r, fmt, dry_run)

    @work(thread=True, exclusive=True, group="archive")
    def _scan_and_plan(self, src: Path, dst: Path, fmt: str, dry_run: bool) -> None:
        plan = archiver.scan(src, dst, fmt)
        self.app.call_from_thread(self._after_scan, plan, dst, dry_run)

    def _after_scan(self, plan: archiver.ScanResult, dst: Path, dry_run: bool) -> None:
        for err in plan.errors:
            self._log_error(err)
        self._set_stat("scanned", str(len(plan.items) + plan.skipped))
        self._set_stat("media", str(len(plan.items)))
        self._set_stat("non_media", str(plan.skipped))
        self._set_stat("planned", str(len(plan.items)))
        self._set_stat("folders", str(plan.folders_to_create))
        self._set_stat("bytes", human_size(plan.total_size))
        self._set_stat("conflicts", str(len(plan.conflicts)))

        if not plan.items:
            self.notify("ℹ️ No media files found in the source folder.", severity="information")
            return

        if plan.conflicts:
            policy = self.query_one("#conflict-policy", RadioSet).pressed_button
            policy_id = (policy.id if policy else "cf-ask") or "cf-ask"
            if policy_id == "cf-ask":
                def got(action: str) -> None:
                    self._after_conflicts(plan, dst, dry_run, action)
                self.push_screen(ConflictScreen(plan.conflicts, dst), got)
                return
            action = {"cf-rename": "rename", "cf-overwrite": "overwrite", "cf-skip": "skip"}[policy_id]
        else:
            action = "rename"  # no conflicts; action is irrelevant
        self._after_conflicts(plan, dst, dry_run, action)

    def _after_conflicts(
        self, plan: archiver.ScanResult, dst: Path, dry_run: bool, action: str
    ) -> None:
        if action == "cancel":
            self.notify("🚫 Operation cancelled by user.")
            return
        try:
            resolved = archiver.apply_resolution(plan, action, dst)
        except ValueError:
            self.notify("⚠️ Unknown conflict action.", severity="error")
            return
        if action == "skip":
            self._set_stat("conflicts_skipped", str(len(plan.conflicts)))
        self._do_copy(resolved, dst, dry_run)

    @work(thread=True, exclusive=True, group="archive")
    def _do_copy(self, plan: archiver.ScanResult, dst: Path, dry_run: bool) -> None:
        report = archiver.execute(plan, dst, dry_run, on_progress=self._progress_from_thread)
        self.app.call_from_thread(self._after_copy, report, dry_run)

    def _progress_from_thread(self, message: str, kind: str) -> None:
        self.app.call_from_thread(self._log, message, kind)

    def _after_copy(self, report: archiver.CopyReport, dry_run: bool) -> None:
        for _src, err in report.errors:
            self._log_error(err)
        self._set_stat("copied", str(report.copied))
        self._set_stat("folders", str(report.folders_created))
        self._set_stat("bytes", human_size(report.bytes_copied))
        self._set_stat("errors", str(len(report.errors)))
        if dry_run:
            self.notify(f"🧪 Dry run complete — {report.copied} files would be copied.")
        else:
            self.notify(f"📦 Archive complete — {report.copied} files copied.")
