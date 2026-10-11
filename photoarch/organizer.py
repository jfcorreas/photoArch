"""Media detection and destination folder layout."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

# Common image extensions
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".heic", ".heif", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng",
    ".orf", ".rw2", ".srw", ".raf",
}

# Common video extensions
VIDEO_EXTS = {
    ".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp", ".mts", ".m2ts", ".webm",
}

MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

# Destination folder format options: key -> (label, template)
FORMATS: dict[str, tuple[str, str]] = {
    "year_month": ("📅 YYYY / MM", "{year:04d}/{month:02d}"),
    "year_month_day": ("📅 YYYY / MM / DD", "{year:04d}/{month:02d}/{day:02d}"),
    "year_month_device": (
        "📅 YYYY / MM - 📷 Device",
        "{year:04d}/{month:02d} - {device}",
    ),
    "device_year_month": (
        "📷 Device / 📅 YYYY / MM",
        "{device}/{year:04d}/{month:02d}",
    ),
    "year_full_date": (
        "📅 YYYY / YYYY-MM-DD",
        "{year:04d}/{year:04d}-{month:02d}-{day:02d}",
    ),
}

_DEFAULT_FORMAT = "year_month"

_BAD_CHARS = set('/\\:*?"<>|')


def _clean_part(part: str) -> str:
    """Make a string safe to use as a single path component."""
    part = "".join("_" if c in _BAD_CHARS else c for c in part).strip(" .")
    return part or "Unknown"


def build_relative_dir(fmt_key: str, when: datetime, device: str) -> Path:
    """Build the relative destination directory for a media file."""
    try:
        _label, template = FORMATS[fmt_key]
    except KeyError:
        _label, template = FORMATS[_DEFAULT_FORMAT]
    raw = template.format(
        year=when.year,
        month=when.month,
        day=when.day,
        device=_clean_part(device),
    )
    return Path(*(_clean_part(p) for p in raw.split("/")))
