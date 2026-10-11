# photoArch 🖼️

Terminal app (TUI) to archive and organize your photo/video files by their
metadata (capture date, camera device) — the source folder is **never modified**.

## Features

- 📂 **Folder selector** for the source folder (photos are only read, never changed)
- 🎯 **Folder selector** for the destination archive
- 🗂️ **Destination formats**: `YYYY/MM`, `YYYY/MM/DD`, `YYYY/MM - Device`,
  `Device/YYYY/MM`, `YYYY/YYYY-MM-DD`
- 🧩 **Conflict handling**: when a file name already exists at the destination
  (or duplicates inside the batch), a dialog asks you to auto-rename (default),
  overwrite, or skip — or you can preset a global policy
- 🧪 **Dry run** button: full preview of what would be copied without writing anything
- 📊 **Statistics & results**: files scanned/found/copied, folders created,
  size, conflicts, and per-file error details
- 🌌 Unicode icons throughout the UI

## Requirements

- Python 3.10+ (tested on 3.14)
- Dependencies (see `requirements.txt`): `textual`, `pillow`

## How to run

```bash
./run.sh
```

The script reuses the project `venv/`, installs dependencies on first run,
and launches the app. Keybindings: `d` = dry run, `a` = archive, `q` = quit.

## Tests

```bash
./venv/bin/python tests/smoke_test.py   # core logic + TUI smoke test
./venv/bin/python tests/e2e_test.py     # full dry-run/archive/conflict flow
```

## Safety rules

- The source tree is opened **read-only**; all writes go to the destination.
- The destination must not be inside the source folder (validated).
- Copy uses `shutil.copy2`, preserving file metadata/timestamps.
