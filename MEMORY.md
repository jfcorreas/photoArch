# MEMORY.md — Photo Archiver (photoArch)
Project Memory between sessions. Maximum ~50 lines: summarize or remove anything that no longer adds value.
## Current Status
- v0.1.4: TUI archives photos/videos by EXIF date+device; devices get user-chosen
  friendly names reused later (Devices tab renames/removes). Videos get their device
  from a pure ISO-BMFF parser; stats show images/videos counts + formats. Last-used
  source/dest/format/conflict persisted in ~/.config/photoarch/settings.json.
## Decisions (and why)
- Easy to run. Exec only with run.sh.
- Conflict granularity — the dialog resolves all conflicts with one action ("Apply to all"); per-file decisions are not offered (kept it simple).
- EXIF fallback — files without capture date fall back to mtime; missing device
  → "Unknown device" (images) or "Videos" (videos, e.g. Xiaomi MP4s carry no
  make/model at all). Both labels are never prompted/stored in devices.json.
- Non-media files (.txt, sidecars…) are counted as "skipped"; hidden files/dirs ignored.
- Video device — pure stdlib struct parser (no ffmpeg/ffprobe, see AGENTS.md invariant):
  covers .mp4/.mov/.m4v/.3gp via ©mak/©mod (ilst + udta strings) and Apple's
  meta/keys mdta registry; .mkv/.avi/.mts/.webm stay "Unknown device" (add on demand).
  Video date stays mtime.
- Device names — JSON at ~/.config/photoarch/devices.json (exact-match keys, raw
  EXIF "Make Model" → friendly name); archiver gets the mapping as a parameter,
  never reads the file. Prompt appears after scan, BEFORE conflict resolution,
  even for formats without {device} and during dry run (naming mandatory; empty
  input = raw name, still stored). Editing the JSON later does not migrate
  already-created folders.
- Devices panel — save/remove rewrite devices.json (file is the truth: table
  reloads on tab activation and after the naming modal saves). Remove → device
  re-prompted next run; rename never moves folders of earlier runs. Mapping is
  read at run start → mid-run edits apply next run.
- Stats — images/videos rows + dynamic per-extension rows from ScanResult.by_ext,
  grouped under their kind row (count desc). Tests override `app.devices_path`.
- Settings — settings.json in ~/.config/photoarch (same tolerant pattern as
  devices.json); restored in on_mount (even a vanished folder, validated at
  run), saved ONLY when a run starts AND after path validation (user choice).
  Tests override `app.settings_path` BEFORE run_test (restore is in on_mount).
- Installed copy at ~/.local/share/photoArch (photoarch/*.py + requirements.txt
  + run.sh only; venv built on first run). Re-copy those files after updates.
## Lessons Learned and Mistakes to Avoid
- Changing item.dest_dir after scan invalidates the conflict list — always rebuild
  it via archiver.apply_device_names() (shares _plan_dests with scan()).
- `fr` units (max-height: 1fr) inside an auto-height modal stretch it to full
  screen and pilot.click() misses buttons silently; use fixed max-height rows.
- MP4 atom types are EXACTLY 4 bytes ("©mod", never "©modl"), and `meta` carries
  4 version/flags bytes before its children — both cost real debugging time.
- Pilot: repeat clicks on the same button within Button.active_effect_duration
  (0.2s, the `-active` class) are silently ignored — pause(0.25) after clicks.
- DataTable RowKey: str(row_key) is the object repr, use row_key.value. TabbedContent /
  ContentSwitcher / TabPane all default height:auto — fr/% inside a pane only resolve
  after explicit heights on #tabs + its ContentSwitcher; #content width:100% laid the
  content out wider than the screen (buttons unclickable) → changed to 1fr.
- Any test creating PhotoArchApp must override settings_path (before run_test).
- EXIF ASCII fields are fixed-width and NUL-padded (WA-forwarded jpegs) —
  .strip() doesn't remove \x00; sanitize in metadata._device_name (control
  chars dropped) or folder names get NULs and mkdir raises ValueError
  (archiver catches only OSError).
## Next Steps
- (blank for now)
