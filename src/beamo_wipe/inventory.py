# SPDX-License-Identifier: GPL-3.0-or-later
"""Display-only explanations; eligibility remains owned by safety.py."""

from typing import Iterable

from beamo_wipe.models import Disk, ExcludedDevice


TITLE = "Other detected devices"
INTRO = "Information only. These devices cannot be selected for erasure."
EMPTY_STEPS = (
    "No eligible disk is available. Review the reasons below. Keep the Beamo USB "
    "connected. Shut down before checking drive connections. If a disk remains "
    "unavailable or its identity is uncertain, contact support. Do not bypass protection."
)


def excluded_device(
    disk: Disk, *, unsupported: bool = False, capacity_unknown: bool = False
) -> ExcludedDevice:
    from beamo_wipe.safety import (
        SafetyError,
        has_any_mount,
        has_protected_mount,
        is_remote_disk,
        normalize_whole_disk,
    )

    reasons = []
    if disk.is_boot or has_protected_mount(disk):
        reasons.append("boot or system protected")
    if has_any_mount(disk):
        reasons.append("mounted or in use")
    if disk.read_only:
        reasons.append("read-only")
    if disk.size_bytes <= 0:
        reasons.append(
            "capacity could not be confirmed" if capacity_unknown else "zero capacity"
        )
    try:
        normalize_whole_disk(disk.path)
    except SafetyError:
        unsupported = True
    if unsupported or is_remote_disk(disk):
        reasons.append("unsupported device")
    if not reasons:
        reasons.append("eligibility could not be confirmed")
    from beamo_wipe.identity import present_disk

    view = present_disk(disk)
    identity = (
        f"{view.title} | {view.capacity} | {view.connection} | "
        f"{view.id_label}: {view.id_value}"
    )
    return ExcludedDevice(identity, tuple(reasons), path=disk.path)


def full_text(devices: tuple[ExcludedDevice, ...]) -> str:
    return INTRO + "\n\n" + "\n\n".join(d.explanation for d in devices)


COMPARE_TITLE = "Compare disks"
COMPARE_INTRO = (
    "Read only. Compare model, capacity, serial and connection before choosing. "
    "Your selection stays unchanged. If identity is uncertain, do not guess."
)


def comparison_entries(
    disks: Iterable[Disk], *, peers: Iterable[Disk] | None = None
) -> tuple[str, ...]:
    """Accept only the caller's eligible snapshot; never discover or select."""
    from beamo_wipe.identity import present_disk, SERIAL_NOT_REPORTED

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
            f"Disk {number}",
            f"Model: {view.title}",
            f"Capacity: {view.capacity}",
            f"Serial: {(disk.serial or '').strip() or SERIAL_NOT_REPORTED}",
            f"Connection: {view.connection}",
        ]
        if view.id_label != "Serial":
            lines.append(f"{view.id_label}: {view.id_value}")
        lines.extend(view.notes)
        entries.append("\n".join(lines))
    return tuple(entries)


def comparison_text(disks: Iterable[Disk], *, peers: Iterable[Disk] | None = None) -> str:
    return COMPARE_INTRO + "\n\n" + "\n\n".join(comparison_entries(disks, peers=peers))
