# SPDX-License-Identifier: GPL-3.0-or-later
"""Display-only explanations; eligibility remains owned by safety.py."""

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
    reminder = "Check the full ID before choosing."
    if start == end:
        unit = "character" if len(serial) == 1 else "characters"
        return 0, 0, f"Serial has {len(serial)} {unit}; other serials are longer. {reminder}"
    position = (f"character {start + 1}" if end == start + 1
                else f"characters {start + 1} to {end}")
    return start, end, f"Compare serial {position}: {serial[start:end]}. {reminder}"
