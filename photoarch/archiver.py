"""Planning and execution of the archive operation.

The source tree is only ever opened for reading; all writes go to the
destination path.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import metadata
from .organizer import MEDIA_EXTS, build_relative_dir


@dataclass
class PlanItem:
    src: Path
    dest_dir: Path  # relative to the destination root
    size: int
    when: datetime
    device: str
    final_name: Optional[str] = None  # set by apply_resolution on rename

    @property
    def name(self) -> str:
        return self.final_name or self.src.name


@dataclass
class Conflict:
    item: PlanItem
    dest_exists: bool  # True: file already on disk; False: duplicate inside the batch
    resolved_dest: Optional[Path] = None


UNKNOWN_DEVICE = "Unknown device"  # metadata.py fallback; never prompted/stored


@dataclass
class ScanResult:
    items: list[PlanItem] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    total_size: int = 0
    folders_to_create: int = 0
    skipped: int = 0  # non-media files
    errors: list[str] = field(default_factory=list)
    unknown_devices: list[str] = field(default_factory=list)  # not yet in the mapping


def _plan_dests(result: ScanResult, dest: Path) -> None:
    """Recompute conflicts and folder count from each item's dest_dir (in place).

    Any change to dest_dir (e.g. friendly device names) invalidates the
    previous conflict list, so this is shared by scan() and
    apply_device_names().
    """
    seen_dests: dict[str, PlanItem] = {}  # full dest path -> item, for in-batch duplicates
    dirs_planned: set[str] = set()
    result.conflicts = []
    result.folders_to_create = 0

    for item in result.items:
        full_dest = dest / item.dest_dir / item.name
        key = str(full_dest)
        if key in seen_dests:
            result.conflicts.append(Conflict(item=item, dest_exists=False))
        elif full_dest.exists():
            result.conflicts.append(Conflict(item=item, dest_exists=True))

        dir_key = str(item.dest_dir)
        if dir_key not in dirs_planned:
            dirs_planned.add(dir_key)
            result.folders_to_create += 1

        seen_dests[key] = item


def scan(
    source: Path, dest: Path, fmt: str, device_map: Optional[dict[str, str]] = None
) -> ScanResult:
    """Walk the source (read-only) and compute the archive plan.

    device_map: raw device name -> friendly name (from devices.py). Devices
    not present in the mapping are collected in result.unknown_devices
    (except the "Unknown device" fallback).
    """
    result = ScanResult()
    mapping = device_map or {}

    for root, dirs, files in os.walk(source):
        # Do not descend into hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in sorted(files):
            if name.startswith("."):
                result.skipped += 1
                continue
            src = Path(root) / name
            if src.suffix.lower() not in MEDIA_EXTS:
                result.skipped += 1
                continue
            try:
                size = src.stat().st_size
            except OSError as exc:
                result.errors.append(f"{src}: {exc}")
                continue

            when, device = metadata.read_capture_info(src)
            dest_dir = build_relative_dir(fmt, when, mapping.get(device, device))
            item = PlanItem(src=src, dest_dir=dest_dir, size=size, when=when, device=device)
            result.items.append(item)
            result.total_size += size

            if (
                device != UNKNOWN_DEVICE
                and device not in mapping
                and device not in result.unknown_devices
            ):
                result.unknown_devices.append(device)

    _plan_dests(result, dest)
    return result


def apply_device_names(
    result: ScanResult, device_map: dict[str, str], fmt: str, dest: Path
) -> ScanResult:
    """Rebuild the plan using friendly device names.

    Recomputes every item's dest_dir (template needs fmt) and rebuilds the
    conflict list and folder count, since they depend on dest_dir.
    Returns a new ScanResult; unknown_devices is cleared.
    """
    out = ScanResult(
        total_size=result.total_size,
        skipped=result.skipped,
        errors=list(result.errors),
    )
    for item in result.items:
        friendly = device_map.get(item.device, item.device)
        out.items.append(
            PlanItem(
                src=item.src,
                dest_dir=build_relative_dir(fmt, item.when, friendly),
                size=item.size,
                when=item.when,
                device=item.device,
                final_name=item.final_name,
            )
        )
    _plan_dests(out, dest)
    return out


def apply_resolution(result: ScanResult, action: str, dest_root: Path) -> ScanResult:
    """Apply the user's conflict decision.

    action: "rename" (keep both, add _1, _2...), "overwrite", "skip".
    Returns a new ScanResult with conflicts resolved (conflicts list emptied,
    skipped files removed from items).
    """
    if action not in {"rename", "overwrite", "skip"}:
        raise ValueError(f"unknown action: {action}")

    out = ScanResult(
        items=[],
        conflicts=[],
        total_size=result.total_size,
        folders_to_create=0,
        skipped=result.skipped,
        errors=list(result.errors),
    )

    conflicting = {(id(c.item.src), str(c.item.src)) for c in result.conflicts}
    used_dests: set[str] = set()
    dirs_planned: set[str] = set()

    for item in result.items:
        is_conflict = (id(item.src), str(item.src)) in conflicting
        dest_dir = item.dest_dir
        base_name = item.src.name

        if is_conflict and action == "skip":
            out.skipped += 1
            continue

        if is_conflict and action == "rename":
            stem = item.src.stem
            suffix = item.src.suffix
            n = 1
            while True:
                candidate = dest_dir / f"{stem}_{n}{suffix}"
                key = str(dest_root / candidate)
                if key not in used_dests and not (dest_root / candidate).exists():
                    base_name = f"{stem}_{n}{suffix}"
                    break
                n += 1

        new_item = PlanItem(
            src=item.src,
            dest_dir=dest_dir,
            size=item.size,
            when=item.when,
            device=item.device,
            final_name=base_name if base_name != item.src.name else None,
        )

        key = str(dest_root / dest_dir / base_name)
        used_dests.add(key)
        dir_key = str(dest_dir)
        if dir_key not in dirs_planned:
            dirs_planned.add(dir_key)
            out.folders_to_create += 1
        out.items.append(new_item)

    return out


@dataclass
class CopyReport:
    copied: int = 0
    folders_created: int = 0
    skipped: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)
    bytes_copied: int = 0
    dry_run: bool = False


def execute(
    result: ScanResult,
    dest_root: Path,
    dry_run: bool,
    on_progress: Optional[Callable[[str, str], None]] = None,
) -> CopyReport:
    """Copy files according to the (resolved) plan.

    on_progress(message, kind) is called for each file; kind is one of
    "copied", "would", "error", "folder".
    """
    report = CopyReport(dry_run=dry_run)
    made_dirs: set[Path] = set()

    def emit(msg: str, kind: str) -> None:
        if on_progress:
            on_progress(msg, kind)

    for item in result.items:
        final_name = item.name
        target_file = dest_root / item.dest_dir / final_name
        target_dir = target_file.parent

        try:
            if target_dir not in made_dirs and not target_dir.exists():
                if dry_run:
                    emit(f"📁 would create folder  {target_dir}", "folder")
                else:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    emit(f"📁 created folder  {target_dir}", "folder")
                made_dirs.add(target_dir)

            if dry_run:
                report.copied += 1
                report.bytes_copied += item.size
                emit(f"📄 would copy  {item.src}  →  {target_file}", "would")
            else:
                shutil.copy2(item.src, target_file)  # preserves metadata
                report.copied += 1
                report.bytes_copied += item.size
                emit(f"✅ copied  {item.src.name}  →  {target_file}", "copied")
        except OSError as exc:
            report.errors.append((item.src, str(exc)))
            emit(f"❌ error  {item.src}: {exc}", "error")

    report.folders_created = len(made_dirs)
    return report
