# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed rules. If we cannot prove a wipe is safe, we do not start it."""

from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from beamo_wipe.models import ConfirmSpec, Disk, DiscoveryResult, WipeRequest

LIVE_MARKERS = (
    "/run/live",
    "/lib/live/mount",
    "/run/initramfs/live",
)

# Whole-disk nodes only. Partitions (sda1, nvme0n1p1) are never wipe targets.
WHOLE_DISK_RE = re.compile(
    r"^/dev/(?:"
    r"sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|dasd[a-z]+|"
    r"nvme\d+n\d+|mmcblk\d+|nbd\d+|sr\d+"
    r")$"
)

FORBIDDEN_LOG_ROOTS = (
    "/mnt/target",
    "/target",
    "/media/target",
)

DEFAULT_LOG_DIR = Path("/tmp/beamo-wipe")


class SafetyError(Exception):
    """Abort. Do not wipe."""


def is_preview_env(env: Optional[dict] = None) -> bool:
    if env is None:
        env = os.environ
    return env.get("BEAMO_WIPE_DRY_RUN") == "1" or env.get("BEAMO_WIPE_DEMO") == "1"


def is_live_environment(
    *,
    env: Optional[dict] = None,
    cmdline: str = "",
    paths_exist: Optional[Sequence[str]] = None,
) -> bool:
    """True only for a real live session (kernel cmdline or live mount markers).

    Preview flags and BEAMO_WIPE_LIVE=1 alone are not enough. The live USB
    always has boot=live on the kernel command line.
    """
    del env
    if "boot=live" in cmdline or "boot=casper" in cmdline:
        return True
    markers = paths_exist
    if markers is None:
        markers = [p for p in LIVE_MARKERS if os.path.exists(p)]
    return bool(markers)


def running_on_live_usb(env: Optional[dict] = None) -> bool:
    """Live USB kiosk: real live markers/cmdline, and not a preview session."""
    if env is None:
        env = os.environ
    if is_preview_env(env):
        return False
    from beamo_wipe.discover import read_cmdline

    return is_live_environment(env=env, cmdline=read_cmdline())


def require_live_or_dry_run(
    env: Optional[dict] = None, cmdline: Optional[str] = None
) -> None:
    if env is None:
        env = os.environ
    if is_preview_env(env):
        return
    if cmdline is None:
        from beamo_wipe.discover import read_cmdline

        cmdline = read_cmdline()
    if is_live_environment(env=env, cmdline=cmdline):
        return
    raise SafetyError(
        "Beamo Wipe only erases disks from the bootable USB environment."
    )


def require_real_live_for_nwipe(env: Optional[dict] = None) -> None:
    """nwipe may run only on the live USB, never in preview/dry-run."""
    if env is None:
        env = os.environ
    if is_preview_env(env):
        raise SafetyError("Refusing to exec nwipe in preview or dry-run.")
    require_live_or_dry_run(env=env)


def selectable_disks(discovery: DiscoveryResult) -> Tuple[Disk, ...]:
    if not discovery.boot_identified or discovery.error:
        return tuple()
    return tuple(d for d in discovery.selectable if not d.is_boot and d.size_bytes > 0)


def boot_device_in_selectable(discovery: DiscoveryResult) -> bool:
    boot = discovery.boot
    if boot is None:
        return False
    boot_real = os.path.realpath(boot.path)
    return any(
        os.path.realpath(d.path) == boot_real and not d.is_boot
        for d in discovery.selectable
    )


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
                return _nonzero_token(
                    token,
                    "Type the last four characters of the serial shown above.",
                    disk,
                )
        if serial:
            same_serial = [
                d
                for d in same
                if (d.serial or "").strip().casefold() == serial.casefold()
            ]
            if len(same_serial) == 1:
                return _nonzero_token(
                    serial,
                    "Type the serial number shown above.",
                    disk,
                )
        token = (disk.name or "").strip() or disk.path
        return _nonzero_token(
            token,
            f"Type the device name shown above ({token}).",
            disk,
        )
    token = (disk.size_gb_label or "").strip()
    return _nonzero_token(
        token,
        f"Type the size number shown above ({token or disk.name}).",
        disk,
    )


def _nonzero_token(token: str, prompt: str, disk: Disk) -> ConfirmSpec:
    text = (token or "").strip()
    if not text:
        text = (disk.name or "").strip() or (disk.path or "").strip()
    if not text:
        raise SafetyError("Cannot build a confirm token for this disk.")
    return ConfirmSpec(token=text, prompt=prompt)


def token_matches(typed: str, spec: ConfirmSpec) -> bool:
    got = (typed or "").strip()
    want = (spec.token or "").strip()
    if not got or not want:
        return False
    return got.casefold() == want.casefold()


def assert_boot_excluded(discovery: DiscoveryResult) -> None:
    if not discovery.boot_identified or discovery.boot is None:
        raise SafetyError(
            "Cannot tell which disk is this USB. Unplug extra USB drives and reboot."
        )
    if boot_device_in_selectable(discovery):
        raise SafetyError("Boot USB appeared as a selectable disk. Refusing to continue.")
    selectable_paths = {os.path.realpath(s.path) for s in discovery.selectable}
    if any(d.is_boot and os.path.realpath(d.path) in selectable_paths for d in discovery.disks):
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


def normalize_whole_disk(path: str) -> str:
    """Return a canonical whole-disk /dev path, or raise."""
    if not path or not path.startswith("/dev/"):
        raise SafetyError("Target must be a /dev/ path.")
    if any(ch in path for ch in " \t\n\r\0"):
        raise SafetyError("Device path contains whitespace.")
    if ".." in path.split("/"):
        raise SafetyError("Device path must not contain '..'.")
    real = os.path.realpath(path)
    if not real.startswith("/dev/"):
        raise SafetyError("Device path must resolve under /dev.")
    if not WHOLE_DISK_RE.match(real):
        raise SafetyError("Device path is not a whole-disk /dev node.")
    return real


def disk_identity(disk: Disk) -> Tuple[str, str, int, str]:
    return (
        os.path.realpath(disk.path),
        (disk.serial or "").strip(),
        disk.size_bytes,
        (disk.model or "").strip(),
    )


def assert_disk_identity(disk: Disk, discovery: DiscoveryResult) -> None:
    """Selected disk must still be the same device (path + serial + size + model)."""
    want = os.path.realpath(disk.path)
    listed = [
        d
        for d in selectable_disks(discovery)
        if os.path.realpath(d.path) == want
    ]
    if len(listed) != 1:
        raise SafetyError("Selected disk is not in the safe list.")
    fresh = listed[0]
    if fresh.is_boot:
        raise SafetyError("Selected disk is the boot device.")
    if disk_identity(fresh) != disk_identity(disk):
        raise SafetyError("Disk identity changed. Refusing to erase.")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def assert_log_not_on_target(
    log_path: str, target: str, *, log_dir: Optional[Path] = None
) -> None:
    if not log_path:
        raise SafetyError("Log path is missing.")
    raw = Path(log_path).expanduser()
    try:
        st = os.lstat(raw)
    except FileNotFoundError:
        st = None
    except OSError as exc:
        raise SafetyError("Cannot stat log path.") from exc
    if st is not None:
        if stat.S_ISLNK(st.st_mode):
            raise SafetyError("Refusing to write logs through a symlink.")
        if stat.S_ISBLK(st.st_mode) or stat.S_ISCHR(st.st_mode) or stat.S_ISDIR(st.st_mode):
            raise SafetyError("Refusing to write logs onto a special file.")
    try:
        log = raw.resolve()
    except OSError as exc:
        raise SafetyError("Cannot resolve log path.") from exc
    text = str(log)
    if text == "/dev" or text.startswith("/dev/"):
        raise SafetyError("Refusing to write logs onto a block device.")
    if any(text == root or text.startswith(root + "/") for root in FORBIDDEN_LOG_ROOTS):
        raise SafetyError("Refusing to write logs onto the target disk.")
    if target:
        target_real = os.path.realpath(target)
        if text == target_real or (target_real != "/" and text.startswith(target_real + "/")):
            raise SafetyError("Refusing to write logs onto the target disk.")
    root = (log_dir or default_log_dir()).resolve()
    if log == root or not _is_under(log, root):
        raise SafetyError("Log file must live under the Beamo Wipe log directory.")
    if log.exists():
        try:
            st = os.lstat(log)
        except OSError as exc:
            raise SafetyError("Cannot stat log file.") from exc
        if stat.S_ISLNK(st.st_mode) or stat.S_ISBLK(st.st_mode) or stat.S_ISCHR(st.st_mode):
            raise SafetyError("Refusing to write logs onto a special file.")


def default_log_dir() -> Path:
    path = DEFAULT_LOG_DIR
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise SafetyError("Cannot create log directory.") from exc
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise SafetyError("Cannot stat log directory.") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise SafetyError("Refusing unsafe log directory.")
    if st.st_uid == os.getuid():
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    resolved = path.resolve()
    tmp = Path("/tmp").resolve()
    try:
        resolved.relative_to(tmp)
    except ValueError as exc:
        raise SafetyError("Log directory must live under /tmp.") from exc
    return path


def logfile_for(target: str, log_dir: Optional[Path] = None) -> str:
    directory = log_dir or default_log_dir()
    safe_name = os.path.basename(target).replace("/", "_")
    if not safe_name or safe_name in {".", ".."}:
        raise SafetyError("Cannot build a log name for this device.")
    path = directory / f"nwipe-{safe_name}-{os.getpid()}-{time.time_ns()}.log"
    assert_log_not_on_target(str(path), target, log_dir=directory)
    return str(path)


def truncate_log_file(log_path: str, target: str) -> None:
    """Create/truncate a regular log file. Never follows symlinks or opens devices."""
    assert_log_not_on_target(log_path, target)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    try:
        fd = os.open(log_path, flags, 0o600)
    except OSError as exc:
        raise SafetyError(f"Cannot create log file: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SafetyError("Refusing to write logs to a non-regular file.")
    finally:
        os.close(fd)


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
    if disk.size_bytes <= 0:
        raise SafetyError("Refusing to erase a zero-size disk.")
    assert_disk_identity(disk, discovery)
    spec = confirm_spec(disk, selectable_disks(discovery))
    if not token_matches(typed_token, spec):
        raise SafetyError("Confirm token does not match.")
    if not countdown_complete:
        raise SafetyError("Erase delay has not finished.")
    boot = discovery.boot
    if boot is None:
        raise SafetyError("Boot device missing.")
    device = normalize_whole_disk(disk.path)
    boot_path = normalize_whole_disk(boot.path)
    assert_not_boot(device, boot_path)
    log = logfile_for(device)
    return WipeRequest(
        device=device,
        method=method,
        boot_device=boot_path,
        logfile=log,
    )


def same_size_conflict(selectable: Iterable[Disk]) -> bool:
    labels = [d.size_gb_label for d in selectable]
    return len(labels) != len(set(labels))
