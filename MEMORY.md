# MEMORY.md — Photo Archiver (photoArch)
Project Memory between sessions. Maximum ~50 lines: summarize or remove anything that no longer adds value.
## Current Status
- v0.1.6: TUI archives photos/videos by EXIF date+device with friendly device
  names (Devices tab renames/removes); WhatsApp-named files skip metadata;
  video device via pure ISO-BMFF parser; last-used settings incl. optional
  cold storage (2nd destination) in ~/.config/photoarch/settings.json.
## Decisions (and why)
- Easy to run. Exec only with run.sh.
- Conflict granularity — one action for all conflicts ("Apply to all"); no per-file decisions (kept it simple).
- EXIF fallback — no capture date → mtime; no device → "Unknown device" (images) /
  "Videos" (videos). Never prompted/stored in devices.json.
- WhatsApp — regex `-\d{8}-WA\d{4}$` on the stem; date from name (mtime fallback),
  device fixed "WhatsApp"; metadata never read (user chose filename wins even when
  EXIF survives — time-of-day lost).
- Non-media files (.txt, sidecars…) are "skipped"; hidden files/dirs ignored.
- Video device — pure struct parser (no ffmpeg): ©mak/©mod (ilst+udta) + Apple mdta;
  other containers → "Unknown device". Video date stays mtime.
- Device names — devices.json (exact-match raw "Make Model" → friendly); archiver gets
  the mapping as a parameter, never reads the file. Prompt after scan, BEFORE conflict
  resolution, even for formats without {device} and during dry run (naming mandatory;
  empty input = raw name). Editing JSON later does not migrate folders. Panel:
  save/remove rewrite the file; remove → re-prompted next run; mapping read at run start.
- Stats — images/videos rows + per-extension rows from ScanResult.by_ext (count desc).
  Tests override `app.devices_path`.
- Settings — restored in on_mount (vanished folder kept as-is, validated at run), saved
  ONLY when a run starts after path validation. Tests override `app.settings_path`
  BEFORE run_test.
- Cold storage — validated before mkdir (never inside source, never equal/nested with
  primary); ONE scan vs primary, cold plan rebuilt via apply_device_names (no 2nd walk);
  combined dialog, action applied per root independently (per-dest suffixes); dry run
  mirrors primary; stats = primary rows + cold_copies/cold_bytes. Source IS read once
  per destination at copy time — FUTURE OPTIMIZATION: read once, fan out bytes.
- Installed copy at ~/.local/share/photoArch (photoarch/*.py + requirements.txt +
  run.sh). Re-copy after updates.
## Lessons Learned and Mistakes to Avoid
- Changing item.dest_dir after scan invalidates the conflict list — rebuild via
  archiver.apply_device_names() (shares _plan_dests with scan()).
- `fr` units inside an auto-height modal stretch it to full screen and
  pilot.click() misses buttons silently; use fixed max-height rows.
- MP4 atom types are EXACTLY 4 bytes ("©mod", never "©modl"), and `meta` carries
  4 version/flags bytes before its children — both cost real debugging time.
- Pilot: repeat clicks within Button.active_effect_duration (0.2s) are ignored —
  pause(0.25) after clicks. DataTable RowKey: use row_key.value, not str().
- Any test creating PhotoArchApp must override settings_path (before run_test).
- EXIF ASCII fields are NUL-padded (WA jpegs) — .strip() won't remove \x00;
  sanitize in metadata._device_name or mkdir raises ValueError.
## Next Steps
- (blank for now)
