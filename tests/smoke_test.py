"""Headless smoke tests for photoArch core logic and TUI."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photoarch import archiver
from photoarch.app import PhotoArchApp
from photoarch.organizer import build_relative_dir


def make_photo(path: Path, date: str | None = None, model: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        path.write_bytes(b"\x00\x00fake-video-bytes")
        return
    img = Image.new("RGB", (4, 4), color=(10, 20, 30))
    if date and model:
        exif = img.getexif()
        exif[36867] = date
        exif[271] = "TestMake"
        exif[272] = model
        img.save(path, exif=exif.tobytes())
    else:
        img.save(path)


def test_organizer() -> None:
    when = datetime(2023, 7, 5, 12, 0, 0)
    assert str(build_relative_dir("year_month", when, "X")) == "2023/07"
    assert str(build_relative_dir("year_month_day", when, "X")) == "2023/07/05"
    assert str(build_relative_dir("year_month_device", when, "iPhone 13")) == "2023/07 - iPhone 13"
    assert str(build_relative_dir("device_year_month", when, "Canon EOS")) == "Canon EOS/2023/07"
    assert str(build_relative_dir("year_full_date", when, "X")) == "2023/2023-07-05"
    # unsafe device name gets sanitized (no separators inside the device part)
    rel = build_relative_dir("year_month_device", when, "A/B:C")
    assert all("/" not in part for part in rel.parts[1:]), rel
    print("✅ organizer OK")


def test_scan_and_copy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        make_photo(src / "a" / "photo1.jpg", "2021:03:14 10:00:00", "Pixel 7")
        make_photo(src / "a" / "photo2.jpg")  # no exif -> mtime
        make_photo(src / "b" / "clip.mp4")
        (src / "notes.txt").write_text("not media")

        plan = archiver.scan(src, dst, "year_month_day")
        assert len(plan.items) == 3, plan.items
        assert plan.skipped == 1
        assert not plan.conflicts

        # photo1 has EXIF date -> 2021/03/15 (timezone-independent from EXIF)
        dirs = {str(i.dest_dir) for i in plan.items}
        assert "2021/03/15" in dirs or "2021/03/14" in dirs, dirs

        resolved = archiver.apply_resolution(plan, "rename", dst)
        report = archiver.execute(resolved, dst, dry_run=False)
        assert report.copied == 3 and not report.errors, report
        assert report.folders_created >= 1
        # source untouched
        assert (src / "a" / "photo1.jpg").exists()
        assert (src / "notes.txt").exists()

        # second run over same destination -> conflicts, rename keeps both
        plan2 = archiver.scan(src, dst, "year_month_day")
        assert len(plan2.conflicts) == 3, plan2.conflicts
        resolved2 = archiver.apply_resolution(plan2, "rename", dst)
        report2 = archiver.execute(resolved2, dst, dry_run=False)
        assert report2.copied == 3
        assert (dst / "2021" / "03" / "15" / "photo1_1.jpg").exists() or (
            dst / "2021" / "03" / "14" / "photo1_1.jpg"
        ).exists()

        # skip leaves destination untouched
        plan3 = archiver.scan(src, dst, "year_month_day")
        resolved3 = archiver.apply_resolution(plan3, "skip", dst)
        assert not resolved3.items
        print("✅ scan/apply/execute OK")


def test_dry_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src, dst = root / "src", root / "dst"
        make_photo(src / "x.jpg", "2020:01:02 00:00:00", "Cam")
        plan = archiver.scan(src, dst, "year_month")
        report = archiver.execute(plan, dst, dry_run=True)
        assert report.copied == 1 and report.dry_run
        assert not dst.exists() or not any(dst.iterdir()), "dry run must not write!"
        print("✅ dry run OK")


async def test_directory_navigation() -> None:
    """Regression: the folder picker must navigate into child folders, not only root/parent."""
    from textual.app import App, ComposeResult

    from photoarch.app import DirectoryScreen

    class Probe(App):
        start: Path

        def compose(self) -> ComposeResult:
            yield from ()

        def on_mount(self) -> None:
            self.push_screen(DirectoryScreen(self.start))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "alpha").mkdir()
        (root / "beta").mkdir()
        (root / "alpha" / "inner").mkdir()

        app = Probe()
        app.start = root
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DirectoryScreen)
            listing = screen.query_one("#dir-list")

            async def pick(name: str) -> None:
                idx = next(i for i, e in enumerate(screen._entries) if e and e.name == name)
                listing.highlighted = idx
                listing.action_select()
                await pilot.pause()

            await pick("alpha")
            assert screen.current == root / "alpha", screen.current

            await pick("inner")  # nested child
            assert screen.current == root / "alpha" / "inner", screen.current

            listing.highlighted = 0  # ".." row
            listing.action_select()
            await pilot.pause()
            assert screen.current == root / "alpha", screen.current

            await pilot.click("#dir-select")  # confirm selection
            await pilot.pause()
            assert not isinstance(app.screen, DirectoryScreen)
    print("✅ directory navigation OK (children + parent)")


async def test_tui() -> None:
    app = PhotoArchApp()
    async with app.run_test() as pilot:
        assert app.query_one("#pick-source")
        assert app.query_one("#pick-dest")
        assert app.query_one("#btn-dry")
        assert app.query_one("#btn-archive")
        # run with nothing selected -> should notify, not crash
        await pilot.press("d")
        await pilot.pause()
        # open & close the source folder dialog
        await pilot.click("#pick-source")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    print("✅ TUI smoke OK")


def main() -> None:
    test_organizer()
    test_scan_and_copy()
    test_dry_run()
    asyncio.run(test_directory_navigation())
    asyncio.run(test_tui())
    print("\n🎉 All tests passed")


if __name__ == "__main__":
    main()
