"""Read capture metadata (EXIF) from media files. Source is only ever read."""

from __future__ import annotations

import os
import re
import struct
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterator, Optional

from .organizer import VIDEO_EXTS  # no import cycle: organizer imports nothing from here

# EXIF tag ids (avoids depending on Pillow's ExifTags enum layout)
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME_DIGITIZED = 36868
TAG_DATETIME = 306
TAG_MAKE = 271
TAG_MODEL = 272

_EPOCH = datetime(1970, 1, 1)

# Folder labels used when metadata has no device (both never prompted/stored)
UNKNOWN_DEVICE = "Unknown device"  # images without EXIF
VIDEOS_DEVICE = "Videos"  # videos without device metadata (e.g. Xiaomi)
WHATSAPP_DEVICE = "WhatsApp"  # files named *-YYYYMMDD-WA#### (never prompted)

# WhatsApp renames media on save: IMG-20260925-WA0000.jpg, VID-20261011-WA0000.mp4…
# Generic: any prefix, 8-digit date, -WA + 4 digits at the end of the stem.
_WA_NAME_RE = re.compile(r"-(\d{8})-WA\d{4}$", re.IGNORECASE)


def _parse_dt(value: object) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _sanitize_exif_str(value: object) -> str:
    """Stringify an EXIF value, dropping control characters.

    Real-world EXIF ASCII fields are fixed-width and NUL-padded
    (e.g. WhatsApp-forwarded jpegs: "Xiaomi\\x00\\x00..."); ".strip()"
    alone does not remove \\x00, which would end up in folder names.
    """
    if not value:
        return ""
    return "".join(c for c in str(value) if c >= " ").strip()


def _device_name(make: object, model: object) -> Optional[str]:
    make_s = _sanitize_exif_str(make)
    model_s = _sanitize_exif_str(model)
    if model_s and make_s:
        if model_s.lower().startswith(make_s.lower()):
            return model_s
        return f"{make_s} {model_s}"
    return model_s or make_s or None


# ---- ISO-BMFF (mp4/mov/m4v/3gp) device atoms ------------------------------
# Pure stdlib, seeks by atom headers only (never reads the huge mdat payload).
# Three real-world conventions are handled:
#   1. ilst entries with 4CC types: ©mak / ©mod (atom types are EXACTLY 4 bytes)
#   2. QuickTime user-data strings directly under udta: ©mak / ©mod (GoPro style)
#   3. ilst entries referencing the meta/keys registry (mdta namespace),
#      where keys like com.apple.quicktime.make/model live (iPhone style)

# ilst/udta 4CC -> role
_VIDEO_DEVICE_ATOMS = {
    b"\xa9mak": "make",   # ©mak
    b"\xa9mod": "model",  # ©mod
}

# mdta keys registry names -> role
_MDTA_KEYS = {
    "com.apple.quicktime.make": "make",
    "com.apple.quicktime.model": "model",
}


def _iter_atoms(
    f: BinaryIO, start: int, end: int
) -> Iterator[tuple[str, int, int]]:
    """Yield (type, payload_start, payload_end) for atoms inside [start, end)."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            return
        size, atype = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:  # 64-bit largesize follows the header
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            header_size = 16
        elif size == 0:  # atom extends to the end of the region
            size = end - pos
        if size < header_size or pos + size > end:
            return  # malformed; stop walking this level
        yield atype.decode("latin-1"), pos + header_size, pos + size
        pos += size


def _find_child(f: BinaryIO, start: int, end: int, wanted: bytes) -> Optional[tuple[int, int]]:
    for atype, pstart, pend in _iter_atoms(f, start, end):
        if atype.encode("latin-1") == wanted:
            return pstart, pend
    return None


def _read_data_payload(f: BinaryIO, start: int, end: int) -> Optional[str]:
    """Read the text payload of an ilst entry's 'data' atom (8-byte prefix)."""
    for atype, pstart, pend in _iter_atoms(f, start, end):
        if atype == "data":
            f.seek(pstart + 8)  # skip type indicator + locale
            raw = f.read(max(0, pend - pstart - 8))
            try:
                return raw.decode("utf-8").strip() or None
            except UnicodeDecodeError:
                return None
    return None


def _read_udta_string(f: BinaryIO, start: int, end: int) -> Optional[str]:
    """QuickTime user-data text atom: 2-byte language code, then the text."""
    length = end - start
    if length < 3:
        return None
    f.seek(start + 2)
    try:
        text = f.read(length - 2).decode("utf-8").strip("\x00").strip()
    except UnicodeDecodeError:
        return None
    return text or None


def _read_keys_registry(f: BinaryIO, start: int, end: int) -> dict[int, str]:
    """Parse meta/keys: version/flags + count + [size, 'mdta', name] entries."""
    f.seek(start)
    hdr = f.read(8)
    if len(hdr) < 8:
        return {}
    count = struct.unpack(">I", hdr[4:8])[0]
    keys: dict[int, str] = {}
    pos = start + 8
    for i in range(1, min(count, 64) + 1):
        if pos + 8 > end:
            break
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            break
        size, namespace = struct.unpack(">I4s", head)
        if size < 8 or pos + size > end:
            break
        name = f.read(size - 8)
        if namespace == b"mdta":
            keys[i] = name.split(b"\x00")[0].decode("utf-8", "replace")
        pos += size
    return keys


def _ilst_role(atype: bytes, keys: dict[int, str]) -> Optional[str]:
    """Map an ilst entry type to make/model: either a 4CC or a keys index."""
    tag = _VIDEO_DEVICE_ATOMS.get(atype)
    if tag:
        return tag
    name = keys.get(int.from_bytes(atype, "big"))
    return _MDTA_KEYS.get(name) if name else None


def read_video_device(path: Path) -> Optional[str]:
    """Extract the device (make/model) from an ISO-BMFF video file.

    Supports the ©mak/©mod ilst and udta conventions plus Apple's mdta
    keys registry (com.apple.quicktime.make/model). Returns None for
    anything unreadable or without device data — never raises.
    """
    make: Optional[str] = None
    model: Optional[str] = None

    def note(role: str, value: Optional[str]) -> None:
        nonlocal make, model
        if not value:
            return
        if role == "make" and make is None:
            make = value
        elif role == "model" and model is None:
            model = value

    try:
        with path.open("rb") as f:
            file_end = f.seek(0, os.SEEK_END)
            moov = _find_child(f, 0, file_end, b"moov")
            if not moov:
                return None
            udta = _find_child(f, *moov, b"udta")
            if not udta:
                return None

            # (1)+(2): 4CC entries in ilst, or plain strings under udta
            for atype, pstart, pend in _iter_atoms(f, *udta):
                tag = _VIDEO_DEVICE_ATOMS.get(atype.encode("latin-1"))
                if tag:
                    note(tag, _read_udta_string(f, pstart, pend))

            # (3): ilst entries via the meta/keys registry (iPhone style)
            meta = _find_child(f, *udta, b"meta")
            if meta:
                # 'meta' carries 4 version/flags bytes before its child atoms
                cstart, cend = meta[0] + 4, meta[1]
                keys: dict[int, str] = {}
                keys_span = _find_child(f, cstart, cend, b"keys")
                if keys_span:
                    keys = _read_keys_registry(f, *keys_span)
                ilst = _find_child(f, cstart, cend, b"ilst")
                if ilst:
                    for atype, pstart, pend in _iter_atoms(f, *ilst):
                        role = _ilst_role(atype.encode("latin-1"), keys)
                        if role:
                            note(role, _read_data_payload(f, pstart, pend))
    except OSError:
        return None
    return _device_name(make, model)


def _wa_date(match: re.Match[str]) -> Optional[datetime]:
    """Capture date from a _WA_NAME_RE match (None when unparseable)."""
    try:
        return datetime.strptime(match.group(1), "%Y%m%d")
    except ValueError:
        return None


def _whatsapp_date(path: Path) -> Optional[datetime]:
    """Capture date embedded in a WhatsApp filename, or None.

    Matches "*-YYYYMMDD-WA####" anywhere in the stem (IMG-, VID-, GIF-…).
    An unparseable date (e.g. month 40) yields None -> caller falls back
    to mtime; the file is still treated as WhatsApp media.
    """
    match = _WA_NAME_RE.search(path.stem)
    return _wa_date(match) if match else None


def read_mtime(path: Path) -> datetime:
    """File modification time (epoch on OSError)."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return _EPOCH


def read_capture_info(path: Path) -> tuple[datetime, str]:
    """Return (capture date, device name).

    WhatsApp-named files (*-YYYYMMDD-WA####) skip metadata parsing entirely:
    their date comes from the filename (mtime fallback) and their device is
    the fixed "WhatsApp" label — no EXIF/atom read at all.
    Falls back to file modification time when the file has no usable date.
    Images are read via Pillow/EXIF; videos try a pure ISO-BMFF device parse
    (no ffprobe); their date stays mtime. Missing device -> "Unknown device"
    for images, "Videos" for videos (folder label, never prompted).
    """
    wa_match = _WA_NAME_RE.search(path.stem)
    if wa_match:
        # WA file: date from name (or mtime if the name date is garbage);
        # metadata is never read — WA strips it in ~85% of files anyway.
        return (_wa_date(wa_match) or read_mtime(path)), WHATSAPP_DEVICE

    when: Optional[datetime] = None
    device: Optional[str] = None

    try:
        from PIL import Image

        with Image.open(path) as im:
            exif = im.getexif()
            if exif:
                raw_dt = (
                    exif.get(TAG_DATETIME_ORIGINAL)
                    or exif.get(TAG_DATETIME_DIGITIZED)
                    or exif.get(TAG_DATETIME)
                )
                when = _parse_dt(raw_dt)
                device = _device_name(exif.get(TAG_MAKE), exif.get(TAG_MODEL))
    except Exception:
        # Not an image, unsupported codec, corrupt file, missing Pillow...
        pass

    if device is None and path.suffix.lower() in VIDEO_EXTS:
        device = read_video_device(path)

    if when is None:
        when = read_mtime(path)

    if device:
        return when, device
    # no device in metadata: videos get their own folder label
    return when, VIDEOS_DEVICE if path.suffix.lower() in VIDEO_EXTS else UNKNOWN_DEVICE
