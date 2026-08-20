# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed rules. If we cannot prove a wipe is safe, we do not start it."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from beamo_wipe.models import ConfirmSpec, Disk, DiscoveryResult, WipeRequest

LIVE_MARKERS = (
    "/run/live",
    "/lib/live/mount",
    "/run/initramfs/live",
)


class SafetyError(Exception):
    """Abort. Do not wipe."""


def is_live_environment(
    *,
    env: Optional[dict] = None,
    cmdline: str = "",
    paths_exist: Optional[Sequence[str]] = None,
) -> bool:
    if env is None:
        env = os.environ
    if env.get("BEAMO_WIPE_LIVE") == "1":
        return True
    if env.get("BEAMO_WIPE_DRY_RUN") == "1":
        return True
    if env.get("BEAMO_WIPE_DEMO") == "1":
        return True
    if "boot=live" in cmdline or "boot=casper" in cmdline:
        return True
    markers = paths_exist
    if markers is None:
        markers = [p for p in LIVE_MARKERS if os.path.exists(p)]
        return bool(markers)
    return bool(markers)


def require_live_or_dry_run(env: Optional[dict] = None, cmdline: str = "") -> None:
    if env is None:
        env = os.environ
    if env.get("BEAMO_WIPE_DRY_RUN") == "1" or env.get("BEAMO_WIPE_DEMO") == "1":
        return
    if is_live_environment(env=env, cmdline=cmdline):
        return
    raise SafetyError(
        "Beamo Wipe only erases disks from the bootable USB environment."
    )


def selectable_disks(discovery: DiscoveryResult) -> Tuple[Disk, ...]:
    if not discovery.boot_identified or discovery.error:
        return tuple()
    return tuple(d for d in discovery.selectable if not d.is_boot)


def boot_device_in_selectable(discovery: DiscoveryResult) -> bool:
    boot = discovery.boot
    if boot is None:
        return False
    return any(d.path == boot.path and not d.is_boot for d in discovery.selectable)


def confirm_spec(disk: Disk, selectable: Sequence[Disk]) -> ConfirmSpec:
    """
    Default token is the size label (e.g. 256).
    If two listed disks share that size, use last 4 of serial when that
    suffix is unique in the same-size set, else the full serial if unique,
    else the device name.
    """
    same = [d for d in selectable if d.size_gb_label == disk.size_gb_label]
    if len(same) > 1:
        serial = (disk.serial or "").strip()
        if len(serial) >= 4:
            token = serial[-4:]
            same_token = [
                d
                for d in same
                if (d.serial or "").strip()[-4:].casefold() == token.casefold()
            ]
            if len(same_token) == 1:
                return ConfirmSpec(
                    token=token,
                    prompt="Type the last four characters of the serial shown above.",
                )
        if serial:
            same_serial = [
                d
                for d in same
                if (d.serial or "").strip().casefold() == serial.casefold()
            ]
            if len(same_serial) == 1:
                return ConfirmSpec(
                    token=serial,
                    prompt="Type the serial number shown above.",
                )
        token = disk.name
        return ConfirmSpec(
            token=token,
            prompt=f"Type the device name shown above ({disk.name}).",
        )
    return ConfirmSpec(
        token=disk.size_gb_label,
        prompt=f"Type the size number shown above ({disk.size_gb_label}).",
    )


def token_matches(typed: str, spec: ConfirmSpec) -> bool:
    got = (typed or "").strip()
    want = spec.token.strip()
    return got.casefold() == want.casefold()


def assert_boot_excluded(discovery: DiscoveryResult) -> None:
    if not discovery.boot_identified or discovery.boot is None:
        raise SafetyError(
            "Cannot tell which disk is this USB. Unplug extra USB drives and reboot."
        )
    if boot_device_in_selectable(discovery):
        raise SafetyError("Boot USB appeared as a selectable disk. Refusing to continue.")
    if any(d.is_boot and d.path in {s.path for s in discovery.selectable} for d in discovery.disks):
        raise SafetyError("Boot USB appeared as a selectable disk. Refusing to continue.")


def assert_not_boot(device: str, boot_path: str) -> None:
    if not device or not boot_path:
        raise SafetyError("Missing device or boot path.")
    if os.path.realpath(device) == os.path.realpath(boot_path):
        raise SafetyError("Refusing to erase the Beamo boot device.")
    dev = os.path.realpath(device)
    boot = os.path.realpath(boot_path)
    if _is_partition_of(dev, boot) or _is_partition_of(boot, dev):
        raise SafetyError("Refusing to erase the Beamo boot device.")


def _is_partition_of(device: str, parent: str) -> bool:
    """True if `device` is a partition of `parent` (sda1 of sda, nvme0n1p1 of nvme0n1).

    Sibling NVMe namespaces (nvme0n1 vs nvme0n11) are not partitions.
    """
    if not device.startswith(parent) or len(device) <= len(parent):
        return False
    rest = device[len(parent) :]
    parent_name = os.path.basename(parent)
    if parent_name.startswith("nvme") or parent_name.startswith("mmcblk"):
        return len(rest) > 1 and rest[0] in "pP" and rest[1:].isdigit()
    return rest.isdigit()


def assert_log_not_on_target(log_path: str, target: str) -> None:
    log = Path(log_path).resolve()
    # Target is a block device; the log must live on tmpfs or the boot medium,
    # never as a file path that starts like /mnt/target.
    forbidden_roots = (
        "/mnt/target",
        "/target",
        "/media/target",
    )
    text = str(log)
    if any(text.startswith(root) for root in forbidden_roots):
        raise SafetyError("Refusing to write logs onto the target disk.")
    # If someone bind-mounted the target at /tmp, we cannot always see it.
    # Callers must pass a directory we created under /tmp/beamo-wipe.


def default_log_dir() -> Path:
    path = Path("/tmp/beamo-wipe")
    path.mkdir(parents=True, exist_ok=True)
    return path


def logfile_for(target: str, log_dir: Optional[Path] = None) -> str:
    directory = log_dir or default_log_dir()
    safe_name = os.path.basename(target).replace("/", "_")
    path = directory / f"nwipe-{safe_name}-{os.getpid()}-{time.time_ns()}.log"
    assert_log_not_on_target(str(path), target)
    return str(path)


def assert_ready_to_wipe(
    *,
    owner_ok: bool,
    disk: Optional[Disk],
    discovery: DiscoveryResult,
    typed_token: str,
    countdown_complete: bool,
    method,
) -> WipeRequest:
    require_live_or_dry_run()
    if not owner_ok:
        raise SafetyError("Owner checkbox is required.")
    assert_boot_excluded(discovery)
    if disk is None or disk.is_boot:
        raise SafetyError("No target disk selected.")
    if disk.path not in {d.path for d in selectable_disks(discovery)}:
        raise SafetyError("Selected disk is not in the safe list.")
    spec = confirm_spec(disk, selectable_disks(discovery))
    if not token_matches(typed_token, spec):
        raise SafetyError("Confirm token does not match.")
    if not countdown_complete:
        raise SafetyError("Erase delay has not finished.")
    boot = discovery.boot
    if boot is None:
        raise SafetyError("Boot device missing.")
    assert_not_boot(disk.path, boot.path)
    log = logfile_for(disk.path)
    return WipeRequest(
        device=disk.path,
        method=method,
        boot_device=boot.path,
        logfile=log,
    )


def same_size_conflict(selectable: Iterable[Disk]) -> bool:
    labels = [d.size_gb_label for d in selectable]
    return len(labels) != len(set(labels))
