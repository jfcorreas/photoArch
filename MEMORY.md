# MEMORY.md — Photo Archiver (photoArch)
Project Memory between sessions. Maximum ~50 lines: summarize or remove anything that no longer adds value.
## Current Status
- v0.1.9 clarity refactor (behavior frozen; smoke+e2e green): conflict policy
  single source in settings.py (CONFLICT_POLICIES → RadioSet build + restore/
  save/resolve, app._conflict_policy()); _set_stats batches table renders;
  _validate_cold() split from _validate_run; archiver: _count_folders,
  _needs_naming + _PROMPT_EXEMPT, seen_dests is a set, conflict key = id(item)
  (conflicts always reference items of the same result); metadata WA date =
  one regex search (_wa_date(match)); tests share tests/helpers.py
  (make_photo/make_video). v0.1.8 before it: modals in screens.py, frozen
  RunRequest pipeline, _pick_folder.
- Installed copy at ~/.local/share/photoArch — re-copy after updates.
- Skills installed in .agents/skills/. Tooling NOT adopted (ruff/mypy/pytest/uv
  = new deps, forbidden) — tests stay plain asyncio scripts.
## Decisions (and why)
- Easy to run. Exec only with run.sh.
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
- Changing item.dest_dir invalidates the conflict list — rebuild via
  archiver.apply_device_names().
- fr units inside auto-height modals stretch them to fullscreen and
  pilot.click() misses buttons → fixed max-height rows.
- MP4 atom types EXACTLY 4 bytes ("©mod"); meta carries 4 version/flags bytes
  before its children.
- Pilot: clicks within 0.2s debounce ignored (pause 0.25); display toggles
  reflow the sidebar (pause after relayout); DataTable: use row_key.value.
- Any test creating PhotoArchApp must override settings_path before run_test.
- EXIF ASCII fields are NUL-padded — sanitize in metadata._device_name or
  mkdir raises ValueError.
## Next Steps
- (blank for now)
