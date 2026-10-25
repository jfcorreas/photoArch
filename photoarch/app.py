"""photoArch TUI application (Textual)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pathlib import Path
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioSet,
    RadioButton,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from . import archiver, devices, settings, theming
from .screens import ConflictScreen, DeviceNamingScreen, DirectoryScreen
from .organizer import FORMATS, IMAGE_EXTS, VIDEO_EXTS

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

# --------------------------------------------------------------------------
# One run's settings, threaded through the pipeline as a single object
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RunRequest:
    """Everything a pipeline step needs about the current run.

    frozen=True: never mutated — after the naming modal we build a NEW
    request with dataclasses.replace() instead of changing this one.
    """

    src: Path
    dst: Path
    cold: Optional[Path]  # optional 2nd destination (None = no cold storage)
    fmt: str
    dry_run: bool
    device_map: dict[str, str]  # raw device -> friendly name

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
    #sidebar Button { width: 100%; height: 1; border: none; padding: 0 1; margin: 1 0 1 0; }
    .section { text-style: bold; color: $accent; }
    #clear-cold { display: none; }
    #app-title {
        background: $accent;   /* Omarchy accent when available, Textual default else */
        color: $surface;       /* contrasting text (surface follows the theme too) */
        text-style: bold;
        height: 1;
        width: 100%;
        content-align: center middle;
        margin-bottom: 1;
    }

    #content { padding: 1 2; width: 1fr; }
    #path-summary { height: auto; margin-bottom: 1; }
    #tabs { height: 1fr; }
    #tabs ContentSwitcher { height: 1fr; }
    #tab-devices { height: 100%; }
    #tab-results { height: 100%; }
    #stats-panel { height: 100%; }
    /* table scrolls internally beyond 60% so the activity log always shows */
    #stats-table { height: auto; max-height: 60%; }
    #stats-panel RichLog { height: 1fr; min-height: 6; }
    #errors-log { height: 100%; }

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
        # Where the Omarchy theme state lives (tests override this)
        self.theme_state_dir: Path = theming.STATE_DIR
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
                    *(
                        RadioButton(label, value=policy == settings.DEFAULTS["conflict"], id=radio_id)
                        for policy, radio_id, label in settings.CONFLICT_POLICIES
                    ),
                    id="conflict-policy",
                )
                yield Button("🧪  Dry run", id="btn-dry")
                yield Button("📦  Archive now", id="btn-archive", variant="primary")
            with Vertical(id="content"):
                yield Static("Select a source and destination folder to begin.", id="path-summary")
                yield TabbedContent(id="tabs")
        yield Footer()

    def _apply_omarchy_theme(self) -> None:
        """Adapt the TUI to the current Omarchy theme when one is available.

        Startup-only (one palette read); missing/corrupt palette files keep
        Textual's default look silently — the feature is "if it is available".
        """
        colors = theming.load_palette(self.theme_state_dir)
        if not colors:
            return
        slug = theming.load_slug(self.theme_state_dir)
        self.register_theme(theming.build_theme(colors, slug))
        self.theme = f"omarchy-{slug}"
        ansi = theming.build_ansi_theme(colors)  # activity-log colors follow too
        self.ansi_theme_dark = ansi
        self.ansi_theme_light = ansi

    async def on_mount(self) -> None:
        self._apply_omarchy_theme()
        tabs = self.query_one("#tabs", TabbedContent)
        # Statistics + Results fused into ONE tab: aggregate stats table on
        # top, live per-file activity log below (log capped to bound memory).
        await tabs.add_pane(
            TabPane(
                "📊 Results",
                Vertical(
                    DataTable(id="stats-table"),
                    RichLog(id="results-log", wrap=True, max_lines=2000),
                    id="stats-panel",
                ),
                id="tab-results",
            )
        )
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
        self._update_clear_cold()
        self.query_one("#fmt-select", Select).value = cfg["format"]
        radio_id = settings.RADIO_BY_POLICY.get(cfg["conflict"], "cf-ask")
        self.query_one(f"#{radio_id}", RadioButton).value = True

    def _update_clear_cold(self) -> None:
        """Show the clear button only when a cold folder is set (saves 4 rows)."""
        self.query_one("#clear-cold", Button).display = self._cold is not None

    def _conflict_policy(self) -> str:
        """Current sidebar conflict policy ("ask" when nothing is pressed)."""
        pressed = self.query_one("#conflict-policy", RadioSet).pressed_button
        return settings.POLICY_BY_RADIO.get((pressed.id if pressed else "") or "", "ask")

    def _save_settings(self) -> None:
        """Persist the current folders/format/conflict (called on run start)."""
        data = {
            "source": str(self._source) if self._source else "",
            "dest": str(self._dest) if self._dest else "",
            "cold_dest": str(self._cold) if self._cold else "",
            "format": str(self.query_one("#fmt-select", Select).value),
            "conflict": self._conflict_policy(),
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

    def _set_stats(self, values: dict[str, str]) -> None:
        """Update several stats at once (one table re-render instead of N)."""
        self._stat_values.update(values)
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

    # which attribute each folder picker writes to: kind -> (attr, icon, refresh_clear)
    _PICKERS = {
        "source": ("_source", "📁  ", False),
        "dest": ("_dest", "📁  ", False),
        "cold": ("_cold", "🗄️  ", True),  # cold also toggles the Clear button
    }

    def _pick_folder(self, kind: str) -> None:
        """Open the folder modal for 'source'/'dest'/'cold' and store the result."""
        attr, icon, refresh_clear = self._PICKERS[kind]

        def got(path: Optional[Path]) -> None:
            if path is None:
                return  # cancelled
            setattr(self, attr, path)
            event_button = self.query_one(f"#pick-{kind}", Button)
            event_button.label = f"{icon}{path}"
            if refresh_clear:
                self._update_clear_cold()
            self._update_summary()

        self.push_screen(DirectoryScreen(getattr(self, attr)), got)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid in ("pick-source", "pick-dest", "pick-cold"):
            self._pick_folder(bid.removeprefix("pick-"))
        elif bid == "clear-cold":
            self._cold = None
            self.query_one("#pick-cold", Button).label = "🗄️  Select cold storage folder…"
            self._update_clear_cold()
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
        req = self._validate_run(dry_run)
        if req is None:
            return  # validation already showed the error notification
        self._save_settings()  # run started -> remember for the next launch

        self._reset_stats()
        self.query_one("#results-log", RichLog).clear()
        self.query_one("#errors-log", RichLog).clear()
        self._set_stats(
            {
                "mode": "🧪 dry run" if dry_run else "📦 real archive",
                "source": str(req.src),
                "dest": str(req.dst),
                "format": FORMATS.get(req.fmt, next(iter(FORMATS.values())))[0],
            }
        )
        self.notify("🔎 Scanning source folder…")
        self._scan_and_plan(req)

    def _validate_run(self, dry_run: bool) -> Optional[RunRequest]:
        """Check folders and return the run's request, or None (error shown).

        Order matters and is tested: destination folders are created only
        after every check passed, and settings are saved after this returns
        a request (never on a rejected run).
        """
        if self._source is None or self._dest is None:
            self.notify("⚠️ Select both source and destination folders first.", severity="error")
            return None
        src = self._source.expanduser()
        dst = self._dest.expanduser()
        if not src.is_dir():
            self.notify(f"⚠️ Source folder does not exist: {src}", severity="error")
            return None
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.notify(f"⚠️ Cannot create destination: {exc}", severity="error")
            return None

        src_r, dst_r = src.resolve(), dst.resolve()
        if src_r == dst_r or src_r in dst_r.parents:
            self.notify("⚠️ Destination must not be inside the source folder.", severity="error")
            return None

        # optional cold storage: same restrictions as the primary destination
        cold_r: Optional[Path] = None
        if self._cold is not None:
            cold_r = self._validate_cold(self._cold, src_r, dst_r)
            if cold_r is None:
                return None  # rejected inside _validate_cold (notified there)

        fmt = str(self.query_one("#fmt-select", Select).value)
        device_map = devices.load(self.devices_path)
        return RunRequest(src_r, dst_r, cold_r, fmt, dry_run, device_map)

    def _validate_cold(self, cold: Path, src_r: Path, dst_r: Path) -> Optional[Path]:
        """Validate the cold-storage path; None = rejected (notification shown).

        Restrictions mirror the primary destination: not inside the source,
        not equal to / nested with the destination. Validation happens BEFORE
        mkdir so a rejected path never touches the source tree; on success the
        folder is created (also on dry run, mirroring the primary destination).
        """
        cold = cold.expanduser()
        cold_r = cold.resolve()
        if cold_r == src_r or src_r in cold_r.parents:
            self.notify("⚠️ Cold storage must not be inside the source folder.", severity="error")
            return None
        if cold_r == dst_r or dst_r in cold_r.parents or cold_r in dst_r.parents:
            self.notify(
                "⚠️ Cold storage must differ from the destination and not contain it (or be inside it).",
                severity="error",
            )
            return None
        try:
            cold.mkdir(parents=True, exist_ok=True)  # mirror primary (also on dry run)
        except OSError as exc:
            self.notify(f"⚠️ Cannot create cold storage: {exc}", severity="error")
            return None
        return cold_r

    @work(thread=True, exclusive=True, group="archive")
    def _scan_and_plan(self, req: RunRequest) -> None:
        # Scan once against the primary destination (cold reuses these items)
        plan = archiver.scan(req.src, req.dst, req.fmt, req.device_map)
        self.app.call_from_thread(self._after_scan, req, plan)

    def _after_scan(self, req: RunRequest, plan: archiver.ScanResult) -> None:
        for err in plan.errors:
            self._log_error(err)
        self._set_stats(
            {
                "scanned": str(len(plan.items) + plan.skipped),
                "media": str(len(plan.items)),
                "images": str(plan.images),
                "videos": str(plan.videos),
                "non_media": str(plan.skipped),
            }
        )
        self._ext_counts = dict(plan.by_ext)
        self._set_stats(
            {"planned": str(len(plan.items)), "bytes": human_size(plan.total_size)}
        )

        if not plan.items:
            self.notify("ℹ️ No media files found in the source folder.", severity="information")
            return

        if plan.unknown_devices:
            def got(mapping: Optional[dict[str, str]]) -> None:
                self._after_device_names(req, plan, mapping)
            self.push_screen(DeviceNamingScreen(plan.unknown_devices), got)
            return

        self._begin_resolution(req, plan)

    def _after_device_names(
        self,
        req: RunRequest,
        plan: archiver.ScanResult,
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
        self._begin_resolution(replace(req, device_map=merged), plan)

    def _begin_resolution(self, req: RunRequest, raw_plan: archiver.ScanResult) -> None:
        """Build one plan per destination (reusing the scanned items) and resolve.

        apply_device_names recomputes dest_dir from the friendly names AND
        rebuilds the conflict list against the given root — so each destination
        gets its own conflicts without re-walking the source.
        """
        roots = [req.dst] + ([req.cold] if req.cold is not None else [])
        targets = [
            (archiver.apply_device_names(raw_plan, req.device_map, req.fmt, root), root)
            for root in roots
        ]
        self._set_stat("folders", str(targets[0][0].folders_to_create))  # primary
        self._set_stat(
            "conflicts", str(sum(len(plan.conflicts) for plan, _root in targets))
        )
        self._resolve_conflicts(req, targets)

    def _resolve_conflicts(
        self, req: RunRequest, targets: list[tuple[archiver.ScanResult, Path]]
    ) -> None:
        groups = [(root, plan.conflicts) for plan, root in targets if plan.conflicts]
        if groups:
            policy = self._conflict_policy()
            if policy == "ask":
                def got(action: str) -> None:
                    self._after_conflicts(req, targets, action)
                self.push_screen(ConflictScreen(groups), got)
                return
            action = policy  # "rename" | "overwrite" | "skip"
        else:
            action = "rename"  # no conflicts; action is irrelevant
        self._after_conflicts(req, targets, action)

    def _after_conflicts(
        self,
        req: RunRequest,
        targets: list[tuple[archiver.ScanResult, Path]],
        action: str,
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
        self._do_copy(req, resolved)

    @work(thread=True, exclusive=True, group="archive")
    def _do_copy(
        self,
        req: RunRequest,
        resolved: list[tuple[archiver.ScanResult, Path]],
    ) -> None:
        reports = [
            archiver.execute(plan, root, req.dry_run, on_progress=self._progress_from_thread)
            for plan, root in resolved
        ]
        primary = reports[0]
        cold_report = reports[1] if len(reports) > 1 else None
        self.app.call_from_thread(self._after_copy, req, primary, cold_report)

    def _progress_from_thread(self, message: str, kind: str) -> None:
        self.app.call_from_thread(self._log, message, kind)

    def _after_copy(
        self,
        req: RunRequest,
        report: archiver.CopyReport,
        cold_report: Optional[archiver.CopyReport],
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
        verb = "would be copied" if req.dry_run else "copied"
        icon = "🧪" if req.dry_run else "📦"
        msg = f"{icon} {'Dry run complete' if req.dry_run else 'Archive complete'} — {report.copied} files {verb}"
        if cold_report is not None:
            msg += f" (+{cold_report.copied} to cold storage)"
        self.notify(msg + ".")
