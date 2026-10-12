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


def test_devices_json() -> None:
    from photoarch import devices

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "cfg" / "devices.json"
        assert devices.load(p) == {}, "missing file -> empty mapping"
        assert devices.save({"A": "Alpha"}, p)
        assert devices.load(p) == {"A": "Alpha"}
        p.write_text("{not valid json", encoding="utf-8")
        assert devices.load(p) == {}, "corrupt file -> empty mapping"
        p.write_text('["a", "list"]', encoding="utf-8")
        assert devices.load(p) == {}, "non-dict JSON -> empty mapping"
        print("✅ devices json OK")


def test_device_mapping() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src, dst = root / "src", root / "dst"
        make_photo(src / "a.jpg", "2021:03:14 10:00:00", "Pixel 7")
        make_photo(src / "b.jpg")  # no EXIF -> "Unknown device"

        # no mapping -> raw device in folder, new device reported
        plan = archiver.scan(src, dst, "device_year_month", {})
        assert plan.unknown_devices == ["TestMake Pixel 7"], plan.unknown_devices
        assert any(
            str(i.dest_dir).startswith("TestMake Pixel 7/") for i in plan.items
        ), [i.dest_dir for i in plan.items]

        # known mapping -> friendly name used, no unknowns
        plan2 = archiver.scan(
            src, dst, "device_year_month", {"TestMake Pixel 7": "My Pixel"}
        )
        assert plan2.unknown_devices == []
        assert any(str(i.dest_dir).startswith("My Pixel/") for i in plan2.items)

        # apply_device_names rebuilds dest_dir AND the conflict list
        plan3 = archiver.scan(src, dst, "device_year_month", {})
        applied = archiver.apply_device_names(
            plan3, {"TestMake Pixel 7": "My Pixel"}, "device_year_month", dst
        )
        assert applied.unknown_devices == []
        item = next(i for i in applied.items if i.src.name == "a.jpg")
        assert str(item.dest_dir).startswith("My Pixel/"), item.dest_dir
        assert not applied.conflicts
        # a file already at the friendly destination must appear as a conflict
        friendly_file = dst / item.dest_dir / "a.jpg"
        friendly_file.parent.mkdir(parents=True, exist_ok=True)
        friendly_file.write_bytes(b"x")
        applied2 = archiver.apply_device_names(
            plan3, {"TestMake Pixel 7": "My Pixel"}, "device_year_month", dst
        )
        conf = [c for c in applied2.conflicts if c.item.src.name == "a.jpg"]
        assert conf and conf[0].dest_exists, applied2.conflicts

        # friendly name is sanitized at path-build time (typed as-is in JSON)
        plan4 = archiver.scan(
            src, dst, "device_year_month", {"TestMake Pixel 7": "A/B:C"}
        )
        a_item = next(i for i in plan4.items if i.src.name == "a.jpg")
        # device stays ONE path part ("A_B_C"), no injected separators
        assert a_item.dest_dir.parts[0] == "A_B_C", a_item.dest_dir
        assert len(a_item.dest_dir.parts) == 3, a_item.dest_dir
        print("✅ device mapping OK")


def main() -> None:
    test_organizer()
    test_scan_and_copy()
    test_dry_run()
    test_devices_json()
    test_device_mapping()
    asyncio.run(test_directory_navigation())
    asyncio.run(test_tui())
    print("\n🎉 All tests passed")


if __name__ == "__main__":
    main()
