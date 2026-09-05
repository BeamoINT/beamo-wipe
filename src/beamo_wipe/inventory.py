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
    identity = (
        f"{disk.display_name} | {disk.size_phrase} | {disk.path} | "
        f"Serial: {disk.serial or 'unavailable'}"
    )
    return ExcludedDevice(identity, tuple(reasons))


def full_text(devices: tuple[ExcludedDevice, ...]) -> str:
    return INTRO + "\n\n" + "\n\n".join(d.explanation for d in devices)
