"""End-to-end TUI test: dry run, archive, and conflict modal via the pilot."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import make_photo, make_video  # tests/ = sys.path[0] when run as a script
from photoarch.app import DeviceNamingScreen, PhotoArchApp
from textual.widgets import DataTable, Input, RadioButton, Select, TabbedContent


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src, dst = root / "src", root / "dst"
        make_photo(src / "trip" / "beach.jpg", "2022:08:01 09:30:00", "iPhone 13")
        make_photo(src / "trip" / "sunset.jpg", "2022:08:01 19:45:00", "iPhone 13")
        make_photo(src / "misc" / "cat.png")
        make_video(src / "trip" / "drone.mp4", make="GoPro", model="HERO11")
        make_video(src / "misc" / "clip.mp4")  # no device metadata -> "Videos"
        (src / "readme.txt").write_text("nope")

        # Pre-seed known devices so the naming modal only appears for new ones.
        devices_file = root / "devices.json"
        devices_file.write_text(
            '{"TestMake iPhone 13": "Test Phone", "GoPro HERO11": "My GoPro"}',
            encoding="utf-8",
        )
        settings_file = root / "settings.json"

        app = PhotoArchApp()
        app.devices_path = devices_file  # never touch the real ~/.config file
        app.settings_path = settings_file
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
            assert stats.get("media") == "5", stats
            assert stats.get("images") == "3", stats
            assert stats.get("videos") == "2", stats
            assert stats.get("non_media") == "1", stats
            assert app._ext_counts == {".jpg": 2, ".png": 1, ".mp4": 2}, app._ext_counts
            # image formats under Images, video formats under Videos, count desc
            table = app.query_one("#stats-table")
            labels = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
            i_idx = labels.index("📸 Images")
            img_rows = labels[i_idx + 1 : i_idx + 3]
            assert any(".jpg" in r for r in img_rows), labels
            assert any(".png" in r for r in img_rows), labels
            assert ".jpg" in img_rows[0], labels  # highest count first
            assert labels[i_idx + 3] == "🎬 Videos", labels
            v_idx = i_idx + 3
            assert ".mp4" in labels[v_idx + 1], labels
            assert labels[v_idx + 2] == "⏭️ Non-media skipped", labels
            assert not dst.exists() or not any(dst.rglob("*")), "dry run wrote files!"
            # switch to the Results tab so the hidden RichLog is laid out
            tabs = app.query_one("#tabs")
            tabs.active = "tab-results"
            await pilot.pause()
            log = app.query_one("#results-log")
            assert log.lines, "no results logged"
            # fused panel: stats table and activity log share #stats-panel,
            # and both must get real height (a collapsed pane broke the log
            # silently — writes are deferred and rows invisible)
            panel = app.query_one("#stats-panel")
            assert app.query_one("#stats-table").parent == panel
            assert log.parent == panel
            assert panel.size.height > 0 and log.size.height > 1, (panel.size, log.size)
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
            # drone.mp4 date stays mtime (only device is parsed from the container)
            assert app._stat_values.get("copied") == "5", app._stat_values
            assert list(dst.rglob("drone.mp4")), list(dst.rglob("*"))
            # source untouched
            assert (src / "trip" / "beach.jpg").exists()
            assert (src / "readme.txt").exists()
            print("✅ e2e archive OK (5 files, EXIF date folders)")

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
            assert app._stat_values.get("conflicts") == "5", app._stat_values
            assert app._stat_values.get("conflicts_skipped") == "5", app._stat_values
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
            # video device (pre-seeded friendly name) used for its folder
            assert list((dst / "My GoPro").rglob("drone.mp4")), list(dst.rglob("*"))
            # video without device metadata goes to a "Videos" folder
            assert list((dst / "Videos").rglob("clip.mp4")), list(dst.rglob("*"))
            # naming was mandatory -> JSON now knows the new device
            import json

            saved = json.loads(devices_file.read_text(encoding="utf-8"))
            assert saved["TestMake Pixel 9"] == "My Pixel", saved
            assert saved["TestMake iPhone 13"] == "Test Phone", saved
            assert saved["GoPro HERO11"] == "My GoPro", saved
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

            # --- devices panel: rename applies from the NEXT run ---
            app.query_one("#tabs", TabbedContent).active = "tab-devices"
            await pilot.pause()
            table = app.query_one("#devices-table", DataTable)
            idx = next(
                i
                for i in range(table.row_count)
                if table.get_row_at(i)[0] == "TestMake Pixel 9"
            )
            table.move_cursor(row=idx)
            await pilot.pause()
            app.query_one("#dev-manage-input", Input).value = "Pixel Renamed"
            await pilot.click("#dev-save-name")
            await pilot.pause()
            saved = json.loads(devices_file.read_text(encoding="utf-8"))
            assert saved["TestMake Pixel 9"] == "Pixel Renamed", saved

            # next run uses the new friendly name; only pixel.jpg is new
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            assert app.screen.__class__ is ConflictScreen, app.screen  # 5 old files
            app.screen.query_one("#act-skip").value = True
            await pilot.click("#conflict-apply")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            assert (
                dst / "Pixel Renamed" / "2023" / "05" / "pixel.jpg"
            ).exists(), list(dst.rglob("*"))
            assert app._stat_values.get("copied") == "1", app._stat_values
            print("✅ e2e devices panel OK (rename picked up by next run)")

        # --- settings: saved on run start, restored by the next app instance ---
        import json

        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        assert saved == {
            "source": str(src),
            "dest": str(dst),
            "cold_dest": "",
            "format": "device_year_month",
            "conflict": "ask",
        }, saved

        app2 = PhotoArchApp()
        app2.devices_path = devices_file
        app2.settings_path = settings_file
        async with app2.run_test(size=(140, 45)) as pilot2:
            await pilot2.pause()
            assert app2._source == src, app2._source
            assert app2._dest == dst, app2._dest
            assert str(app2.query_one("#fmt-select", Select).value) == "device_year_month"
            assert app2.query_one("#cf-ask", RadioButton).value is True
            # folder buttons show the restored paths
            assert str(src) in str(app2.query_one("#pick-source").label)
            assert str(dst) in str(app2.query_one("#pick-dest").label)
        print("✅ e2e settings OK (saved on run start, restored on next launch)")

    print("\n🎉 End-to-end tests passed")


async def test_cold_storage() -> None:
    """Cold storage: optional 2nd destination, same restrictions + per-dest conflicts."""
    import json

    from photoarch.app import ConflictScreen

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src, dst, cold = root / "src", root / "dst", root / "cold"
        make_photo(src / "a.jpg", "2022:08:01 09:30:00", "iPhone 13")
        make_photo(src / "b.jpg", "2022:08:01 19:45:00", "iPhone 13")
        make_photo(src / "c.jpg")  # no EXIF

        devices_file = root / "devices.json"
        # pre-seed the friendly name so no naming modal interrupts the flow
        devices_file.write_text('{"TestMake iPhone 13": "iPhone"}', encoding="utf-8")
        settings_file = root / "settings.json"

        app = PhotoArchApp()
        app.devices_path = devices_file
        app.settings_path = settings_file
        async with app.run_test(size=(140, 45)) as pilot:
            app._source = src
            app._dest = dst
            app._cold = cold
            app._update_clear_cold()  # picker callback does this; test sets _cold directly
            await pilot.pause()  # let the reflow (clear button appearing) settle before clicks
            app.query_one("#fmt-select", Select).value = "year_month"

            # --- real archive copies to BOTH destinations ---
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            for root_dir in (dst, cold):
                assert (root_dir / "2022" / "08" / "a.jpg").exists(), list(root_dir.rglob("*"))
                assert (root_dir / "2022" / "08" / "b.jpg").exists()
            # c.jpg -> mtime (current year/month)
            stats = app._stat_values
            assert stats.get("copied") == "3", stats  # primary count
            assert stats.get("cold_copies") == "3", stats
            # settings persisted cold_dest
            assert json.loads(settings_file.read_text())["cold_dest"] == str(cold)
            print("✅ e2e cold archive OK (files in both destinations)")

            # --- second run: conflict in BOTH destinations -> one dialog, skip everywhere ---
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.0)
            await pilot.pause()
            assert app.screen.__class__ is ConflictScreen, app.screen
            # a,b (2022/08) + c (current month) exist in dst AND cold = 6 conflicts
            app.screen.query_one("#act-skip").value = True
            await pilot.click("#conflict-apply")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            assert app._stat_values.get("conflicts_skipped") == "6", app._stat_values
            # skip -> no new files anywhere
            assert not (dst / "2022" / "08" / "a_1.jpg").exists()
            assert not (cold / "2022" / "08" / "a_1.jpg").exists()
            print("✅ e2e cold conflicts OK (skip applied to both destinations)")

            # --- rename: per-destination suffixes computed independently ---
            app.query_one("#cf-rename", RadioButton).value = True
            await pilot.pause()
            # d.jpg pre-exists ONLY in dst -> renamed there, plain name in cold
            (dst / "2022" / "08" / "d.jpg").write_bytes(b"placeholder")
            make_photo(src / "d.jpg", "2022:08:02 10:00:00", "iPhone 13")
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            # d conflicted in dst (pre-existing) -> d_1.jpg; cold had no d -> d.jpg
            assert (dst / "2022" / "08" / "d_1.jpg").exists(), list((dst / "2022" / "08").iterdir())
            assert (cold / "2022" / "08" / "d.jpg").exists(), list((cold / "2022" / "08").iterdir())
            print("✅ e2e cold rename OK (per-destination suffix)")

            # --- clear cold storage -> next run archives primary only ---
            await pilot.click("#clear-cold")
            await pilot.pause(0.25)
            assert app._cold is None
            make_photo(src / "e.jpg", "2022:08:03 11:00:00", "iPhone 13")
            await pilot.click("#btn-archive")
            await pilot.pause()
            await asyncio.sleep(1.5)
            await pilot.pause()
            # policy=rename -> no dialog; e.jpg is new -> copied to primary only
            assert (dst / "2022" / "08" / "e.jpg").exists(), list((dst / "2022" / "08").iterdir())
            assert not (cold / "2022" / "08" / "e.jpg").exists()  # cold untouched
            # no cold target -> row is not populated (table renders "—")
            assert app._stat_values.get("cold_copies") is None, app._stat_values
            print("✅ e2e cold clear OK (primary only after clearing)")

        # --- restriction: cold storage inside source is rejected ---
        app3 = PhotoArchApp()
        app3.devices_path = devices_file
        app3.settings_path = settings_file
        async with app3.run_test(size=(140, 45)) as pilot3:
            app3._source = src
            app3._dest = dst
            app3._cold = src / "cold-nested"  # inside source!
            await pilot3.click("#btn-archive")
            await pilot3.pause(0.25)
            # validation aborts: nothing copied to the nested cold dir
            assert not (src / "cold-nested").exists() or not any((src / "cold-nested").rglob("*"))
            print("✅ e2e cold restriction OK (cold inside source rejected)")

    print("\n🎉 Cold-storage e2e tests passed")


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(test_cold_storage())
