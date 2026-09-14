# SPDX-License-Identifier: GPL-3.0-or-later
"""Display-only explanations; eligibility remains owned by safety.py."""

import os

from beamo_wipe.models import Disk, DiscoveryResult, ExcludedDevice


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


def other_devices(discovery: DiscoveryResult) -> tuple[ExcludedDevice, ...]:
    """Display-only exclusions, with confirmed boot media presented separately."""
    from beamo_wipe.safety import selectable_disks

    # Never display inventory when boot identity failed closed.
    if not discovery.boot_identified or discovery.error or discovery.boot is None:
        return ()
    boot_paths = {
        discovery.boot.path,
        os.path.realpath(discovery.boot.path),
    }
    if discovery.excluded:
        return tuple(
            device
            for device in discovery.excluded
            if not device.path or device.path not in boot_paths
        )
    eligible = {d.path for d in selectable_disks(discovery)}
    boot_paths = {discovery.boot.path, os.path.realpath(discovery.boot.path)}
    return tuple(
        excluded_device(d)
        for d in discovery.disks
        if d.path not in eligible and os.path.realpath(d.path) not in boot_paths
    )
