# MEMORY.md — Photo Archiver (photoArch)
Project Memory between sessions. Maximum ~50 lines: summarize or remove anything that no longer adds value.
## Current Status
- v0.1.5: TUI archives photos/videos by EXIF date+device; devices get user-chosen
  friendly names reused later (Devices tab renames/removes). WhatsApp-named files
  (*-YYYYMMDD-WA####) skip metadata: date from filename, device "WhatsApp". Videos
  get their device from a pure ISO-BMFF parser. Last-used run settings in
  ~/.config/photoarch/settings.json.
## Decisions (and why)
- Easy to run. Exec only with run.sh.
- Conflict granularity — the dialog resolves all conflicts with one action ("Apply to all"); per-file decisions are not offered (kept it simple).
- EXIF fallback — no capture date → mtime; no device → "Unknown device" (images)
  or "Videos" (videos, Xiaomi MP4s carry none). Never prompted/stored in devices.json.
- WhatsApp — generic regex `-\d{8}-WA\d{4}$` (any prefix, case-insensitive) on
  the stem; date from the name (mtime if garbage), device fixed "WhatsApp"
  (never-prompted label; manual devices.json override honored). Metadata never
  read for these files (stripped in ~85% anyway; user chose filename wins even
  when EXIF survives — time-of-day lost).
- Non-media files (.txt, sidecars…) are "skipped"; hidden files/dirs ignored.
- Video device — pure stdlib struct parser (no ffmpeg/ffprobe, see AGENTS.md invariant):
  ©mak/©mod (ilst + udta) + Apple mdta registry; other containers stay "Unknown
  device". Video date stays mtime.
- Device names — JSON at ~/.config/photoarch/devices.json (exact-match keys, raw
  EXIF "Make Model" → friendly name); archiver gets the mapping as a parameter,
  never reads the file. Prompt appears after scan, BEFORE conflict resolution,
  even for formats without {device} and during dry run (naming mandatory; empty
  input = raw name, still stored). Editing the JSON later does not migrate
  already-created folders.
- Devices panel — save/remove rewrite devices.json (file is the truth). Remove →
  device re-prompted next run; rename never moves earlier folders. Mapping read
  at run start → mid-run edits apply next run.
- Stats — images/videos rows + dynamic per-extension rows from ScanResult.by_ext
  under their kind row (count desc). Tests override `app.devices_path`.
- Settings — settings.json in ~/.config/photoarch (same tolerant pattern); restored
  in on_mount (vanished folder restored as-is, validated at run), saved ONLY when
  a run starts after path validation. Tests override `app.settings_path` BEFORE
  run_test (restore is in on_mount).
- Installed copy at ~/.local/share/photoArch (photoarch/*.py + requirements.txt
  + run.sh; venv on first run). Re-copy after updates.
## Lessons Learned and Mistakes to Avoid
- Changing item.dest_dir after scan invalidates the conflict list — rebuild via
  archiver.apply_device_names() (shares _plan_dests with scan()).
- `fr` units inside an auto-height modal stretch it to full screen and
  pilot.click() misses buttons silently; use fixed max-height rows.
- MP4 atom types are EXACTLY 4 bytes ("©mod", never "©modl"), and `meta` carries
  4 version/flags bytes before its children — both cost real debugging time.
- Pilot: repeat clicks on the same button within Button.active_effect_duration
  (0.2s, the `-active` class) are silently ignored — pause(0.25) after clicks.
- DataTable RowKey: str(row_key) is the object repr, use row_key.value. fr/%
  inside auto-height panes only resolve after explicit heights on the parents.
- Any test creating PhotoArchApp must override settings_path (before run_test).
- EXIF ASCII fields are fixed-width and NUL-padded (WA-forwarded jpegs) —
  .strip() doesn't remove \x00; sanitize in metadata._device_name or folder
  names get NULs and mkdir raises ValueError (archiver catches only OSError).
## Next Steps
- (blank for now)
