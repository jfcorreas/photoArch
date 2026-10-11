# MEMORY.md — Photo Archiver (photoArch)
Project Memory between sessions. Maximum ~50 lines: summarize or remove anything that no longer adds value.
## Current Status
- v1 up and running: TUI than permits the user to store photos from source folder to destination, organized by date and device obtained from metadata
## Decisions (and why)
- Easy to run. Exec only with run.sh
- Conflict granularity — the dialog resolves all conflicts with one action ("Apply to all"); per-file decisions are not offered (kept it simple).
- EXIF fallback — files without capture date (videos, screenshots, edited images) fall back to file modification time; unknown device becomes Unknown device.
- Non-media files (.txt, sidecars…) are counted as "skipped" and left untouched.
- Hidden files/dirs (dot-prefixed) are ignored entirely.
- Videos get no date EXIF parsing (would need an extra lib like ffmpeg-python); mtime is used.
## Lessons Learned and Mistakes to Avoid
- (blank for now)
## Next Steps
- (blank for now)