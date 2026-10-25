# MEMORY.md — Photo Archiver (photoArch)
Project Memory between sessions. Maximum ~50 lines: summarize or remove anything that no longer adds value.
## Current Status
- v0.1.10 Omarchy theme adaptation (smoke+theme+e2e green): NEW photoarch/theming.py
  reads the resolved palette ~/.local/state/omarchy/current/theme/colors.toml +
  theme.name (stdlib tomllib), builds Textual Theme + Rich ANSI TerminalTheme;
  app._apply_omarchy_theme() runs first in on_mount; NEW tests/theme_test.py.
- v0.1.9 (frozen, tests green): conflict policy single source in settings.py,
  RunRequest pipeline, modals in screens.py, fused Results tab, tests/helpers.py.
- Installed copy at ~/.local/share/photoArch — re-copy photoarch/*.py after
  updates (last synced 2026-10-25 = v0.1.10; venv kept, __pycache__ cleared).
- Skills installed in .agents/skills/. Tooling NOT adopted (ruff/mypy/pytest/uv
  = new deps, forbidden) — tests stay plain asyncio scripts.
## Decisions (and why)
- Easy to run. Exec only with run.sh.
- Theme: ALWAYS-ON when detected, startup-only (no live reload), silent per-key
  fallback to Textual defaults; never shells out to `omarchy` (state dir is the
  already-merged stock+overlay palette). Mapping: blue→primary, yellow→warning
  (orange==accent in Coppernight), lighter_background→surface, selection→panel,
  muted→secondary, mode→dark (light themes get light UI); log ANSI colors from
  the same palette (Omarchy's own terminal map); button-color-foreground =
  contrast vs primary (default would be light-on-light-blue).
- Conflicts: one action for all ("Apply to all"); no per-file decisions.
- EXIF fallback — date→mtime; device→"Unknown device"(images)/"Videos"(videos)/
  "WhatsApp": folder labels, never prompted/stored. WA regex `-\d{8}-WA\d{4}$`
  on stem, filename wins over EXIF, metadata never read.
- Non-media/hidden skipped. Video device = pure struct parser (©mak/©mod +
  Apple mdta, no ffmpeg), else "Videos"; video date stays mtime.
- devices.json: exact-match raw→friendly, passed into scan() as a param
  (archiver never reads config files). Naming mandatory post-scan/pre-conflict,
  even for formats without {device} and on dry run; empty input = raw name.
  Editing JSON later does not migrate folders.
- Stats + activity log fused in ONE "📊 Results" tab (#stats-table/#results-log,
  log cap 2000 lines). Settings: restore on_mount, save ONLY on run start;
  tests override devices_path/settings_path BEFORE run_test.
- Cold storage: validated before mkdir (never inside source / nested with
  primary); ONE scan → plan per root via apply_device_names; combined dialog,
  per-root action; stats = primary rows + cold_copies/cold_bytes. FUTURE:
  read source once per run, fan out bytes to both roots.
- Sidebar compact: flat 1-row buttons, #clear-cold only while set, 1-row
  $accent banner (~32-row terminals, no scrolling).
- Refactors freeze behavior: widget ids, CSS, notification texts, pipeline
  order and `from photoarch.app import ...` re-exports untouched.
## Lessons Learned and Mistakes to Avoid
- TabPane height:auto → 0-height collapse (log defers writes, table renders
  nothing). Fix: #tab-results height:100%, table max-height:60%, log
  min-height:6. ALWAYS assert layout sizes — data-only asserts pass collapsed.
- theming._FIELD_MAP is colors.toml key→Theme field: the dict comprehension
  unpacked it backwards once (KeyError at startup). Watch .items() order.
- Changing item.dest_dir invalidates the conflict list — rebuild via
  archiver.apply_device_names().
- fr units inside auto-height modals stretch them to fullscreen and
  pilot.click() misses buttons → fixed max-height rows.
- MP4 atom types EXACTLY 4 bytes ("©mod"); meta carries 4 version/flags bytes
  before its children.
- Pilot: clicks within 0.2s debounce ignored (pause 0.25); display toggles
  reflow the sidebar (pause after relayout); DataTable: use row_key.value.
- Any test creating PhotoArchApp must override settings_path before run_test
  (and theme_state_dir when the theme must be deterministic).
- EXIF ASCII fields are NUL-padded — sanitize in metadata._device_name or
  mkdir raises ValueError.
## Next Steps
- (blank for now)
