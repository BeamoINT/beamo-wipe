# SPDX-License-Identifier: GPL-3.0-or-later
"""Display-only explanations; eligibility remains owned by safety.py."""

import os
from dataclasses import replace
from typing import Iterable

from beamo_wipe.models import Disk, DiscoveryResult, ExcludedDevice


TITLE = "Other detected devices"
INTRO = "Information only. These devices cannot be selected for erasure."
NESTED_INTRO = "On this disk (cannot be erased separately):"
REASON_UNSUPPORTED = "unsupported device"
REASON_PROTECTED = "boot or system protected"
REASON_MOUNTED = "mounted or in use"
REASON_READ_ONLY = "read-only"
REASON_CAPACITY_UNKNOWN = "capacity could not be confirmed"
REASON_ZERO_CAPACITY = "zero capacity"
REASON_ELIGIBILITY = "eligibility could not be confirmed"
REASON_UNPROVEN_TRANSPORT = "local connection could not be confirmed"
# Nested cards already say they cannot be erased separately. Keep other
# reasons (mounted, protected) visible; drop the generic whole-disk label.
NESTED_SILENT_REASONS = frozenset({REASON_UNSUPPORTED})
EMPTY_STEPS = (
    "No eligible disk is available. Review the reasons below. Keep the Beamo USB "
    "connected. Shut down before checking drive connections. If a disk remains "
    "unavailable or its identity is uncertain, contact support. Do not bypass protection."
)

KIND_PART = "Partition"
KIND_CRYPT = "Encrypted volume"
KIND_MAPPED = "Mapped volume"
KIND_LOOP = "Loop device"
KIND_ROM = "Optical disc"
KIND_RAID = "RAID volume"
KIND_DISK = "Disk"
KIND_TECHNICAL = "Technical component"


def _build_kind_labels() -> dict[str, str]:
    return {
        "part": KIND_PART,
        "crypt": KIND_CRYPT,
        "lvm": KIND_MAPPED,
        "dm": KIND_MAPPED,
        "loop": KIND_LOOP,
        "rom": KIND_ROM,
        "md": KIND_RAID,
        "mpath": KIND_RAID,
        "disk": KIND_DISK,
    }


_KIND_LABELS = _build_kind_labels()


def _apply_language() -> None:
    global _KIND_LABELS, NESTED_SILENT_REASONS
    _KIND_LABELS = _build_kind_labels()
    NESTED_SILENT_REASONS = frozenset({REASON_UNSUPPORTED})


def kind_label_for_type(node_type: str) -> str:
    key = (node_type or "").lower().strip()
    if key in _KIND_LABELS:
        return _KIND_LABELS[key]
    if key.startswith("raid"):
        return KIND_RAID
    return KIND_TECHNICAL


def component_summary(disk: Disk, kind_label: str) -> str:
    """Plain nested label. Parent serial/model stay on the parent card."""
    from beamo_wipe.identity import UNKNOWN_MODEL

    heading = kind_label or KIND_TECHNICAL
    parts = [heading]
    parts.append(disk.size_phrase)
    label = (disk.label or "").strip()
    title = (disk.model or "").strip()
    extra = label
    if not extra and title and title != UNKNOWN_MODEL:
        extra = title
    if extra and extra not in parts:
        parts.append(extra)
    return " · ".join(parts)


def excluded_device(
    disk: Disk,
    *,
    unsupported: bool = False,
    capacity_unknown: bool = False,
    parent_path: str = "",
    node_type: str = "",
) -> ExcludedDevice:
    from beamo_wipe.safety import (
        SafetyError,
        has_any_mount,
        has_protected_mount,
        is_remote_disk,
        is_unproven_scsi_transport,
        normalize_whole_disk,
    )

    reasons = []
    if disk.is_boot or has_protected_mount(disk):
        reasons.append(REASON_PROTECTED)
    if has_any_mount(disk):
        reasons.append(REASON_MOUNTED)
    if disk.read_only:
        reasons.append(REASON_READ_ONLY)
    if disk.size_bytes <= 0:
        reasons.append(
            REASON_CAPACITY_UNKNOWN if capacity_unknown else REASON_ZERO_CAPACITY
        )
    try:
        normalize_whole_disk(disk.path)
    except SafetyError:
        unsupported = True
    if unsupported or is_remote_disk(disk):
        reasons.append(REASON_UNSUPPORTED)
    if is_unproven_scsi_transport(disk):
        reasons.append(REASON_UNPROVEN_TRANSPORT)
    if not reasons:
        reasons.append(REASON_ELIGIBILITY)
    from beamo_wipe.identity import present_disk

    view = present_disk(disk)
    identity = (
        f"{view.title} | {view.capacity} | {view.connection} | "
        f"{view.id_label}: {view.id_value}"
    )
    kind = kind_label_for_type(node_type) if node_type else (
        KIND_DISK if not parent_path else KIND_TECHNICAL
    )
    return ExcludedDevice(
        identity,
        tuple(reasons),
        path=disk.path,
        parent_path=parent_path,
        kind_label=kind,
        summary=component_summary(disk, kind),
    )


def nested_heading(device: ExcludedDevice) -> str:
    return device.summary or device.identity


def nested_reason_text(device: ExcludedDevice) -> str:
    shown = [reason for reason in device.reasons if reason not in NESTED_SILENT_REASONS]
    return "; ".join(shown)


def nested_under(
    parent_path: str, devices: Iterable[ExcludedDevice]
) -> tuple[ExcludedDevice, ...]:
    """Children whose known physical parent is parent_path. Display only."""
    if not parent_path:
        return ()
    aliases = {parent_path}
    try:
        aliases.add(os.path.realpath(parent_path))
    except OSError:
        pass
    return tuple(
        device
        for device in devices
        if device.parent_path and device.parent_path in aliases
    )


def card_nesting_text(children: Iterable[ExcludedDevice]) -> str:
    items = tuple(children)
    if not items:
        return ""
    lines = [NESTED_INTRO]
    for child in items:
        lines.append(nested_heading(child))
        extra = nested_reason_text(child)
        if extra:
            lines.append(extra)
    return "\n".join(lines)


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line if line else line for line in text.split("\n"))


def full_text(devices: tuple[ExcludedDevice, ...]) -> str:
    blocks = [INTRO]
    for device in devices:
        blocks.append(device.explanation)
        nested = card_nesting_text(device.children)
        if nested:
            blocks.append(_indent(nested))
    return "\n\n".join(blocks)


def _path_aliases(path: str) -> set[str]:
    aliases = {path}
    try:
        aliases.add(os.path.realpath(path))
    except OSError:
        pass
    return aliases


def _raw_other_devices(discovery: DiscoveryResult) -> tuple[ExcludedDevice, ...]:
    from beamo_wipe.safety import selectable_disks

    boot_paths = _path_aliases(discovery.boot.path)
    if discovery.excluded:
        return tuple(
            device
            for device in discovery.excluded
            if not device.path or device.path not in boot_paths
        )
    eligible = {d.path for d in selectable_disks(discovery)}
    return tuple(
        excluded_device(d)
        for d in discovery.disks
        if d.path not in eligible and os.path.realpath(d.path) not in boot_paths
    )


def _known_parent_paths(
    raw: tuple[ExcludedDevice, ...], discovery: DiscoveryResult
) -> set[str]:
    from beamo_wipe.safety import selectable_disks

    known: set[str] = set()
    for disk in selectable_disks(discovery):
        known.update(_path_aliases(disk.path))
    if discovery.boot is not None:
        known.update(_path_aliases(discovery.boot.path))
    for device in raw:
        if device.path and not device.parent_path:
            known.update(_path_aliases(device.path))
    return known


def _group_other_devices(
    raw: tuple[ExcludedDevice, ...], discovery: DiscoveryResult
) -> tuple[ExcludedDevice, ...]:
    known = _known_parent_paths(raw, discovery)
    roots = []
    for device in raw:
        if device.parent_path and device.parent_path in known:
            continue
        roots.append(device)
    grouped = []
    for device in roots:
        kids = nested_under(device.path, raw) if device.path else ()
        grouped.append(replace(device, children=kids) if kids else device)
    return tuple(grouped)


def other_devices(discovery: DiscoveryResult) -> tuple[ExcludedDevice, ...]:
    """Display-only exclusions, with confirmed boot media presented separately.

    Children of a known physical parent are omitted here and shown on that
    parent instead. Orphans with missing parentage stay visible.
    """
    # Never display inventory when boot identity failed closed.
    if not discovery.boot_identified or discovery.error or discovery.boot is None:
        return ()
    return _group_other_devices(_raw_other_devices(discovery), discovery)


def serial_comparison(disk: Disk, peers: tuple[Disk, ...]) -> tuple[int, int, str]:
    """Display-only span (Python offsets) and spoken, one-based explanation.

    Compare the existing warning's displayed-capacity group. Strip only a
    common prefix/suffix, so the remaining portion preserves every difference.
    Case-only differences cannot establish identity. Missing serials prevent a
    complete comparison; duplicate serials never receive a distinguishing span.
    """
    serial = (disk.serial or "").strip()
    others = [d for d in peers if d.path != disk.path
              and d.size_gb_label == disk.size_gb_label]
    values = [serial, *((d.serial or "").strip() for d in others)]
    if (disk.is_boot or not others or not all(values)
            or any(serial.casefold() == (other.serial or "").strip().casefold()
                   for other in peers if other.path != disk.path)):
        return 0, 0, ""
    start = 0
    shortest = min(map(len, values))
    while start < shortest and len({v[start].casefold() for v in values}) == 1:
        start += 1
    suffix = 0
    while (suffix < shortest - start
           and len({v[-suffix - 1].casefold() for v in values}) == 1):
        suffix += 1
    end = len(serial) - suffix
    reminder = REMINDER_CHECK_ID
    if start == end:
        unit = UNIT_CHAR if len(serial) == 1 else UNIT_CHARS
        return 0, 0, SERIAL_LONGER.format(count=len(serial), unit=unit, reminder=reminder)
    position = (POSITION_ONE.format(n=start + 1) if end == start + 1
                else POSITION_RANGE.format(a=start + 1, b=end))
    return start, end, COMPARE_SERIAL.format(position=position, span=serial[start:end], reminder=reminder)


REMINDER_CHECK_ID = "Check the full ID before choosing."
UNIT_CHAR = "character"
UNIT_CHARS = "characters"
SERIAL_LONGER = "Serial number has {count} {unit}; other serials are longer. {reminder}"
POSITION_ONE = "character {n}"
POSITION_RANGE = "characters {a} to {b}"
COMPARE_SERIAL = "Compare serial number {position}: {span}. {reminder}"
ENTRY_DISK = "Disk {number}"
ENTRY_MODEL = "Model: {value}"
ENTRY_CAPACITY = "Capacity: {value}"
ENTRY_SERIAL = "Serial number: {value}"
ENTRY_CONNECTION = "Connection: {value}"


COMPARE_TITLE = "Compare disks"
COMPARE_INTRO = (
    "Read only. Compare model, capacity, serial number and connection before choosing. "
    "Your selection stays unchanged. If identity is uncertain, do not guess."
)


def comparison_entries(
    disks: Iterable[Disk], *, peers: Iterable[Disk] | None = None
) -> tuple[str, ...]:
    """Accept only the caller's eligible snapshot; never discover or select."""
    from beamo_wipe.identity import present_disk, SERIAL_LABEL, SERIAL_NOT_REPORTED

    candidates = tuple(disks)
    identity_peers = tuple(peers) if peers is not None else candidates
    entries = []
    numbered = enumerate(sorted(candidates, key=lambda d: d.path), 1)
    # Keep equal-capacity candidates adjacent while retaining picker numbers.
    ordered = sorted(
        numbered, key=lambda item: (item[1].size_bytes, (item[1].model or "").casefold(), item[0])
    )
    for number, disk in ordered:
        view = present_disk(disk, identity_peers)
        lines = [
            ENTRY_DISK.format(number=number),
            ENTRY_MODEL.format(value=view.title),
            ENTRY_CAPACITY.format(value=view.capacity),
            ENTRY_SERIAL.format(value=(disk.serial or '').strip() or SERIAL_NOT_REPORTED),
            ENTRY_CONNECTION.format(value=view.connection),
        ]
        if view.id_label != SERIAL_LABEL:
            lines.append(f"{view.id_label}: {view.id_value}")
        lines.extend(view.notes)
        entries.append("\n".join(lines))
    return tuple(entries)


def comparison_text(disks: Iterable[Disk], *, peers: Iterable[Disk] | None = None) -> str:
    return COMPARE_INTRO + "\n\n" + "\n\n".join(comparison_entries(disks, peers=peers))

