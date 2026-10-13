"""Last-used run settings (source, destination, format, conflict policy).

The JSON lives OUTSIDE the source tree (user config, not archive data).
The archiver never reads this file: the app loads it on mount to prefill
the widgets and saves it when a run starts.

File layout: {"source": "/path", "dest": "/path",
              "format": "year_month", "conflict": "ask"}
"""

from __future__ import annotations

import json
from pathlib import Path

from .devices import APP_CONFIG_DIR
from .organizer import FORMATS

SETTINGS_FILE = APP_CONFIG_DIR / "settings.json"

DEFAULTS = {"source": "", "dest": "", "format": "year_month", "conflict": "ask"}

# conflict policy values, matching the sidebar RadioSet options
CONFLICT_ACTIONS = ("ask", "rename", "overwrite", "skip")


def load(path: Path = SETTINGS_FILE) -> dict[str, str]:
    """Return the settings merged over the defaults.

    Tolerant by design: a missing, unreadable or corrupt file yields the
    defaults; empty paths and unknown format/conflict values are dropped
    back to their defaults too.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    source = data.get("source")
    dest = data.get("dest")
    if isinstance(source, str) and source:
        out["source"] = source
    if isinstance(dest, str) and dest:
        out["dest"] = dest
    if data.get("format") in FORMATS:
        out["format"] = str(data["format"])
    if data.get("conflict") in CONFLICT_ACTIONS:
        out["conflict"] = str(data["conflict"])
    return out


def save(settings: dict[str, str], path: Path = SETTINGS_FILE) -> bool:
    """Persist the settings (full rewrite, invalid values sanitized).
    Returns False on I/O failure."""
    fmt = settings.get("format")
    conflict = settings.get("conflict")
    payload = {
        "source": str(settings.get("source", "")),
        "dest": str(settings.get("dest", "")),
        "format": str(fmt) if fmt in FORMATS else DEFAULTS["format"],
        "conflict": str(conflict) if conflict in CONFLICT_ACTIONS else DEFAULTS["conflict"],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        path.write_text(text + "\n", encoding="utf-8")
        return True
    except OSError:
        return False
