"""Headless smoke tests for photoArch core logic and TUI."""

from __future__ import annotations

import asyncio
import struct
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


def make_video(
    path: Path, make: str | None = None, model: str | None = None, style: str = "ilst"
) -> None:
    """Craft a minimal ISO-BMFF (mp4/mov) file with device metadata.

    style="ilst": ilst 4CC entries (©mak/©mod + data atoms)
    style="udta": QuickTime user-data strings under udta (GoPro style)
    style="mdta": ilst entries via the meta/keys registry (iPhone style)
    """

    def atom(typ: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + typ + payload

    def data(text: str) -> bytes:
        return atom(b"data", struct.pack(">II", 1, 0) + text.encode("utf-8"))

    ftyp = atom(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")

    if style == "ilst":
        ilst = b""
        if make:
            ilst += atom(b"\xa9mak", data(make))
        if model:
            ilst += atom(b"\xa9mod", data(model))
        meta = atom(b"meta", b"\x00\x00\x00\x00" + atom(b"ilst", ilst))
        body = atom(b"moov", atom(b"udta", meta))
    elif style == "udta":
        def lang_str(text: str) -> bytes:  # 16-bit language code + text
            return struct.pack(">H", 0x55C4) + text.encode("utf-8")

        udta_body = b""
        if make:
            udta_body += atom(b"\xa9mak", lang_str(make))
        if model:
            udta_body += atom(b"\xa9mod", lang_str(model))
        body = atom(b"moov", atom(b"udta", udta_body))
    else:  # "mdta"
        entries: list[tuple[bytes, str]] = []
        if make:
            entries.append((b"com.apple.quicktime.make", make))
        if model:
            entries.append((b"com.apple.quicktime.model", model))
        keys_payload = struct.pack(">II", 0, len(entries))
        ilst = b""
        for index, (key, value) in enumerate(entries, start=1):
            keys_payload += struct.pack(">I", 8 + len(key)) + b"mdta" + key
            ilst += atom(struct.pack(">I", index), data(value))
        meta = atom(
            b"meta", b"\x00\x00\x00\x00" + atom(b"keys", keys_payload) + atom(b"ilst", ilst)
        )
        body = atom(b"moov", atom(b"udta", meta))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ftyp + body)


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
        # media statistics: by kind and by extension
        assert plan.images == 2, plan.images
        assert plan.videos == 1, plan.videos
        assert plan.by_ext == {".jpg": 2, ".mp4": 1}, plan.by_ext

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
    with tempfile.TemporaryDirectory() as tmp:
        app = PhotoArchApp()
        app.settings_path = Path(tmp) / "settings.json"  # never touch the real ~/.config file
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


def test_settings_json() -> None:
    from photoarch import settings

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "cfg" / "settings.json"
        # missing file -> defaults
        assert settings.load(p) == settings.DEFAULTS, settings.load(p)
        # round trip
        assert settings.save(
            {
                "source": "/src",
                "dest": "/dst",
                "cold_dest": "/cold",
                "format": "device_year_month",
                "conflict": "skip",
            },
            p,
        )
        assert settings.load(p) == {
            "source": "/src",
            "dest": "/dst",
            "cold_dest": "/cold",
            "format": "device_year_month",
            "conflict": "skip",
        }
        # invalid format/conflict values fall back to defaults, paths kept
        p.write_text(
            '{"source": "/s", "dest": "/d", "format": "nope", "conflict": "maybe"}',
            encoding="utf-8",
        )
        assert settings.load(p) == {
            "source": "/s",
            "dest": "/d",
            "cold_dest": "",
            "format": "year_month",
            "conflict": "ask",
        }
        # empty paths -> defaults (nothing restored)
        p.write_text('{"source": "", "dest": "", "format": "year_month_day", "conflict": "rename"}', encoding="utf-8")
        loaded = settings.load(p)
        assert loaded["source"] == "" and loaded["dest"] == ""
        # corrupt / non-dict JSON -> defaults
        p.write_text("{not valid json", encoding="utf-8")
        assert settings.load(p) == settings.DEFAULTS
        p.write_text('["a", "list"]', encoding="utf-8")
        assert settings.load(p) == settings.DEFAULTS
        # save sanitizes invalid values too
        assert settings.save({"format": "nope", "conflict": "maybe"}, p)
        assert settings.load(p) == settings.DEFAULTS
        print("✅ settings json OK")


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


def test_video_device() -> None:
    from photoarch import metadata

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"

        # (1) ilst 4CC entries: ©mak / ©mod
        gopro = src / "gopro.mp4"
        make_video(gopro, make="GoPro", model="HERO11 Black", style="ilst")
        assert metadata.read_capture_info(gopro)[1] == "GoPro HERO11 Black"

        # (2) QuickTime udta strings (GoPro/Sony style)
        dji = src / "dji.mov"
        make_video(dji, make="DJI", model="Mavic 3", style="udta")
        assert metadata.read_capture_info(dji)[1] == "DJI Mavic 3"

        # (3) mdta keys registry (iPhone style), model only
        phone = src / "phone.mov"
        make_video(phone, model="iPhone 15", style="mdta")
        assert metadata.read_capture_info(phone)[1] == "iPhone 15"

        # malformed files must never raise; videos fall back to the "Videos"
        # folder label (images would fall back to "Unknown device")
        junk = src / "junk.mp4"
        junk.write_bytes(b"\x00" * 64)
        assert metadata.read_capture_info(junk)[1] == "Videos"
        cut = src / "cut.mp4"
        cut.write_bytes(struct.pack(">I", 4096) + b"moov")  # claims 4KB, has 4
        assert metadata.read_capture_info(cut)[1] == "Videos"
        empty = src / "none.mp4"
        empty.write_bytes(b"")
        assert metadata.read_capture_info(empty)[1] == "Videos"

        # scan: video devices join the friendly-name folder layout
        plan = archiver.scan(src, root / "dst", "device_year_month")
        by_name = {i.src.name: i for i in plan.items}
        assert str(by_name["gopro.mp4"].dest_dir).startswith("GoPro HERO11 Black/")
        assert str(by_name["dji.mov"].dest_dir).startswith("DJI Mavic 3/")
        assert str(by_name["phone.mov"].dest_dir).startswith("iPhone 15/")
        # metadata-less videos go to a "Videos" folder and are never prompted
        assert str(by_name["junk.mp4"].dest_dir).startswith("Videos/")
        assert str(by_name["none.mp4"].dest_dir).startswith("Videos/")
        # order = sorted file names: cut, dji, gopro, none, phone
        assert plan.unknown_devices == [
            "DJI Mavic 3",
            "GoPro HERO11 Black",
            "iPhone 15",
        ], plan.unknown_devices
        assert plan.videos == 6 and plan.images == 0, (plan.videos, plan.images)
        print("✅ video device OK")


async def test_devices_panel() -> None:
    """Devices tab: rename and remove known devices (writes only devices.json)."""
    import json

    from textual.widgets import DataTable, Input, TabbedContent

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "devices.json"
        cfg.write_text(
            '{"GoPro HERO11": "My GoPro", "TestMake iPhone 13": "Test Phone"}',
            encoding="utf-8",
        )
        app = PhotoArchApp()
        app.devices_path = cfg  # never touch the real ~/.config file
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one("#tabs", TabbedContent).active = "tab-devices"
            await pilot.pause()
            table = app.query_one("#devices-table", DataTable)
            inp = app.query_one("#dev-manage-input", Input)

            def rows() -> list[tuple[str, ...]]:
                return [tuple(table.get_row_at(i)) for i in range(table.row_count)]

            # sorted by raw name
            assert [r[0] for r in rows()] == ["GoPro HERO11", "TestMake iPhone 13"], rows()
            # row highlight prefills the input with the current friendly name
            table.move_cursor(row=1)
            await pilot.pause()
            assert inp.value == "Test Phone", inp.value
            table.move_cursor(row=0)
            await pilot.pause()
            assert inp.value == "My GoPro", inp.value

            # --- rename ---
            inp.value = "Action Cam"
            await pilot.click("#dev-save-name")
            await pilot.pause(0.25)  # > Button.active_effect_duration (0.2s debounce)
            saved = json.loads(cfg.read_text(encoding="utf-8"))
            assert saved == {
                "GoPro HERO11": "Action Cam",
                "TestMake iPhone 13": "Test Phone",
            }, saved
            assert rows()[0] == ("GoPro HERO11", "Action Cam"), rows()

            # --- empty input keeps the raw name (same rule as the naming modal) ---
            table.move_cursor(row=1)
            await pilot.pause()
            inp.value = ""
            await pilot.click("#dev-save-name")
            await pilot.pause(0.25)
            saved = json.loads(cfg.read_text(encoding="utf-8"))
            assert saved["TestMake iPhone 13"] == "TestMake iPhone 13", saved

            # --- remove ---
            table.move_cursor(row=0)
            await pilot.pause()
            await pilot.click("#dev-remove")
            await pilot.pause(0.25)
            saved = json.loads(cfg.read_text(encoding="utf-8"))
            assert saved == {"TestMake iPhone 13": "TestMake iPhone 13"}, saved
            assert [r[0] for r in rows()] == ["TestMake iPhone 13"], rows()

            # --- remove the last one -> placeholder row, actions become no-ops ---
            table.move_cursor(row=0)
            await pilot.pause()
            await pilot.click("#dev-remove")
            await pilot.pause(0.25)
            assert json.loads(cfg.read_text(encoding="utf-8")) == {}
            assert rows()[0][0] == "(no known devices yet)", rows()
            await pilot.click("#dev-save-name")  # no device selected -> notify only
            await pilot.pause(0.25)
            assert json.loads(cfg.read_text(encoding="utf-8")) == {}
    print("✅ devices panel OK (rename + remove)")


async def test_settings_restore() -> None:
    """Last-used folders/format/conflict are prefilled and saved on run start."""
    import json

    from textual.widgets import RadioButton, Select

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src, dst, cold = root / "src", root / "dst", root / "cold"
        src.mkdir()
        dst.mkdir()
        cfg = root / "settings.json"
        cfg.write_text(
            json.dumps(
                {
                    "source": str(src),
                    "dest": str(dst),
                    "cold_dest": str(cold),
                    "format": "year_month_day",
                    "conflict": "overwrite",
                }
            ),
            encoding="utf-8",
        )

        app = PhotoArchApp()
        app.settings_path = cfg  # never touch the real ~/.config file
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            # all values are prefilled from the file
            assert app._source == src, app._source
            assert app._dest == dst, app._dest
            assert app._cold == cold, app._cold
            assert str(cold) in str(app.query_one("#pick-cold").label)
            # clear button only visible while a cold folder is set (compact sidebar)
            assert app.query_one("#clear-cold").display is True
            assert str(app.query_one("#fmt-select", Select).value) == "year_month_day"
            assert app.query_one("#cf-overwrite", RadioButton).value is True

            # clear-cold drops it (persisted on next run start)
            await pilot.click("#clear-cold")
            await pilot.pause(0.25)
            assert app._cold is None
            assert app.query_one("#clear-cold").display is False

            # changing widgets does NOT save yet (save happens on run start)
            app.query_one("#fmt-select", Select).value = "device_year_month"
            app.query_one("#cf-skip", RadioButton).value = True
            await pilot.pause()
            assert json.loads(cfg.read_text(encoding="utf-8"))["format"] == "year_month_day"

            # a run start persists the current values
            await pilot.press("d")
            await pilot.pause()
            await asyncio.sleep(1.0)  # let the scan worker finish
            saved = json.loads(cfg.read_text(encoding="utf-8"))
            assert saved == {
                "source": str(src),
                "dest": str(dst),
                "cold_dest": "",
                "format": "device_year_month",
                "conflict": "skip",
            }, saved
    print("✅ settings restore OK (prefill + save on run start)")


async def test_settings_missing_folder() -> None:
    """A saved folder that no longer exists is restored as-is; the run errors out."""
    import json

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "settings.json"
        gone = Path(tmp) / "vanished"
        cfg.write_text(
            json.dumps(
                {"source": str(gone), "dest": str(gone / "out"), "format": "year_month", "conflict": "ask"}
            ),
            encoding="utf-8",
        )
        app = PhotoArchApp()
        app.settings_path = cfg
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app._source == gone, app._source  # restored even though missing
            await pilot.press("d")
            await pilot.pause()
            # validation fails before the save: file untouched
            assert json.loads(cfg.read_text(encoding="utf-8"))["source"] == str(gone)
    print("✅ settings missing folder OK (restored, run validates)")


def test_device_sanitize() -> None:
    """EXIF ASCII fields can be NUL-padded (WA-forwarded jpegs) -> no NULs in names."""
    from photoarch import metadata

    # control chars (incl. NUL padding) are dropped, everything else kept
    assert metadata._device_name("Xiaomi\x00\x00", "22101316G\x00") == "Xiaomi 22101316G"
    assert metadata._device_name("Xiaomi\x00\x00 22101316G", None) == "Xiaomi 22101316G"
    assert metadata._device_name("GoPro\t", "HERO11\x00") == "GoPro HERO11"
    # model already containing the make (NUL-padded) -> model alone, sanitized
    assert metadata._device_name("iPhone\x00", "iPhone 15\x00") == "iPhone 15"
    assert metadata._device_name("\x00", "\x00") is None  # only padding -> no device

    # end-to-end: a real image whose Make/Model carry NUL padding
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "padded.jpg"
        img = Image.new("RGB", (4, 4), color=(1, 2, 3))
        exif = img.getexif()
        exif[36867] = "2026:10:05 10:56:22"
        exif[271] = b"Xiaomi\x00\x00\x00"
        exif[272] = b"22101316G\x00\x00"
        img.save(p, exif=exif.tobytes())
        _when, device = metadata.read_capture_info(p)
        assert device == "Xiaomi 22101316G", repr(device)
        # and the sanitized name is safe as a path part (no NUL -> mkdir works)
        assert "\x00" not in str(build_relative_dir("device_year_month", _when, device))
        print("✅ device sanitize OK")


def test_whatsapp_files() -> None:
    """WA-named files: date from the filename, device 'WhatsApp', no metadata read."""
    from datetime import datetime as dt

    from photoarch import metadata

    # generic pattern: any prefix, case-insensitive, at the end of the stem
    assert metadata._WA_NAME_RE.search("IMG-20260925-WA0000")
    assert metadata._WA_NAME_RE.search("VID-20261011-WA0000")
    assert metadata._WA_NAME_RE.search("GIF-20260101-WA0001")
    assert metadata._WA_NAME_RE.search("img-20260925-wa0000")  # lowercase
    assert not metadata._WA_NAME_RE.search("IMG_20260925_170640")  # camera name
    assert not metadata._WA_NAME_RE.search("IMG-20260925-WA0000-copy")
    assert metadata._whatsapp_date(Path("IMG-20260925-WA0000.jpg")) == dt(2026, 9, 25)
    assert metadata._whatsapp_date(Path("IMG-20261340-WA0000.jpg")) is None  # bad date
    assert metadata._whatsapp_date(Path("IMG_20260925_170640.jpg")) is None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # WA image WITH full EXIF -> filename wins, metadata never consulted
        wa_img = root / "IMG-20261005-WA0004.jpg"
        make_photo(wa_img, "2020:01:02 03:04:05", "Pixel 7")
        when, device = metadata.read_capture_info(wa_img)
        assert (when, device) == (dt(2026, 10, 5), "WhatsApp"), (when, device)

        # WA video WITH device atoms -> still skipped, label wins
        wa_vid = root / "VID-20260813-WA0002.mp4"
        make_video(wa_vid, make="GoPro", model="HERO11")
        when, device = metadata.read_capture_info(wa_vid)
        assert (when, device) == (dt(2026, 8, 13), "WhatsApp"), (when, device)

        # garbage date in the name -> mtime fallback, still WhatsApp
        bad = root / "IMG-20261340-WA0000.jpg"
        make_photo(bad)
        when, device = metadata.read_capture_info(bad)
        assert device == "WhatsApp" and when is not None
        assert abs((datetime.now() - when).total_seconds()) < 3600  # ~mtime

        # scan: WA files land in WhatsApp/<YYYY>/<MM>, never prompted
        src = root / "src"
        make_photo(src / "IMG-20260925-WA0000.jpg")
        make_video(src / "VID-20260813-WA0002.mp4")
        make_photo(src / "normal.jpg", "2021:03:14 10:00:00", "Pixel 7")
        plan = archiver.scan(src, root / "dst", "device_year_month", {})
        by_name = {i.src.name: i for i in plan.items}
        assert str(by_name["IMG-20260925-WA0000.jpg"].dest_dir).startswith("WhatsApp/2026/09")
        assert str(by_name["VID-20260813-WA0002.mp4"].dest_dir).startswith("WhatsApp/2026/08")
        assert "WhatsApp" not in plan.unknown_devices, plan.unknown_devices
        assert plan.unknown_devices == ["TestMake Pixel 7"], plan.unknown_devices
        # manual devices.json override is still honored (like the other labels)
        plan2 = archiver.scan(src, root / "dst", "device_year_month", {"WhatsApp": "WA 2026"})
        by_name2 = {i.src.name: i for i in plan2.items}
        assert str(by_name2["IMG-20260925-WA0000.jpg"].dest_dir).startswith("WA 2026/2026/09")
        print("✅ whatsapp files OK")


def main() -> None:
    test_organizer()
    test_scan_and_copy()
    test_dry_run()
    test_devices_json()
    test_settings_json()
    test_device_mapping()
    test_device_sanitize()
    test_whatsapp_files()
    test_video_device()
    asyncio.run(test_directory_navigation())
    asyncio.run(test_tui())
    asyncio.run(test_devices_panel())
    asyncio.run(test_settings_restore())
    asyncio.run(test_settings_missing_folder())
    print("\n🎉 All tests passed")


if __name__ == "__main__":
    main()
