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

# Whole-disk nodes only. Partitions (sda1, nvme0n1p1) are never wipe targets.
# nbd is excluded: a network block device can point at remote storage.
WHOLE_DISK_RE = re.compile(
    r"^/dev/(?:"
    r"sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|dasd[a-z]+|"
    r"nvme\d+n\d+|mmcblk\d+|sr\d+"
    r")$"
)
OPTICAL_RE = re.compile(r"^/dev/sr\d+$")
# Confirm tokens are typed by a person. Reject path elements and control chars
# so a garbage serial cannot become `../sda` or a homoglyph of another disk.
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]+$")

# boot=live / boot=casper as a kernel cmdline *token*, not a substring.
LIVE_BOOT_RE = re.compile(r"(?:^|\s)boot=(?:live|casper)(?:\s|,|$)")

# Mountpoints that mean "this is the running system / live medium". A disk
# mounted here is never a wipe target, even if boot identification glitched.
PROTECTED_MOUNT_PREFIXES = (
    "/run/live",
    "/lib/live",
    "/run/initramfs",
    "/cdrom",
    "/mnt/live",
    "/usr",
    "/boot",
    "/lib",
    "/bin",
    "/sbin",
    "/etc",
    "/var",
    "/opt",
    "/home",
    "/root",
    "/snap",
    "/sys",
    "/proc",
    "/dev",
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


def is_protected_mountpoint(mountpoint: str) -> bool:
    """True if this mount is the running OS or the live medium."""
    mp = (mountpoint or "").strip()
    if not mp:
        return False
    if mp == "/":
        return True
    for prefix in PROTECTED_MOUNT_PREFIXES:
        if mp == prefix or mp.startswith(prefix + "/"):
            return True
    return False


def has_protected_mount(disk: Disk) -> bool:
    return any(is_protected_mountpoint(mp) for mp in disk.mountpoints)


def is_live_environment(
    *,
    env: Optional[dict] = None,
    cmdline: str = "",
    paths_exist: Optional[Sequence[str]] = None,
    live_medium_mounted: Optional[bool] = None,
    mountinfo_text: Optional[str] = None,
) -> bool:
    """True only on a real live session: cmdline token AND a live-medium mount.

    Preview flags, BEAMO_WIPE_LIVE=1, and a directory like /run/live are not
    enough. `mkdir /run/live` on a running desktop must never enable wipes.
    Adding `boot=live` to a desktop GRUB line is also not enough — the live
    medium must actually be mounted (mountinfo, not a mkdir'd folder).
    """
    del env
    if not LIVE_BOOT_RE.search(cmdline or ""):
        return False
    if live_medium_mounted is not None:
        return bool(live_medium_mounted)
    # Explicit paths_exist is the old "directory present" hook. Directories
    # are not mounts; treating them as live would re-open the mkdir bypass.
    if paths_exist is not None:
        return False
    from beamo_wipe.discover import live_medium_is_mounted

    return live_medium_is_mounted(text=mountinfo_text)


def running_on_live_usb(env: Optional[dict] = None) -> bool:
    """True on the real live USB even if a preview env var was injected.

    A fake Finished screen on the kiosk is a safety bug: operators will
    unplug a disk that was never erased. Live-medium detection wins.
    """
    if env is None:
        env = os.environ
    from beamo_wipe.discover import read_cmdline

    return is_live_environment(env=env, cmdline=read_cmdline())


def require_live_or_dry_run(
    env: Optional[dict] = None,
    cmdline: Optional[str] = None,
    live_medium_mounted: Optional[bool] = None,
) -> None:
    if env is None:
        env = os.environ
    if is_preview_env(env):
        return
    if cmdline is None:
        from beamo_wipe.discover import read_cmdline

        cmdline = read_cmdline()
    if is_live_environment(
        env=env, cmdline=cmdline, live_medium_mounted=live_medium_mounted
    ):
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


def is_wipeable_disk(disk: Disk) -> bool:
    """True if this node is a whole-disk wipe target (same gate as nwipe argv)."""
    if disk.is_boot or disk.size_bytes <= 0 or has_protected_mount(disk):
        return False
    try:
        normalize_whole_disk(disk.path)
    except SafetyError:
        return False
    return True


def selectable_disks(discovery: DiscoveryResult) -> Tuple[Disk, ...]:
    if not discovery.boot_identified or discovery.error:
        return tuple()
    return tuple(d for d in discovery.selectable if is_wipeable_disk(d))


def listed_disks(discovery: DiscoveryResult) -> Tuple[Disk, ...]:
    """Selectable targets plus every disk marked boot. Same set the pick list shows."""
    seen = set()
    out = []
    for disk in selectable_disks(discovery):
        key = os.path.realpath(disk.path)
        if key not in seen:
            seen.add(key)
            out.append(disk)
    for disk in discovery.disks:
        if not disk.is_boot:
            continue
        key = os.path.realpath(disk.path)
        if key not in seen:
            seen.add(key)
            out.append(disk)
    return tuple(out)


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
    suffix is unique in the same-size set, else the full serial if unique
    and not another disk's device name, else the device name.
    """
    same = [d for d in selectable if d.size_gb_label == disk.size_gb_label]
    if len(same) > 1:
        serial = (disk.serial or "").strip()
        peer_names = _peer_name_tokens(disk, same)
        if len(serial) >= 4:
            token = _safe_token(serial[-4:])
            same_token = [
                d
                for d in same
                if _safe_token((d.serial or "").strip()[-4:]).casefold() == token.casefold()
            ]
            if token and len(same_token) == 1 and token.casefold() not in peer_names:
                return _nonzero_token(
                    token,
                    "Type the last four characters of the serial shown above.",
                    disk,
                )
        serial_token = _safe_token(serial)
        if serial_token:
            same_serial = [
                d
                for d in same
                if _safe_token((d.serial or "").strip()).casefold() == serial_token.casefold()
            ]
            if len(same_serial) == 1 and serial_token.casefold() not in peer_names:
                return _nonzero_token(
                    serial_token,
                    "Type the serial number shown above.",
                    disk,
                )
        token = _safe_token((disk.name or "").strip()) or _safe_token(
            os.path.basename(disk.path or "")
        )
        return _nonzero_token(
            token,
            f"Type the device name shown above ({token or disk.name}).",
            disk,
        )
    token = _safe_token((disk.size_gb_label or "").strip())
    return _nonzero_token(
        token,
        f"Type the size number shown above ({token or disk.name}).",
        disk,
    )


def _peer_name_tokens(disk: Disk, same: Sequence[Disk]) -> set[str]:
    """Kernel names of the other same-size disks. A serial must not reuse one."""
    names = set()
    want = os.path.realpath(disk.path)
    for other in same:
        if os.path.realpath(other.path) == want:
            continue
        token = _safe_token((other.name or "").strip()) or _safe_token(
            os.path.basename(other.path or "")
        )
        if token:
            names.add(token.casefold())
    return names


def _safe_token(text: str) -> str:
    got = (text or "").strip()
    if not got or got in {".", ".."}:
        return ""
    if not SAFE_TOKEN_RE.fullmatch(got):
        return ""
    return got


def _nonzero_token(token: str, prompt: str, disk: Disk) -> ConfirmSpec:
    text = _safe_token(token)
    if not text:
        text = _safe_token((disk.name or "").strip())
    if not text:
        text = _safe_token(os.path.basename(disk.path or ""))
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
    # Same underlying block device under two names (by-id vs sdX, etc.).
    try:
        dst = os.lstat(dev)
        bst = os.lstat(boot)
    except OSError:
        return
    if (
        stat.S_ISBLK(dst.st_mode)
        and stat.S_ISBLK(bst.st_mode)
        and dst.st_rdev == bst.st_rdev
    ):
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


def normalize_whole_disk(path: str, *, allow_optical: bool = False) -> str:
    """Return a canonical whole-disk /dev path, or raise.

    Optical nodes (`/dev/srN`) may be the live ISO (boot/exclude) but are
    never a wipe target.
    """
    if not path or not path.startswith("/dev/"):
        raise SafetyError("Target must be a /dev/ path.")
    if any(ch in path for ch in " \t\n\r\0,;"):
        raise SafetyError("Device path contains whitespace.")
    if ".." in path.split("/"):
        raise SafetyError("Device path must not contain '..'.")
    real = os.path.realpath(path)
    if not real.startswith("/dev/"):
        raise SafetyError("Device path must resolve under /dev.")
    if not WHOLE_DISK_RE.match(real):
        raise SafetyError("Device path is not a whole-disk /dev node.")
    if OPTICAL_RE.match(real) and not allow_optical:
        raise SafetyError("Refusing to erase an optical drive.")
    return real


def disk_identity(disk: Disk) -> Tuple[str, str, int, str, str, str]:
    return (
        os.path.realpath(disk.path),
        (disk.serial or "").strip(),
        disk.size_bytes,
        (disk.model or "").strip(),
        (disk.wwn or "").strip(),
        (disk.vendor or "").strip(),
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
    if fresh.is_boot or has_protected_mount(fresh):
        raise SafetyError("Selected disk is the boot device.")
    if disk_identity(fresh) != disk_identity(disk):
        raise SafetyError("Disk identity changed. Refusing to erase.")


def assert_not_system_mounted(disk: Disk) -> None:
    if has_protected_mount(disk):
        raise SafetyError(
            "Refusing to erase a disk that is mounted as the live system."
        )


def assert_existing_is_block_device(path: str, *, required: bool = False) -> None:
    """If the path exists, it must be a block device. Missing paths are for tests.

    Production nwipe exec requires the node to exist (`required=True`) so a
    path cannot be created as a different device between confirm and exec.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        if required:
            raise SafetyError("Target device is missing.") from exc
        return
    except OSError as exc:
        raise SafetyError("Cannot stat target device.") from exc
    if stat.S_ISLNK(st.st_mode):
        raise SafetyError("Target device path is a symlink.")
    if not stat.S_ISBLK(st.st_mode):
        raise SafetyError("Target is not a block device.")


def block_rdev(path: str) -> Optional[int]:
    """st_rdev of a whole-disk block node, or None if it cannot be proven."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISBLK(st.st_mode):
        return None
    return int(st.st_rdev)


def block_size_bytes(path: str) -> Optional[int]:
    """Kernel size for `path` via sysfs, or None when sysfs is absent (tests)."""
    name = os.path.basename(os.path.realpath(path))
    if not name or name in {".", ".."}:
        return None
    sysfs = f"/sys/block/{name}/size"
    try:
        with open(sysfs, encoding="ascii") as fh:
            sectors = int(fh.read().strip(), 10)
    except (OSError, ValueError):
        return None
    if sectors <= 0:
        return None
    return sectors * 512


def assert_size_unchanged(path: str, expected_bytes: int) -> None:
    """Refuse if sysfs size disagrees with the size we showed the owner."""
    if expected_bytes <= 0:
        return
    sysfs = block_size_bytes(path)
    if sysfs is None:
        return
    if sysfs != expected_bytes:
        raise SafetyError("Disk size changed. Refusing to erase.")


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
    root_dir = log_dir if log_dir is not None else default_log_dir()
    raw = Path(log_path).expanduser()
    if raw.name in {".", "..", ""} or "/" in raw.name:
        raise SafetyError("Invalid log file name.")
    parent = raw.parent
    try:
        pst = os.lstat(parent)
    except FileNotFoundError as exc:
        raise SafetyError("Log directory is missing.") from exc
    except OSError as exc:
        raise SafetyError("Cannot stat log directory.") from exc
    if stat.S_ISLNK(pst.st_mode):
        raise SafetyError("Refusing to write logs through a symlink.")
    if not stat.S_ISDIR(pst.st_mode):
        raise SafetyError("Log parent is not a directory.")
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
    root = root_dir.resolve()
    if log == root or not _is_under(log, root):
        raise SafetyError("Log file must live under the Beamo Wipe log directory.")
    if log.exists():
        try:
            st = os.lstat(log)
        except OSError as exc:
            raise SafetyError("Cannot stat log file.") from exc
        if stat.S_ISLNK(st.st_mode) or stat.S_ISBLK(st.st_mode) or stat.S_ISCHR(st.st_mode):
            raise SafetyError("Refusing to write logs onto a special file.")
    if not is_preview_env() and _log_filesystem_is_target(log, target):
        raise SafetyError("Refusing to write logs onto the target disk.")


def _log_filesystem_is_target(log: Path, target: str) -> bool:
    """True if mountinfo says `log` lives on `target` (or a partition of it)."""
    if not target:
        return False
    try:
        target_real = os.path.realpath(target)
    except OSError:
        return False
    from beamo_wipe.discover import MOUNTINFO_PATH, parse_mountinfo

    try:
        with open(MOUNTINFO_PATH, encoding="utf-8") as fh:
            pairs = parse_mountinfo(fh.read())
    except OSError:
        return False
    log_text = str(log)
    best_source = ""
    best_len = -1
    for source, mountpoint in pairs:
        mp = mountpoint.rstrip("/") or "/"
        if log_text == mp or log_text.startswith(mp + "/"):
            if len(mp) > best_len:
                best_source = source
                best_len = len(mp)
    if not best_source:
        return False
    src = best_source.split("[", 1)[0].strip()
    if not src.startswith("/dev/"):
        return False
    try:
        src_real = os.path.realpath(src)
    except OSError:
        src_real = src
    if src_real == target_real:
        return True
    if _is_partition_of(src_real, target_real) or _is_partition_of(target_real, src_real):
        return True
    try:
        tst = os.lstat(target_real)
        sst = os.lstat(src_real)
    except OSError:
        return False
    return (
        stat.S_ISBLK(tst.st_mode)
        and stat.S_ISBLK(sst.st_mode)
        and tst.st_rdev == sst.st_rdev
    )


def default_log_dir() -> Path:
    path = DEFAULT_LOG_DIR
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise SafetyError("Cannot create log directory.") from exc
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SafetyError("Refusing unsafe log directory.") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise SafetyError("Refusing unsafe log directory.")
        if st.st_uid != os.getuid():
            raise SafetyError("Log directory must be owned by this process.")
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o700:
            try:
                os.fchmod(fd, 0o700)
            except OSError as exc:
                raise SafetyError("Log directory permissions are unsafe.") from exc
            st = os.fstat(fd)
            if stat.S_IMODE(st.st_mode) != 0o700:
                raise SafetyError("Log directory permissions are unsafe.")
        try:
            tmp_st = os.stat("/tmp")
        except OSError as exc:
            raise SafetyError("Cannot stat /tmp.") from exc
        if st.st_dev != tmp_st.st_dev:
            raise SafetyError("Log directory must be on the /tmp filesystem.")
    finally:
        os.close(fd)
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
    directory = os.path.dirname(log_path)
    name = os.path.basename(log_path)
    if not directory or not name or name in {".", ".."} or "/" in name:
        raise SafetyError("Cannot create log file.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        dirfd = os.open(directory, flags)
    except OSError as exc:
        raise SafetyError(f"Cannot open log directory: {exc}") from exc
    try:
        st = os.fstat(dirfd)
        if not stat.S_ISDIR(st.st_mode):
            raise SafetyError("Log parent is not a directory.")
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        try:
            fd = os.open(name, file_flags, 0o600, dir_fd=dirfd)
        except OSError as exc:
            raise SafetyError(f"Cannot create log file: {exc}") from exc
        try:
            stf = os.fstat(fd)
            if not stat.S_ISREG(stf.st_mode):
                raise SafetyError("Refusing to write logs to a non-regular file.")
        finally:
            os.close(fd)
    finally:
        os.close(dirfd)


def assert_ready_to_wipe(
    *,
    owner_ok: bool,
    disk: Optional[Disk],
    discovery: DiscoveryResult,
    typed_token: str,
    countdown_complete: bool,
    method,
) -> WipeRequest:
    from beamo_wipe.methods import METHODS

    require_live_or_dry_run()
    if not owner_ok:
        raise SafetyError("Owner checkbox is required.")
    assert_boot_excluded(discovery)
    if disk is None or disk.is_boot or has_protected_mount(disk):
        raise SafetyError("No target disk selected.")
    if disk.size_bytes <= 0:
        raise SafetyError("Refusing to erase a zero-size disk.")
    if method not in METHODS:
        raise SafetyError("Unknown wipe method.")
    assert_disk_identity(disk, discovery)
    assert_not_system_mounted(disk)
    spec = confirm_spec(disk, listed_disks(discovery))
    if not token_matches(typed_token, spec):
        raise SafetyError("Confirm token does not match.")
    if not countdown_complete:
        raise SafetyError("Erase delay has not finished.")
    boot = discovery.boot
    if boot is None:
        raise SafetyError("Boot device missing.")
    device = normalize_whole_disk(disk.path, allow_optical=False)
    boot_path = normalize_whole_disk(boot.path, allow_optical=True)
    assert_not_boot(device, boot_path)
    need_block = not is_preview_env()
    assert_existing_is_block_device(device, required=need_block)
    assert_existing_is_block_device(boot_path, required=False)
    assert_size_unchanged(device, disk.size_bytes)
    log = logfile_for(device)
    return WipeRequest(
        device=device,
        method=method,
        boot_device=boot_path,
        logfile=log,
        device_rdev=block_rdev(device) or 0,
        device_size_bytes=disk.size_bytes,
    )


def same_size_conflict(selectable: Iterable[Disk]) -> bool:
    labels = [d.size_gb_label for d in selectable]
    return len(labels) != len(set(labels))
