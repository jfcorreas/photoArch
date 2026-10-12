# MEMORY.md — Photo Archiver (photoArch)
Project Memory between sessions. Maximum ~50 lines: summarize or remove anything that no longer adds value.
## Current Status
- v1.1: TUI archives photos/videos by EXIF date+device. New devices are named by the
  user (mandatory) and the friendly name is reused in folder names on later runs.
## Decisions (and why)
- Easy to run. Exec only with run.sh.
- Conflict granularity — the dialog resolves all conflicts with one action ("Apply to all"); per-file decisions are not offered (kept it simple).
- EXIF fallback — files without capture date fall back to mtime; unknown device becomes "Unknown device" (never prompted/stored).
- Non-media files (.txt, sidecars…) are counted as "skipped"; hidden files/dirs ignored.
- Videos get no date EXIF parsing (would need ffmpeg-python); mtime is used.
- Device names — JSON at ~/.config/photoarch/devices.json (exact-match keys, raw
  EXIF "Make Model" → friendly name); archiver gets the mapping as a parameter,
  never reads the file. Prompt appears after scan, BEFORE conflict resolution,
  even for formats without {device} and during dry run (user decision: naming is
  mandatory; empty input = raw name, still stored). Editing the JSON later does
  not migrate already-created folders.
- Test override: `app.devices_path` lets tests use a temp JSON (never touch the real one).
## Lessons Learned and Mistakes to Avoid
- Changing item.dest_dir after scan invalidates the conflict list — always rebuild
  it via archiver.apply_device_names() (shares _plan_dests with scan()).
- `fr` units (max-height: 1fr) inside an auto-height modal stretch it to full
  screen and pilot.click() misses buttons silently; use fixed max-height rows.
## Next Steps
- (blank for now)
