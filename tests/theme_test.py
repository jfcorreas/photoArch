"""Headless tests for the Omarchy theme adaptation (photoarch.theming + app wiring)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photoarch import theming
from photoarch.app import PhotoArchApp

# a trimmed copy of a real Omarchy colors.toml (Coppernight, dark)
COLORS_DARK = """mode = "dark"

accent = "#fab387"
cursor = "#ed8796"
selection = "#313244"
muted = "#5b6078"

background = "#11111b"
dark_background = "#0b0b12"
darker_background = "#060609"
lighter_background = "#1e1e2e"

foreground = "#cad3f5"
dark_foreground = "#6e738d"
light_foreground = "#b8c0e0"
bright_foreground = "#cad3f5"

red = "#ed8796"
yellow = "#eed49f"
orange = "#fab387"
green = "#a6da95"
cyan = "#8bd5ca"
blue = "#8aadf4"
magenta = "#c6a0f6"

bright_red = "#ed8796"
bright_yellow = "#fab387"
bright_green = "#a6da95"
bright_cyan = "#8bd5ca"
bright_blue = "#8aadf4"
bright_magenta = "#c6a0f6"
"""

# light Omarchy theme (e.g. catppuccin-latte style)
COLORS_LIGHT = """mode = "light"

accent = "#1e66f5"
selection = "#ccd0da"
muted = "#acb0be"

background = "#eff1f5"
lighter_background = "#dce0e8"

foreground = "#4c4f69"
bright_foreground = "#4c4f69"

red = "#d20f39"
yellow = "#df8e1d"
green = "#40a02b"
cyan = "#179299"
blue = "#1e66f5"
magenta = "#ea76cb"
"""


def test_load_palette() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # missing state dir -> None
        assert theming.load_palette(root) is None
        # valid palette -> dict (mode kept, non-color values dropped)
        state = root / "state"
        (state / "theme").mkdir(parents=True)
        (state / "theme" / "colors.toml").write_text(COLORS_DARK, encoding="utf-8")
        palette = theming.load_palette(state)
        assert palette is not None and palette["accent"] == "#fab387", palette
        assert palette["mode"] == "dark"
        # corrupt TOML -> None (no exception)
        (state / "theme" / "colors.toml").write_text("not = valid toml [", encoding="utf-8")
        assert theming.load_palette(state) is None
        # parses but carries no colors -> None
        (state / "theme" / "colors.toml").write_text("[section]\nx = 1\n", encoding="utf-8")
        assert theming.load_palette(state) is None
        print("✅ load palette OK")


def test_load_slug() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)
        # missing file -> "custom"
        assert theming.load_slug(state) == "custom"
        (state / "theme.name").write_text("coppernight\n", encoding="utf-8")
        assert theming.load_slug(state) == "coppernight"
        (state / "theme.name").write_text("tokyo-night", encoding="utf-8")
        assert theming.load_slug(state) == "tokyo-night"
        # slug stays a safe Textual theme name
        (state / "theme.name").write_text("My Weird Theme! ", encoding="utf-8")
        assert theming.load_slug(state) == "my-weird-theme"
        (state / "theme.name").write_text("   ", encoding="utf-8")
        assert theming.load_slug(state) == "custom"
        print("✅ load slug OK")


def test_build_theme() -> None:
    palette = _parse(COLORS_DARK)

    theme = theming.build_theme(palette, "coppernight")
    assert theme.name == "omarchy-coppernight"
    assert theme.dark is True
    # mapping: blue->primary, yellow->warning, lighter_background->surface,
    # selection->panel, muted->secondary (never `orange`: it equals accent here)
    assert theme.primary == "#8aadf4", theme.primary
    assert theme.accent == "#fab387"
    assert theme.warning == "#eed49f"
    assert theme.error == "#ed8796"
    assert theme.success == "#a6da95"
    assert theme.secondary == "#5b6078"
    assert theme.background == "#11111b"
    assert theme.foreground == "#cad3f5"
    assert theme.surface == "#1e1e2e"
    assert theme.panel == "#313244"
    # button labels contrast against the primary color, not the background
    assert theme.variables["button-color-foreground"].startswith("#")

    # light theme -> light UI
    light = theming.build_theme(_parse(COLORS_LIGHT), "latte")
    assert light.dark is False
    assert light.primary == "#1e66f5"
    assert light.background == "#eff1f5"

    # partial palette: explicit keys win, the rest falls back per key
    partial = theming.build_theme({"accent": "#123456"}, "x")
    assert partial.primary == "#123456"  # blue missing -> accent chain
    assert partial.background is None  # textual-dark has no default background
    assert partial.warning == "#ffa62b"  # textual-dark default
    print("✅ build theme OK")


def test_build_ansi_theme() -> None:
    palette = _parse(COLORS_DARK)
    ansi = theming.build_ansi_theme(palette)
    assert tuple(ansi.background_color) == (17, 17, 27)  # background
    assert tuple(ansi.foreground_color) == (202, 211, 245)  # foreground #cad3f5
    # same map Omarchy uses for its terminals:
    # normal = background, red, green, yellow, blue, magenta, cyan, foreground
    assert tuple(ansi.ansi_colors[0]) == (17, 17, 27)
    assert tuple(ansi.ansi_colors[1]) == (237, 135, 150)  # red
    assert tuple(ansi.ansi_colors[7]) == (202, 211, 245)  # white = foreground
    # bright = muted, bright_*, bright_foreground
    assert tuple(ansi.ansi_colors[8]) == (91, 96, 120)  # bright black = muted
    assert tuple(ansi.ansi_colors[15]) == (202, 211, 245)  # bright white
    # partial palette still builds (defaults fill the gaps)
    fallback = theming.build_ansi_theme({"mode": "dark"})
    assert tuple(fallback.background_color) == (0, 0, 0)
    print("✅ build ansi theme OK")


async def test_app_applies_theme() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = root / "state"
        (state / "theme").mkdir(parents=True)
        (state / "theme" / "colors.toml").write_text(COLORS_DARK, encoding="utf-8")
        (state / "theme.name").write_text("coppernight", encoding="utf-8")

        app = PhotoArchApp()
        app.settings_path = root / "settings.json"  # never touch the real ~/.config file
        app.theme_state_dir = state  # fake Omarchy state dir
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "omarchy-coppernight", app.theme
            theme = app.current_theme
            assert theme.dark is True and theme.accent == "#fab387"
            # activity-log ANSI colors follow the palette too
            assert tuple(app.ansi_theme_dark.background_color) == (17, 17, 27)
            # CSS actually picked the values up (screen background = palette)
            assert app.screen.styles.background.hex.lower() == "#11111b"
    print("✅ app applies omarchy theme OK")


async def test_app_without_omarchy() -> None:
    """No Omarchy state (or corrupt palette) -> Textual default, no crash."""
    for payload in (None, "not = valid toml ["):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            if payload is not None:
                (state / "theme").mkdir(parents=True)
                (state / "theme" / "colors.toml").write_text(payload, encoding="utf-8")
                (state / "theme.name").write_text("coppernight", encoding="utf-8")
            app = PhotoArchApp()
            app.settings_path = root / "settings.json"
            app.theme_state_dir = state
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.theme == "textual-dark", app.theme  # default kept
                assert app.get_theme("omarchy-coppernight") is None
    print("✅ app default without omarchy OK")


def _parse(text: str) -> dict:
    """Minimal TOML parse for the inline palettes (tomllib, as production does)."""
    import tomllib

    data = tomllib.loads(text)
    return {k: v for k, v in data.items() if isinstance(v, str)}


def main() -> None:
    test_load_palette()
    test_load_slug()
    test_build_theme()
    test_build_ansi_theme()
    asyncio.run(test_app_applies_theme())
    asyncio.run(test_app_without_omarchy())
    print("\n🎉 All tests passed")


if __name__ == "__main__":
    main()
