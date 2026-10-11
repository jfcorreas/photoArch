"""Read capture metadata (EXIF) from media files. Source is only ever read."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

# EXIF tag ids (avoids depending on Pillow's ExifTags enum layout)
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME_DIGITIZED = 36868
TAG_DATETIME = 306
TAG_MAKE = 271
TAG_MODEL = 272

_EPOCH = datetime(1970, 1, 1)


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


def _device_name(make: object, model: object) -> Optional[str]:
    make_s = str(make).strip() if make else ""
    model_s = str(model).strip() if model else ""
    if model_s and make_s:
        if model_s.lower().startswith(make_s.lower()):
            return model_s
        return f"{make_s} {model_s}"
    return model_s or make_s or None


def read_capture_info(path: Path) -> tuple[datetime, str]:
    """Return (capture date, device name).

    Falls back to file modification time and "Unknown device" when the file
    has no usable EXIF (e.g. videos, screenshots, edited images).
    """
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

    if when is None:
        try:
            when = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            when = _EPOCH

    return when, device or "Unknown device"
