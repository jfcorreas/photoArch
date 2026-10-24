"""Shared media-file builders for the test scripts (smoke + e2e).

Run the tests as scripts from the repo root (tests/ is then sys.path[0]),
so `from helpers import ...` resolves without making tests a package.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image


def make_photo(path: Path, date: str | None = None, model: str | None = None) -> None:
    """Create a small image (or junk bytes for non-image suffixes).

    date + model write EXIF (DateTimeOriginal 36867, Make 271, Model 272).
    """
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
