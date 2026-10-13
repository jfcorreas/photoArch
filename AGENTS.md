# AGENTS.md - Photo Archiver (photoArch)

Terminal (Textual) app that archives photos/videos by EXIF metadata. Python 3.14,
deps: `textual` (8.x) + `pillow`. Source tree is **read-only by design** — never
write, move, or delete anything under the user's source folder; all writes go to
the destination root.

## Commands

- Run app: `./run.sh` (uses `venv/`, auto-installs `requirements.txt` on first run)
- Tests: `./venv/bin/python tests/smoke_test.py` then `tests/e2e_test.py`
  - No pytest; plain asyncio scripts using `App.run_test()` pilot. Each prints ✅/raises on failure.
  - TUI tests need `await asyncio.sleep(...)` after button clicks: scan/copy run in
    `@work(thread=True)` workers, and `pilot.pause()` alone does not wait for them.
- There is no lint/typecheck/CI config in this repo.

## Layout

- `photoarch/archiver.py` — pure logic (no UI): `scan()` builds the plan,
  `apply_resolution(plan, action, dest_root)` applies rename/overwrite/skip,
  `execute()` copies (honors `dry_run`). Keep UI out of this file; it is fully
  unit-testable headlessly. `ScanResult` also carries the media statistics
  (`images`, `videos`, `by_ext` counts) that the app renders.
- `photoarch/organizer.py` — media extension sets + `FORMATS` dict
  (key → (label, template)). Adding a destination format = one dict entry.
- `photoarch/metadata.py` — EXIF date/device with mtime fallback; missing device
  → "Unknown device" for images, **"Videos" for videos** (both are folder
  labels, never prompted/stored in devices.json).
  WhatsApp-named files (`*-YYYYMMDD-WA####`, generic regex on the stem) skip
  metadata entirely: date from the filename (mtime fallback), device
  **"WhatsApp"** (also a never-prompted label, for both images and videos).
  Videos get their **device** from a pure-stdlib ISO-BMFF parser (atom types are
  exactly 4 bytes: `©mak`/`©mod` in ilst AND as udta strings, plus Apple's
  `meta/keys` mdta registry — iPhone style); never reads `mdat`, never raises.
  Video **date** stays mtime.
- `photoarch/devices.py` — device → friendly-name JSON mapping
  (`~/.config/photoarch/devices.json`, exact-match keys). Tolerant loader
  (missing/corrupt file → `{}`); `save()` returns False on I/O failure.
- `photoarch/settings.py` — last-used run settings JSON
  (`~/.config/photoarch/settings.json`: source, dest, cold_dest, format, conflict
  policy; `cold_dest:""` = no cold storage). Same tolerant load/save pattern;
  invalid values fall back to defaults.
- `photoarch/app.py` — the TUI: `DirectoryScreen` (folder picker modal),
  `ConflictScreen` (takes `groups: list[(dest_root, conflicts)]`, returns
  "rename"/"overwrite"/"skip"/"cancel"),
  `DeviceNamingScreen` (returns {raw_device: friendly_name} or None),
  Devices tab (rename/remove known devices; writes only `devices.json`),
  `PhotoArchApp`. Cold storage = optional 2nd destination: ONE scan against the
  primary root, then a plan per root via `apply_device_names(raw, map, fmt, root)`
  (no second walk); the run threads `targets: list[(ScanResult, Path)]` through
  `_begin_resolution` → `_resolve_conflicts` → `_after_conflicts` → `_do_copy`.

## Textual 8.x gotchas (cost real debugging time — do not "simplify" these away)

- `TabbedContent` accepts **title strings only** as positional args; `TabPane`
  objects are added later via `await tabs.add_pane(TabPane(...))` in an **async**
  `on_mount`. Passing `TabPane`s to the constructor raises AttributeError, and
  `add_pane` is async — querying pane children immediately after without `await`
  gives NoMatches.
- `RichLog.write` **defers all renders while the widget is hidden** (inactive tab,
  size unknown): `log.lines` stays empty until the tab is shown. In tests, switch
  `tabs.active = "tab-results"` before asserting on `log.lines`.
- `OptionList`: `str(option)` is the repr (`"Option('x/')"`), never the label.
  Use `event.option_index` and keep your own index→value map (`DirectoryScreen._entries`).
- Simulate list selection in tests with `listing.highlighted = idx` + `listing.action_select()`;
  setting the private `listing._highlighted` bypasses the reactive and breaks messages.
- Worker threads must reach the UI via `self.app.call_from_thread(...)`, never touch
  widgets directly (see `_scan_and_plan` / `_do_copy` in `app.py`).
- In an auto-height modal (`height: auto`), **never size children with `fr` units**
  (`max-height: 1fr`): the dialog stretches to full screen and `pilot.click()`
  silently misses the buttons. Use a fixed `max-height: <rows>`.

## Invariants (enforced in `PhotoArchApp._run` + `archiver`)

- Destination must not equal or be inside the source (validated before any work).
- Cold storage (optional): validated BEFORE `mkdir` (a rejected path never
  touches the source tree) — not inside source, not equal to the primary dest,
  not nested either way with it. Same restrictions/conflict rules/format/names
  as primary; one combined conflict dialog, the chosen action applies
  independently per destination (a file can conflict in one root only).
  Settings: `cold_dest`, cleared via the sidebar's Clear button (persisted as
  `""` on the next run start). Stats: existing rows = primary, plus
  `cold_copies`/`cold_bytes`; `errors` = both roots combined.
- Conflict handling: in-batch duplicate names and existing destination files both
  produce `Conflict`s; default action is auto-rename (`stem_1.ext`, checked against
  disk AND the in-batch set).
- `shutil.copy2` preserves metadata; tests assert the source tree is byte-identical
  after runs (`tests/e2e_test.py`).
- Device friendly names: the JSON lives OUTSIDE the source tree
  (`~/.config/photoarch/devices.json`, path in `devices.py`). The mapping is
  passed into `scan(source, dest, fmt, device_map)` / `apply_device_names()` —
  the archiver never reads the file itself. "Unknown device", "Videos" and
  "WhatsApp" are never prompted or stored; naming is mandatory for every other
  new device (empty input = raw name, still stored).
- WhatsApp-named files (`*-YYYYMMDD-WA####`, generic regex on the stem) skip
  metadata parsing entirely: date comes from the filename (mtime fallback),
  device is the fixed "WhatsApp" label — never read EXIF/atoms for them.
- Last-used settings (`settings.py`, same `~/.config/photoarch/` rule): loaded
  in `on_mount` (tests override `app.settings_path` **before** `run_test`),
  saved only when a run starts, after path validation. The archiver never
  reads this file either.
- Media metadata is parsed with **pure stdlib** (struct) — never add
  ffmpeg/ffprobe or any media library; that applies to video device AND video
  date (mtime) parsing.

## Memory
- When you start, read `MEMORY.md` to understand the project’s status and the decisions that have been made.
- When you finish a task, update it: current status, important decisions (with the reasons behind them), and pitfalls to avoid.
- Keep it brief (maximum ~50 lines): summarize or remove anything that is no longer relevant.
- If something becomes a permanent rule, suggest moving it to `AGENTS.md` instead of leaving it in the memory.
- Never store sensitive data (passwords, tokens, personal information).

# Way of working
- Just do what's asked: don't add features on your own.
- Make small, focused changes; don't rewrite what already works.
- When you're done, summarize what you've changed and any decisions that need to be reviewed

## Limits
-✅ Always: mantain an easy of use interface for the user
-✅ Allways: update `MEMORY.md` at the end of each task
-⚠️ Ask before: create new files
-🚫 Never: add by your own new dependencies, frameworks or build steps

## Verify
- Test the application and give me a brief of the tests
