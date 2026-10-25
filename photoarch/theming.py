"""Adapt the TUI to the current Omarchy theme, when one is available.

Reads the palette Omarchy has already resolved for the terminal:

    ~/.local/state/omarchy/current/theme/colors.toml  (stock + user overlay merged)
    ~/.local/state/omarchy/current/theme.name         (slug, e.g. "coppernight")

Pure logic, no UI imports: builds a Textual Theme (CSS variables) and a Rich
TerminalTheme (ANSI colors for the activity log). Tolerant by design: a
missing/corrupt colors.toml yields None and the caller keeps Textual's default
look. Never shells out to the `omarchy` CLI.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from rich.console import TerminalTheme
from textual.color import Color
from textual.theme import BUILTIN_THEMES, Theme

STATE_DIR = Path.home() / ".local" / "state" / "omarchy" / "current"

# colors.toml key -> Theme field. Missing keys fall back per-field to the
# Textual builtin theme of the same mode (defaults-dict overlay).
_FIELD_MAP = {
    "background": "background",
    "foreground": "foreground",
    "lighter_background": "surface",
    "selection": "panel",
    "muted": "secondary",
    "yellow": "warning",
    "red": "error",
    "green": "success",
    "accent": "accent",
}
# fields whose key is not 1:1 with colors.toml: first present key wins
_CHAINS = {
    "primary": ("blue", "accent"),
    "accent": ("accent", "blue"),
    "secondary": ("muted", "foreground"),
    "warning": ("yellow", "orange"),
}


def _hex(value: object) -> bool:
    return isinstance(value, str) and value.startswith("#")


def load_palette(state_dir: Path = STATE_DIR) -> dict | None:
    """Return the colors.toml mapping, or None if unavailable/corrupt.

    Tolerant per key: non-color values are dropped, everything else kept
    (missing keys are handled at build time, not here).
    """
    try:
        data = tomllib.loads((state_dir / "theme" / "colors.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    palette = {str(k): v for k, v in data.items() if _hex(v) or k == "mode"}
    return palette or None


def load_slug(state_dir: Path = STATE_DIR) -> str:
    """Return the current theme slug (safe for a Textual theme name)."""
    try:
        raw = (state_dir / "theme.name").read_text(encoding="utf-8").strip()
    except OSError:
        return "custom"
    slug = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-_")
    return slug or "custom"


def _pick(colors: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = colors.get(key)
        if _hex(value):
            return value
    return None


def build_theme(colors: dict, slug: str) -> Theme:
    """Build the Textual theme for a colors.toml mapping (per-key fallback)."""
    dark = str(colors.get("mode", "dark")).lower() != "light"
    base = BUILTIN_THEMES["textual-dark" if dark else "textual-light"]

    values = {field: _pick(colors, (key,)) for key, field in _FIELD_MAP.items()}
    for field, keys in _CHAINS.items():
        values[field] = _pick(colors, keys)
    # explicit keys first, then the builtin defaults for this mode
    primary = values["primary"] or base.primary
    theme = Theme(
        name=f"omarchy-{slug}",
        primary=primary,
        secondary=values["secondary"] or base.secondary,
        warning=values["warning"] or base.warning,
        error=values["error"] or base.error,
        success=values["success"] or base.success,
        accent=values["accent"] or base.accent,
        foreground=values["foreground"] or base.foreground,
        background=values["background"] or base.background,
        surface=values["surface"] or base.surface,
        panel=values["panel"] or base.panel,
        dark=dark,
    )
    # text on primary-colored widgets (buttons): contrast vs the primary color
    theme.variables = {
        "button-color-foreground": Color.parse(primary).get_contrast_text(1.0).hex
    }
    return theme


def _rgb(value: object, default: tuple[int, int, int]) -> tuple[int, int, int]:
    """Parse '#rrggbb' (or '#rgb') into a Rich color triplet."""
    if not _hex(value):
        return default
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    try:
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
    except ValueError:
        return default


def build_ansi_theme(colors: dict) -> TerminalTheme:
    """Build the Rich ANSI theme for the activity log (Omarchy terminal map).

    Same mapping Omarchy uses to generate its terminal configs: normal black =
    background / white = foreground, bright black = muted / white = bright fg.
    """
    get = colors.get
    background = _rgb(get("background"), (0, 0, 0))
    foreground = _rgb(get("foreground"), (229, 229, 229))
    normal = [
        background,
        _rgb(get("red"), (205, 0, 0)),
        _rgb(get("green"), (0, 205, 0)),
        _rgb(get("yellow"), (205, 205, 0)),
        _rgb(get("blue"), (0, 0, 238)),
        _rgb(get("magenta"), (205, 0, 205)),
        _rgb(get("cyan"), (0, 205, 205)),
        foreground,
    ]
    bright = [
        _rgb(get("muted"), (127, 127, 127)),
        _rgb(get("bright_red", get("red")), (255, 0, 0)),
        _rgb(get("bright_green", get("green")), (0, 255, 0)),
        _rgb(get("bright_yellow", get("yellow")), (255, 255, 0)),
        _rgb(get("bright_blue", get("blue")), (0, 0, 255)),
        _rgb(get("bright_magenta", get("magenta")), (255, 0, 255)),
        _rgb(get("bright_cyan", get("cyan")), (0, 255, 255)),
        _rgb(get("bright_foreground", get("foreground")), (255, 255, 255)),
    ]
    return TerminalTheme(background, foreground, normal, bright)
