"""End-to-end TUI test: dry run, archive, and conflict modal via the pilot."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photoarch.app import DeviceNamingScreen, PhotoArchApp
from textual.widgets import Input, Select


def make_photo(path: Path, date: str | None = None, model: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        path.write_bytes(b"\x00fakevideo")
        return
    img = Image.new("RGB", (8, 8), color=(1, 2, 3))
    if date and model:
        exif = img.getexif()
        exif[36867] = date
        exif[271] = "TestMake"
        exif[272] = model
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src, dst = root / "src", root / "dst"
        make_photo(src / "trip" / "beach.jpg", "2022:08:01 09:30:00", "iPhone 13")
        make_photo(src / "trip" / "sunset.jpg", "2022:08:01 19:45:00", "iPhone 13")
        make_photo(src / "misc" / "cat.png")
        (src / "readme.txt").write_text("nope")

        # Pre-seed known devices so the naming modal only appears for new ones.
        devices_file = root / "devices.json"
        devices_file.write_text('{"TestMake iPhone 13": "Test Phone"}', encoding="utf-8")

        app = PhotoArchApp()
        app.devices_path = devices_file  # never touch the real ~/.config file
        async with app.run_test(size=(140, 45)) as pilot:
            # simulate folder selection directly (modal browsing is covered by unit smoke)
            app._source = src
            app._dest = dst

            # --- dry run ---
            await pilot.click("#btn-dry")
            await pilot.pause()
            await asyncio.sleep(1.5)  # let worker threads finish
            await pilot.pause()
            stats = app._stat_values
            assert stats.get("media") == "3", stats
            assert stats.get("non_media") == "1", stats
            assert not dst.exists() or not any(dst.rglob("*")), "dry run wrote files!"
            # switch to the Results tab so the hidden RichLog is laid out
            tabs = app.query_one("#tabs")
            tabs.active = "tab-results"
            await pilot.pause()
            log = app.query_one("#results-log")
            assert log.lines, "no results logged"
            print("✅ e2e dry run OK (no files written)")

            # --- real archive ---
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            copied = dst / "2022" / "08"  # default format: year_month
            assert (copied / "beach.jpg").exists(), list(dst.rglob("*"))
            assert (copied / "sunset.jpg").exists()
            # cat.png has no EXIF -> falls back to mtime (current year/month)
            assert app._stat_values.get("copied") == "3", app._stat_values
            # source untouched
            assert (src / "trip" / "beach.jpg").exists()
            assert (src / "readme.txt").exists()
            print("✅ e2e archive OK (3 files, EXIF date folders)")

            # --- second archive triggers conflict modal; choose skip ---
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.0)
            await pilot.pause()
            from photoarch.app import ConflictScreen

            assert app.screen.__class__ is ConflictScreen, app.screen
            # choose "skip" then apply
            screen = app.screen
            screen.query_one("#act-skip").value = True
            await pilot.click("#conflict-apply")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            assert app._stat_values.get("conflicts") == "3", app._stat_values
            assert app._stat_values.get("conflicts_skipped") == "3", app._stat_values
            assert not (copied / "beach_1.jpg").exists(), "skip should not add files"
            print("✅ e2e conflict modal OK (skip honored)")

            # --- new device -> mandatory naming modal ---
            make_photo(src / "trip" / "pixel.jpg", "2023:05:06 10:00:00", "Pixel 9")
            app.query_one("#fmt-select", Select).value = "device_year_month"
            await pilot.pause()
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()

            assert app.screen.__class__ is DeviceNamingScreen, app.screen
            screen = app.screen
            assert screen.devices_found == ["TestMake Pixel 9"], screen.devices_found
            screen.query_one("#dev-input-0", Input).value = "My Pixel"
            await pilot.click("#dev-save")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()

            # pixel.jpg lands in the friendly-name folder; known device reused
            friendly = dst / "My Pixel" / "2023" / "05"
            assert (friendly / "pixel.jpg").exists(), list(dst.rglob("*"))
            assert (dst / "Test Phone" / "2022" / "08" / "beach.jpg").exists()
            # naming was mandatory -> JSON now knows the new device
            import json

            saved = json.loads(devices_file.read_text(encoding="utf-8"))
            assert saved["TestMake Pixel 9"] == "My Pixel", saved
            assert saved["TestMake iPhone 13"] == "Test Phone", saved
            print("✅ e2e naming modal OK (friendly folder + JSON saved)")

            # --- second run: no naming modal (device now known), conflict modal ---
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            from photoarch.app import ConflictScreen

            assert app.screen.__class__ is ConflictScreen, app.screen
            app.screen.query_one("#act-skip").value = True
            await pilot.click("#conflict-apply")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            print("✅ e2e device remembered OK (no modal on second run)")

    print("\n🎉 End-to-end tests passed")


if __name__ == "__main__":
    asyncio.run(main())
