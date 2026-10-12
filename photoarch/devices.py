"""Device -> friendly name mapping, persisted as a small JSON file.

The JSON lives OUTSIDE the source tree (user config, not archive data).
The archiver never reads this file itself: the app loads the mapping and
passes it into scan()/apply_device_names().

File layout: {"TestMake iPhone 13": "My iPhone", ...}  (exact-match keys)
"""

from __future__ import annotations

import json
from pathlib import Path

APP_CONFIG_DIR = Path.home() / ".config" / "photoarch"
DEVICES_FILE = APP_CONFIG_DIR / "devices.json"


def load(path: Path = DEVICES_FILE) -> dict[str, str]:
    """Return the device->friendly-name mapping.

    Tolerant by design: a missing, unreadable or corrupt file yields {}.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save(mapping: dict[str, str], path: Path = DEVICES_FILE) -> bool:
    """Persist the mapping (full rewrite). Returns False on I/O failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(mapping, indent=2, ensure_ascii=False, sort_keys=True)
        path.write_text(text + "\n", encoding="utf-8")
        return True
    except OSError:
        return False
