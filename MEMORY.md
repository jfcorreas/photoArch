# MEMORY.md — Photo Archiver (photoArch)
Project Memory between sessions. Maximum ~50 lines: summarize or remove anything that no longer adds value.
## Current Status
- v0.1.2: TUI archives photos/videos by EXIF date+device. New devices are named by the
  user (mandatory) and the friendly name is reused in folder names on later runs.
  Videos get their device from a pure ISO-BMFF parser; stats panel shows
  images/videos counts with their formats listed under each (count desc).
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
- Stats — images/videos rows in STAT_ROWS + dynamic per-extension rows from
  ScanResult.by_ext, grouped under their kind row (IMAGE_EXTS / VIDEO_EXTS,
  count desc). Tests override `app.devices_path` (temp JSON).
- Installed copy at ~/.local/share/photoArch (photoarch/*.py + requirements.txt
  + run.sh only; venv built on first run). Re-copy those files after updates.
## Lessons Learned and Mistakes to Avoid
- Changing item.dest_dir after scan invalidates the conflict list — always rebuild
  it via archiver.apply_device_names() (shares _plan_dests with scan()).
- `fr` units (max-height: 1fr) inside an auto-height modal stretch it to full
  screen and pilot.click() misses buttons silently; use fixed max-height rows.
- MP4 atom types are EXACTLY 4 bytes ("©mod", never "©modl"), and `meta` carries
  4 version/flags bytes before its children — both cost real debugging time.
## Next Steps
- (blank for now)
