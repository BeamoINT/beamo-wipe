# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed export of a completed wipe report to one newly inserted USB.

The kiosk never accepts a destination path.  The controller identifies one
new FAT32 USB, then delegates mounting and copying to a short-lived private
mount namespace.  A report is successful only after a read-only remount,
byte-for-byte verification, and a final ordinary unmount.
"""

from __future__ import annotations

import base64
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from beamo_wipe.discover import run_lsblk
from beamo_wipe.evidence import _verified_evidence_bytes
from beamo_wipe.models import Disk, DiscoveryResult
from beamo_wipe.safety import CLEAN_SUBPROCESS_ENV, SafetyError


UNSHARE_BIN = "/usr/bin/unshare"
PYTHON_BIN = "/usr/bin/python3"
MOUNT_BIN = "/usr/bin/mount"
UMOUNT_BIN = "/usr/bin/umount"
SYNC_BIN = "/usr/bin/sync"
MOUNTINFO_PATH = "/proc/self/mountinfo"
SYS_DEV_BLOCK_ROOT = Path("/sys/dev/block")
MOUNT_ROOT = Path("/run/beamo-wipe-export")
REPORTS_DIR = "BEAMO-WIPE-REPORTS"
SUPPORTED_FILESYSTEMS = frozenset({"vfat"})
TERMINAL_OUTCOMES = frozenset({"completed", "verified", "failed", "interrupted"})
EXPORT_TIMEOUT_S = 120
COMMAND_TIMEOUT_S = 15
MAX_LOG_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MIN_VOLUME_BYTES = 1024 * 1024
DEVICE_PATH_RE = re.compile(r"^/dev/sd[a-z]+(?:[0-9]+)?$")
DISK_PATH_RE = re.compile(r"^/dev/sd[a-z]+$")
ROOT_PATH_RE = re.compile(
    r"^/dev/(?:sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|dasd[a-z]+|"
    r"nvme[0-9]+n[0-9]+|mmcblk[0-9]+|sr[0-9]+)$"
)
# Kernel-created non-target roots that normal discovery intentionally hides.
# They can be reported as TYPE=disk by lsblk, but can never be a report USB.
IGNORED_ROOT_PATH_RE = re.compile(
    r"^/dev/(?:fd|ram|zram)[0-9]+$|^/dev/mmcblk[0-9]+(?:boot[0-9]+|rpmb)$"
)
BLOCK_PATH_RE = re.compile(
    r"^/dev/(?:sd[a-z]+[0-9]*|hd[a-z]+[0-9]*|vd[a-z]+[0-9]*|"
    r"xvd[a-z]+[0-9]*|dasd[a-z]+[0-9]*|nvme[0-9]+n[0-9]+(?:p[0-9]+)?|"
    r"mmcblk[0-9]+(?:p[0-9]+|boot[0-9]+|rpmb)?|sr[0-9]+)$"
)
SAFE_ID_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")
SESSION_RE = re.compile(r"^report-[0-9a-f]{24}$")


def _emit_export_marker(marker: str) -> None:
    """Best-effort, identifier-free progress for isolated QEMU diagnostics."""
    try:
        from beamo_wipe.diagnostics import emit_serial_marker

        emit_serial_marker(marker)
    except Exception:
        pass


def _emit_export_failure(exc: Exception) -> None:
    """Map a failure message to one fixed marker without exporting metadata."""
    detail = str(exc)
    if detail == "The report USB device path is unsupported.":
        marker = "BEAMO_WIPE_EXPORT_FAIL_DEVICE_PATH"
    elif detail == "The report USB layout is malformed.":
        marker = "BEAMO_WIPE_EXPORT_FAIL_CHILDREN"
    elif detail == "The report USB layout is ambiguous.":
        marker = "BEAMO_WIPE_EXPORT_FAIL_AMBIGUOUS"
    elif detail == "The report USB layout is unsupported.":
        marker = "BEAMO_WIPE_EXPORT_FAIL_UNSUPPORTED_LAYOUT"
    elif detail == "The report USB partition does not belong to its parent disk.":
        marker = "BEAMO_WIPE_EXPORT_FAIL_PARENT_LINK"
    elif detail == "The report USB volume path is unsupported.":
        marker = "BEAMO_WIPE_EXPORT_FAIL_VOLUME_PATH"
    elif "metadata" in detail or "malformed data" in detail:
        marker = "BEAMO_WIPE_EXPORT_FAIL_METADATA"
    elif detail.startswith("Leave the Beamo USB"):
        marker = "BEAMO_WIPE_EXPORT_FAIL_BASELINE"
    elif "removable USB" in detail:
        marker = "BEAMO_WIPE_EXPORT_FAIL_REMOVABLE"
    elif "exactly one" in detail:
        marker = "BEAMO_WIPE_EXPORT_FAIL_COUNT"
    elif "mounted" in detail or "unmounted" in detail:
        marker = "BEAMO_WIPE_EXPORT_FAIL_MOUNTED"
    elif "layout" in detail or "partition" in detail or "path" in detail:
        marker = "BEAMO_WIPE_EXPORT_FAIL_LAYOUT"
    elif "small" in detail or "size" in detail:
        marker = "BEAMO_WIPE_EXPORT_FAIL_SIZE"
    elif "FAT" in detail or "filesystem" in detail:
        marker = "BEAMO_WIPE_EXPORT_FAIL_FAT32"
    else:
        marker = "BEAMO_WIPE_EXPORT_FAIL_OTHER"
    _emit_export_marker(marker)


@dataclass(frozen=True)
class DeviceFingerprint:
    path: str
    size_bytes: int
    model: str
    serial: str
    wwn: str
    rdev: int = 0
    required: bool = True


@dataclass(frozen=True)
class ExportVolume:
    parent: DeviceFingerprint
    path: str
    size_bytes: int
    fstype: str
    fsver: str
    uuid: str
    rdev: int = 0


@dataclass(frozen=True)
class VerifiedEvidence:
    data: bytes
    sha256: str
    outcome: str
    logfile: str
    log_sha256: str
    log_size_bytes: int


@dataclass(frozen=True)
class ExportReceipt:
    ok: bool
    safe_to_remove: bool
    code: str
    evidence_sha256: str = ""
    session_name: str = ""
    log_status: str = "unavailable"


def _strict_text(node: Mapping[str, Any], key: str, *, required: bool = False) -> str:
    value = node.get(key)
    if value is None:
        if required:
            raise SafetyError("The report USB metadata is incomplete.")
        return ""
    if (
        not isinstance(value, str)
        or (value and not SAFE_ID_RE.fullmatch(value))
        or any(unicodedata.category(ch).startswith("C") for ch in value)
    ):
        raise SafetyError("The report USB metadata is malformed.")
    text = value.strip()
    if text != value or (required and not text):
        raise SafetyError("The report USB metadata is malformed.")
    return text


def _strict_int(node: Mapping[str, Any], key: str) -> int:
    value = node.get(key)
    if isinstance(value, bool):
        raise SafetyError("The report USB metadata is malformed.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        parsed = int(value)
    else:
        raise SafetyError("The report USB metadata is incomplete.")
    if parsed <= 0:
        raise SafetyError("The report USB size is invalid.")
    return parsed


def _strict_bool(node: Mapping[str, Any], key: str) -> bool:
    value = node.get(key)
    if value is True or (
        isinstance(value, int) and not isinstance(value, bool) and value == 1
    ):
        return True
    if isinstance(value, str) and value in {"1", "true"}:
        return True
    if value is False or (
        isinstance(value, int) and not isinstance(value, bool) and value == 0
    ):
        return False
    if isinstance(value, str) and value in {"0", "false"}:
        return False
    raise SafetyError("The report USB metadata is incomplete.")


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = node.get("children", [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(child, dict) for child in value):
        raise SafetyError("The report USB layout is malformed.")
    return value


def _unmounted(node: Mapping[str, Any]) -> bool:
    if "mountpoints" not in node or "mountpoint" not in node:
        raise SafetyError("The report USB mount metadata is incomplete.")
    mountpoints = node.get("mountpoints")
    if not isinstance(mountpoints, list):
        raise SafetyError("The report USB mount metadata is malformed.")
    for value in mountpoints:
        if value is not None and (not isinstance(value, str) or value.strip()):
            return False
    mountpoint = node.get("mountpoint")
    if mountpoint is not None and (not isinstance(mountpoint, str) or mountpoint.strip()):
        return False
    return all(_unmounted(child) for child in _children(node))


def _fingerprint_node(
    node: Mapping[str, Any], *, export_parent: bool = False
) -> DeviceFingerprint:
    path = _strict_text(node, "path", required=True)
    path_pattern = DISK_PATH_RE if export_parent else ROOT_PATH_RE
    if not path_pattern.fullmatch(path):
        raise SafetyError("The report USB device path is unsupported.")
    return DeviceFingerprint(
        path=path,
        size_bytes=_strict_int(node, "size"),
        model=_strict_text(node, "model"),
        serial=_strict_text(node, "serial"),
        wwn=_strict_text(node, "wwn"),
    )


def baseline_fingerprints(
    disks: Sequence[Disk], *, required_paths: Optional[set[str]] = None
) -> tuple[DeviceFingerprint, ...]:
    required_realpaths = (
        None
        if required_paths is None
        else {os.path.realpath(path) for path in required_paths}
    )
    fingerprints = []
    for disk in disks:
        raw_model = getattr(disk, "raw_model", None)
        fingerprints.append(
            DeviceFingerprint(
                path=disk.path,
                size_bytes=disk.size_bytes,
                model=(disk.model or "") if raw_model is None else raw_model,
                serial=disk.serial or "",
                wwn=disk.wwn or "",
                required=(
                    True
                    if required_realpaths is None
                    else os.path.realpath(disk.path) in required_realpaths
                ),
            )
        )
    return tuple(fingerprints)


def _same_device(left: DeviceFingerprint, right: DeviceFingerprint) -> bool:
    if left.path == right.path:
        return True
    if left.wwn and right.wwn and left.wwn.casefold() == right.wwn.casefold():
        return True
    return bool(
        left.serial
        and right.serial
        and left.serial.casefold() == right.serial.casefold()
        and left.size_bytes == right.size_bytes
        and left.model.casefold() == right.model.casefold()
    )


def _root_disks(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    devices = payload.get("blockdevices")
    if not isinstance(devices, list) or any(not isinstance(node, dict) for node in devices):
        raise SafetyError("Disk discovery returned malformed data.")
    roots: list[Mapping[str, Any]] = []
    seen_paths: set[str] = set()
    for node in devices:
        node_type = _strict_text(node, "type", required=True)
        if node_type not in {"disk", "rom"}:
            continue
        path = _strict_text(node, "path", required=True)
        if IGNORED_ROOT_PATH_RE.fullmatch(path):
            continue
        if path in seen_paths:
            raise SafetyError("Disk discovery returned duplicate devices.")
        seen_paths.add(path)
        roots.append(node)
    return roots


def _require_baseline_present(
    roots: Sequence[Mapping[str, Any]], baseline: Sequence[DeviceFingerprint]
) -> None:
    current = [_fingerprint_node(node) for node in roots]
    for expected in baseline:
        if not expected.required:
            continue
        matches = [
            item
            for item in current
            if item.path == expected.path
            and item.size_bytes == expected.size_bytes
            and (not expected.wwn or item.wwn.casefold() == expected.wwn.casefold())
            and (not expected.serial or item.serial.casefold() == expected.serial.casefold())
            and (not expected.model or item.model.casefold() == expected.model.casefold())
        ]
        if len(matches) != 1:
            raise SafetyError(
                "Leave the Beamo USB and selected disk connected, then try again."
            )


def select_export_volume(
    payload: Mapping[str, Any], baseline: Sequence[DeviceFingerprint]
) -> ExportVolume:
    """Return exactly one new, simple, writable FAT32 USB volume."""
    roots = _root_disks(payload)
    _require_baseline_present(roots, baseline)
    new_usb: list[Mapping[str, Any]] = []
    for node in roots:
        if _strict_text(node, "type", required=True) != "disk":
            continue
        fp = _fingerprint_node(node)
        if any(_same_device(fp, old) for old in baseline):
            continue
        tran = _strict_text(node, "tran", required=True)
        if tran != "usb":
            continue
        if not _strict_bool(node, "rm") or not _strict_bool(node, "hotplug"):
            raise SafetyError("The new device is not identified as a removable USB.")
        new_usb.append(node)
    if len(new_usb) != 1:
        raise SafetyError("Insert exactly one new FAT32 report USB, then try again.")

    parent_node = new_usb[0]
    parent = _fingerprint_node(parent_node, export_parent=True)
    if _strict_bool(parent_node, "ro") or not _unmounted(parent_node):
        raise SafetyError("The report USB must be writable and not already mounted.")
    children = _children(parent_node)
    parent_fstype = _strict_text(parent_node, "fstype")
    if parent_fstype:
        if children:
            raise SafetyError("The report USB layout is ambiguous.")
        volume_node = parent_node
    else:
        if len(children) != 1:
            raise SafetyError("The report USB must contain exactly one FAT32 volume.")
        volume_node = children[0]
        if _strict_text(volume_node, "type", required=True) != "part" or _children(volume_node):
            raise SafetyError("The report USB layout is unsupported.")
        if (
            _strict_text(volume_node, "pkname", required=True)
            != os.path.basename(parent.path)
        ):
            raise SafetyError("The report USB partition does not belong to its parent disk.")

    volume_path = _strict_text(volume_node, "path", required=True)
    if not DEVICE_PATH_RE.fullmatch(volume_path):
        raise SafetyError("The report USB volume path is unsupported.")
    if volume_node is not parent_node and not re.fullmatch(
        re.escape(parent.path) + r"[0-9]+", volume_path
    ):
        raise SafetyError("The report USB partition does not belong to its parent disk.")
    if _strict_bool(volume_node, "ro") or not _unmounted(volume_node):
        raise SafetyError("The report USB volume must be writable and unmounted.")
    size_bytes = _strict_int(volume_node, "size")
    if size_bytes < MIN_VOLUME_BYTES:
        raise SafetyError("The report USB volume is too small.")
    fstype = _strict_text(volume_node, "fstype", required=True)
    if fstype not in SUPPORTED_FILESYSTEMS:
        raise SafetyError("Use a FAT32 report USB. Other filesystems are not mounted.")
    fsver = _strict_text(volume_node, "fsver", required=True)
    if fsver != "FAT32":
        raise SafetyError("Use a FAT32 report USB. FAT12 and FAT16 are not accepted.")
    uuid = _strict_text(volume_node, "uuid", required=True)
    return ExportVolume(
        parent=parent,
        path=volume_path,
        size_bytes=size_bytes,
        fstype=fstype,
        fsver=fsver,
        uuid=uuid,
    )


def prepare_terminal_evidence(path: Path, target_path: str) -> VerifiedEvidence:
    data = _verified_evidence_bytes(Path(path))
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafetyError("The saved wipe evidence is malformed.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SafetyError("The saved wipe evidence has an unsupported schema.")
    outcome = payload.get("outcome")
    if outcome not in TERMINAL_OUTCOMES:
        raise SafetyError("Only a finished wipe report can be exported.")
    device = payload.get("device")
    if not isinstance(device, dict) or not isinstance(device.get("path"), str):
        raise SafetyError("The saved wipe evidence is missing its disk identity.")
    if os.path.realpath(device["path"]) != os.path.realpath(target_path):
        raise SafetyError("The saved wipe evidence is for a different disk.")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("evidence_file") != str(path):
        raise SafetyError("The saved wipe evidence provenance does not match.")
    logfile = payload.get("logfile")
    if not isinstance(logfile, str):
        raise SafetyError("The saved wipe evidence has malformed log metadata.")
    log_sha256 = payload.get("log_checksum_sha256")
    log_size_bytes = payload.get("log_snapshot_size_bytes")
    if log_sha256 is None and log_size_bytes in (None, 0):
        log_sha256 = ""
        log_size_bytes = 0
    if (
        not isinstance(log_sha256, str)
        or (log_sha256 and not re.fullmatch(r"[0-9a-f]{64}", log_sha256))
        or isinstance(log_size_bytes, bool)
        or not isinstance(log_size_bytes, int)
        or log_size_bytes < 0
        or log_size_bytes > MAX_LOG_BYTES
        or bool(log_sha256) != bool(log_size_bytes)
    ):
        raise SafetyError("The saved wipe evidence has malformed log metadata.")
    return VerifiedEvidence(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        outcome=outcome,
        logfile=logfile,
        log_sha256=log_sha256,
        log_size_bytes=log_size_bytes,
    )


def read_export_log(
    path: str, *, expected_sha256: str = "", expected_size_bytes: int = 0
) -> tuple[bytes, str]:
    """Read only the exact log suffix authenticated by terminal evidence."""
    if (
        not path
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or isinstance(expected_size_bytes, bool)
        or not isinstance(expected_size_bytes, int)
        or not 0 < expected_size_bytes <= MAX_LOG_BYTES
    ):
        return b"", "unavailable"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return b"", "unavailable"
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
        ):
            return b"", "unavailable"
        truncated = before.st_size > MAX_LOG_BYTES
        if truncated:
            os.lseek(fd, before.st_size - MAX_LOG_BYTES, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = min(before.st_size, MAX_LOG_BYTES)
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            return b"", "unavailable"
        raw_data = b"".join(chunks)
        if len(raw_data) != min(before.st_size, MAX_LOG_BYTES):
            return b"", "unavailable"
        # Evidence hashes the UTF-8 text that the runner used for completion
        # parsing. Recreate that normalization, then authenticate the exact
        # suffix and export no mutable bytes on any mismatch.
        normalized = raw_data.decode("utf-8", errors="replace").encode("utf-8")
        if expected_size_bytes > len(normalized):
            return b"", "unavailable"
        data = normalized[-expected_size_bytes:]
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            return b"", "unavailable"
        complete = not truncated and expected_size_bytes == len(normalized)
        return data, "complete" if complete else "tail"
    finally:
        os.close(fd)


def _block_rdev(path: str) -> int:
    try:
        opened = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SafetyError("The report USB disappeared before it could be opened.") from exc
    if not stat.S_ISBLK(opened.st_mode) or opened.st_rdev <= 0:
        raise SafetyError("The report USB path is not a block device.")
    return opened.st_rdev


def _volume_with_rdev(volume: ExportVolume) -> ExportVolume:
    parent_rdev = _block_rdev(volume.parent.path)
    volume_rdev = _block_rdev(volume.path)
    return ExportVolume(
        parent=DeviceFingerprint(**{**asdict(volume.parent), "rdev": parent_rdev}),
        path=volume.path,
        size_bytes=volume.size_bytes,
        fstype=volume.fstype,
        fsver=volume.fsver,
        uuid=volume.uuid,
        rdev=volume_rdev,
    )


def _baseline_with_rdev(
    baseline: Sequence[DeviceFingerprint],
) -> tuple[DeviceFingerprint, ...]:
    return tuple(
        DeviceFingerprint(
            **{
                **asdict(item),
                # Only the boot medium and selected target are required to
                # remain attached. Other disks are still protected by the
                # fresh scan's descendant rdev set when present, but their
                # removal must not make a legitimate report retry impossible.
                "rdev": _block_rdev(item.path) if item.required else 0,
            }
        )
        for item in baseline
    )


def _protected_paths(
    payload: Mapping[str, Any], baseline: Sequence[DeviceFingerprint]
) -> tuple[str, ...]:
    """Return every node beneath an original disk still present in this scan."""
    protected: set[str] = set()

    def add_tree(node: Mapping[str, Any]) -> None:
        path = _strict_text(node, "path", required=True)
        if not BLOCK_PATH_RE.fullmatch(path) or path in protected:
            raise SafetyError("A protected disk layout is malformed or ambiguous.")
        protected.add(path)
        for child in _children(node):
            add_tree(child)

    for root in _root_disks(payload):
        current = _fingerprint_node(root)
        if any(_same_device(current, original) for original in baseline):
            add_tree(root)
    return tuple(sorted(protected))


def _protected_rdevs(
    payload: Mapping[str, Any], baseline: Sequence[DeviceFingerprint]
) -> tuple[int, ...]:
    values = tuple(sorted({_block_rdev(path) for path in _protected_paths(payload, baseline)}))
    if not values or any(value <= 0 for value in values):
        raise SafetyError("A protected disk identity could not be verified.")
    return values


def _same_volume(left: ExportVolume, right: ExportVolume, *, include_rdev: bool) -> bool:
    if include_rdev:
        return left == right
    return (
        left.path,
        left.size_bytes,
        left.fstype,
        left.fsver,
        left.uuid,
        left.parent.path,
        left.parent.size_bytes,
        left.parent.model,
        left.parent.serial,
        left.parent.wwn,
    ) == (
        right.path,
        right.size_bytes,
        right.fstype,
        right.fsver,
        right.uuid,
        right.parent.path,
        right.parent.size_bytes,
        right.parent.model,
        right.parent.serial,
        right.parent.wwn,
    )


def _request_dict(
    evidence: VerifiedEvidence,
    volume: ExportVolume,
    baseline: Sequence[DeviceFingerprint],
    protected_rdevs: Sequence[int],
    log_data: bytes,
    log_status: str,
) -> dict[str, Any]:
    return {
        "evidence": base64.b64encode(evidence.data).decode("ascii"),
        "evidence_sha256": evidence.sha256,
        "volume": asdict(volume),
        "baseline": [asdict(item) for item in baseline],
        "protected_rdevs": list(protected_rdevs),
        "log": base64.b64encode(log_data).decode("ascii"),
        "log_status": log_status,
    }


def export_to_new_usb(
    *,
    evidence_path: Path,
    discovery: DiscoveryResult,
    target_path: str,
    target_rdev: int = 0,
    boot_rdev: int = 0,
    expected_evidence_sha256: str = "",
    scan: Callable[[], Mapping[str, Any]] = run_lsblk,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ExportReceipt:
    """Discover and export through the private worker. No path is user supplied."""
    _emit_export_marker("BEAMO_WIPE_EXPORT_CONTROLLER_STARTED")
    try:
        evidence = prepare_terminal_evidence(Path(evidence_path), target_path)
    except SafetyError as exc:
        _emit_export_failure(exc)
        raise
    _emit_export_marker("BEAMO_WIPE_EXPORT_EVIDENCE_VERIFIED")
    if (
        expected_evidence_sha256
        and evidence.sha256 != expected_evidence_sha256
    ):
        raise SafetyError("The finished wipe report changed before export.")
    required_paths = {target_path}
    if discovery.boot is not None:
        required_paths.add(discovery.boot.path)
    baseline_without_rdev = baseline_fingerprints(
        discovery.disks, required_paths=required_paths
    )
    first_payload = scan()
    _emit_export_marker("BEAMO_WIPE_EXPORT_SCAN_ONE")
    try:
        first = select_export_volume(first_payload, baseline_without_rdev)
    except SafetyError as exc:
        _emit_export_failure(exc)
        raise
    _emit_export_marker("BEAMO_WIPE_EXPORT_SELECT_ONE")
    second_payload = scan()
    _emit_export_marker("BEAMO_WIPE_EXPORT_SCAN_TWO")
    try:
        second = select_export_volume(second_payload, baseline_without_rdev)
    except SafetyError as exc:
        _emit_export_failure(exc)
        raise
    if not _same_volume(first, second, include_rdev=False):
        raise SafetyError("The report USB changed during discovery. Try again.")
    _emit_export_marker("BEAMO_WIPE_EXPORT_CONTROLLER_SELECTED")
    baseline = _baseline_with_rdev(baseline_without_rdev)
    protected_rdevs = set(_protected_rdevs(second_payload, baseline_without_rdev))
    protected_rdevs.update(item.rdev for item in baseline if item.rdev > 0)
    protected_rdevs.update(value for value in (target_rdev, boot_rdev) if value > 0)
    volume = _volume_with_rdev(second)
    if volume.rdev in protected_rdevs or volume.parent.rdev in protected_rdevs:
        raise SafetyError("The report USB is the boot device or selected disk.")
    _emit_export_marker("BEAMO_WIPE_EXPORT_CONTROLLER_IDENTIFIED")
    log_data, log_status = read_export_log(
        evidence.logfile,
        expected_sha256=evidence.log_sha256,
        expected_size_bytes=evidence.log_size_bytes,
    )
    request = json.dumps(
        _request_dict(
            evidence,
            volume,
            baseline,
            sorted(protected_rdevs),
            log_data,
            log_status,
        ),
        separators=(",", ":"),
        sort_keys=True,
    )
    command = [
        UNSHARE_BIN,
        "--mount",
        "--propagation",
        "private",
        "--",
        PYTHON_BIN,
        "-sP",
        "-m",
        "beamo_wipe.support_export",
        "--worker",
    ]
    try:
        proc = run(
            command,
            input=request,
            text=True,
            capture_output=True,
            check=False,
            timeout=EXPORT_TIMEOUT_S,
            shell=False,
            env=CLEAN_SUBPROCESS_ENV,
            close_fds=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise SafetyError("Saving the report timed out. Shut down before removing the USB.") from exc
    except OSError as exc:
        raise SafetyError("The isolated report helper could not start.") from exc
    if proc.returncode != 0 or len(proc.stdout or "") > 8192:
        raise SafetyError("The isolated report helper failed. Shut down before removing the USB.")
    try:
        raw = json.loads((proc.stdout or "").strip())
        required_receipt_keys = {
            "ok",
            "safe_to_remove",
            "code",
            "evidence_sha256",
            "session_name",
            "log_status",
        }
        if (
            not isinstance(raw, dict)
            or set(raw) != required_receipt_keys
            or type(raw["ok"]) is not bool
            or type(raw["safe_to_remove"]) is not bool
            or any(
                not isinstance(raw[key], str)
                for key in (
                    "code",
                    "evidence_sha256",
                    "session_name",
                    "log_status",
                )
            )
        ):
            raise TypeError("invalid receipt schema")
        receipt = ExportReceipt(**raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SafetyError("The isolated report helper returned an invalid receipt.") from exc
    if receipt.ok is True:
        if (
            not receipt.safe_to_remove
            or receipt.code != "saved_verified_unmounted"
            or receipt.evidence_sha256 != evidence.sha256
            or not SESSION_RE.fullmatch(receipt.session_name)
            or receipt.log_status != log_status
        ):
            raise SafetyError("The exported report success receipt is invalid.")
    elif receipt != ExportReceipt(False, False, "export_failed"):
        # Failure is an exact fail-closed state. In particular, never return a
        # contradictory safe-to-remove flag from untrusted worker stdout.
        raise SafetyError("The exported report returned an invalid receipt for failure.")
    return receipt


def _full_write(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "short report write")
        view = view[written:]


def _write_exclusive(directory_fd: int, name: str, data: bytes) -> None:
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        _full_write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_at(directory_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise SafetyError("The exported report contains an unsafe file.")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _bundle_files(evidence: bytes, log_data: bytes, log_status: str) -> dict[str, bytes]:
    evidence_hash = hashlib.sha256(evidence).hexdigest()
    files: dict[str, bytes] = {
        "result.json": evidence,
        "result.json.sha256": f"{evidence_hash}  result.json\n".encode("ascii"),
    }
    if log_data:
        log_name = "nwipe-tail.log" if log_status == "tail" else "nwipe.log"
        files[log_name] = log_data
        files[f"{log_name}.sha256"] = (
            f"{hashlib.sha256(log_data).hexdigest()}  {log_name}\n".encode("ascii")
        )
    from beamo_wipe.outcomes import present_evidence
    try:
        result_view = present_evidence(json.loads(evidence))
    except (ValueError, UnicodeDecodeError):
        result_view = present_evidence(None)
    readme = (
        f"{result_view.announcement}\r\n"
        "Beamo Wipe report\r\n"
        "result.json records the wipe outcome and disk identifiers.\r\n"
        f"nwipe log: {log_status}.\r\n"
        "COMPLETE authenticates these file contents only. It does not claim that the USB is safe to remove.\r\n"
    ).encode("utf-8")
    files["README.txt"] = readme
    manifest = {
        "manifest_scope": "content_only",
        "safe_to_remove": False,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "log_status": log_status,
        "schema_version": 1,
    }
    files["COMPLETE"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return files


def write_report_bundle(
    mountpoint: Path,
    evidence: bytes,
    log_data: bytes,
    log_status: str,
    *,
    session_name: Optional[str] = None,
) -> tuple[str, dict[str, bytes]]:
    """Write one unique, completion-marked bundle using directory-relative FDs."""
    mount_fd = os.open(str(mountpoint), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    reports_fd = -1
    session_fd = -1
    try:
        try:
            os.mkdir(REPORTS_DIR, 0o700, dir_fd=mount_fd)
        except FileExistsError:
            pass
        reports_fd = os.open(
            REPORTS_DIR,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=mount_fd,
        )
        if session_name is not None:
            candidates: Iterable[str] = (session_name,)
        else:
            candidates = (f"report-{secrets.token_hex(12)}" for _ in range(8))
        chosen = ""
        for candidate in candidates:
            if not SESSION_RE.fullmatch(candidate):
                raise SafetyError("Invalid report session name.")
            try:
                os.mkdir(candidate, 0o700, dir_fd=reports_fd)
                chosen = candidate
                break
            except FileExistsError:
                continue
        if not chosen:
            raise SafetyError("Could not allocate a unique report directory.")
        session_fd = os.open(
            chosen,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=reports_fd,
        )
        files = _bundle_files(evidence, log_data, log_status)
        complete = files.pop("COMPLETE")
        for name, data in files.items():
            _write_exclusive(session_fd, name, data)
        # Persist all content and its directory entries before publishing the
        # content-only manifest. A crash/failure before this boundary leaves no
        # COMPLETE marker at all.
        os.fsync(session_fd)
        os.fsync(reports_fd)
        os.fsync(mount_fd)
        _write_exclusive(session_fd, "COMPLETE", complete)
        files["COMPLETE"] = complete
        os.fsync(session_fd)
        os.fsync(reports_fd)
        os.fsync(mount_fd)
        return chosen, files
    finally:
        if session_fd >= 0:
            os.close(session_fd)
        if reports_fd >= 0:
            os.close(reports_fd)
        os.close(mount_fd)


def verify_report_bundle(mountpoint: Path, session_name: str, files: Mapping[str, bytes]) -> None:
    if not SESSION_RE.fullmatch(session_name):
        raise SafetyError("The report receipt contains an invalid directory name.")
    path = mountpoint / REPORTS_DIR / session_name
    directory_fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        names = sorted(os.listdir(directory_fd))
        if names != sorted(files):
            raise SafetyError("The exported report file set changed.")
        for name, expected in files.items():
            if _read_at(directory_fd, name) != expected:
                raise SafetyError("The exported report did not pass read-back verification.")
    finally:
        os.close(directory_fd)


def _mount_record(mountpoint: Path) -> Optional[tuple[str, str, str, frozenset[str]]]:
    try:
        text = Path(MOUNTINFO_PATH).read_text(encoding="utf-8")
    except OSError as exc:
        raise SafetyError("Could not verify the report USB mount.") from exc
    wanted = str(mountpoint)
    matches: list[tuple[str, str, str, frozenset[str]]] = []
    for line in text.splitlines():
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        left_parts = left.split()
        right_parts = right.split()
        if len(left_parts) < 6 or len(right_parts) < 3 or left_parts[4] != wanted:
            continue
        options = frozenset(left_parts[5].split(",")) | frozenset(right_parts[2].split(","))
        matches.append((left_parts[2], right_parts[0], right_parts[1], options))
    if len(matches) > 1:
        raise SafetyError("The report mountpoint is ambiguous.")
    return matches[0] if matches else None


def _verify_mount(mountpoint: Path, volume: ExportVolume, *, read_only: bool) -> None:
    record = _mount_record(mountpoint)
    if record is None:
        raise SafetyError("The report USB was not mounted.")
    major_minor, fstype, source, options = record
    if fstype != volume.fstype or major_minor != f"{os.major(volume.rdev)}:{os.minor(volume.rdev)}":
        raise SafetyError("The report mount identity does not match the selected USB.")
    try:
        source_stat = os.stat(source, follow_symlinks=False)
        mounted_stat = os.stat(mountpoint, follow_symlinks=False)
    except OSError as exc:
        raise SafetyError("The report mount identity could not be checked.") from exc
    if source_stat.st_rdev != volume.rdev or mounted_stat.st_dev != volume.rdev:
        raise SafetyError("The report mount source changed.")
    required = {"nodev", "nosuid", "noexec", "nosymfollow", "ro" if read_only else "rw"}
    if not required.issubset(options):
        raise SafetyError("The report USB mount is missing required safety options.")


def _run_command(
    command: Sequence[str], *, pass_fds: Sequence[int] = ()
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT_S,
        shell=False,
        env=CLEAN_SUBPROCESS_ENV,
        close_fds=True,
        pass_fds=tuple(pass_fds),
    )


def _mounted_exact(mountpoint: Path, volume: ExportVolume) -> bool:
    try:
        record = _mount_record(mountpoint)
    except SafetyError:
        return False
    return bool(
        record
        and record[0] == f"{os.major(volume.rdev)}:{os.minor(volume.rdev)}"
        and record[1] == volume.fstype
    )


def _ordinary_unmount(mountpoint: Path, volume: ExportVolume) -> bool:
    if not _mounted_exact(mountpoint, volume):
        return _mount_record(mountpoint) is None
    proc = _run_command([UMOUNT_BIN, "--", str(mountpoint)])
    return proc.returncode == 0 and _mount_record(mountpoint) is None


def _decode_worker_request(
    raw: bytes,
) -> tuple[
    VerifiedEvidence,
    ExportVolume,
    list[DeviceFingerprint],
    tuple[int, ...],
    bytes,
    str,
]:
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise SafetyError("Invalid report request size.")
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "evidence",
            "evidence_sha256",
            "volume",
            "baseline",
            "protected_rdevs",
            "log",
            "log_status",
        }:
            raise TypeError("unexpected request fields")
        evidence_data = base64.b64decode(payload["evidence"], validate=True)
        log_data = base64.b64decode(payload["log"], validate=True)
        volume_raw = dict(payload["volume"])
        parent = DeviceFingerprint(**volume_raw.pop("parent"))
        volume = ExportVolume(parent=parent, **volume_raw)
        baseline = [DeviceFingerprint(**item) for item in payload["baseline"]]
        protected_raw = payload["protected_rdevs"]
        if (
            not isinstance(protected_raw, list)
            or any(type(value) is not int or value <= 0 for value in protected_raw)
            or len(set(protected_raw)) != len(protected_raw)
        ):
            raise TypeError("invalid protected identities")
        protected_rdevs = tuple(sorted(protected_raw))
        log_status = payload["log_status"]
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise SafetyError("Malformed report request.") from exc
    evidence_hash = hashlib.sha256(evidence_data).hexdigest()
    if payload.get("evidence_sha256") != evidence_hash:
        raise SafetyError("Report request checksum mismatch.")
    if log_status not in {"complete", "tail", "unavailable"}:
        raise SafetyError("Malformed report log status.")
    if (log_status == "unavailable") != (not log_data):
        raise SafetyError("Malformed report log payload.")
    return (
        VerifiedEvidence(evidence_data, evidence_hash, "", "", "", 0),
        volume,
        baseline,
        protected_rdevs,
        log_data,
        log_status,
    )


def _assert_partition_parent(volume: ExportVolume) -> None:
    """Prove a partition rdev is a child of the selected whole-disk rdev."""
    if volume.path == volume.parent.path:
        if volume.rdev != volume.parent.rdev:
            raise SafetyError("The report USB block identity changed.")
        return
    sysfs_link = SYS_DEV_BLOCK_ROOT / f"{os.major(volume.rdev)}:{os.minor(volume.rdev)}"
    resolved = Path(os.path.realpath(sysfs_link))
    try:
        if (
            not str(resolved).startswith("/sys/devices/")
            or not (resolved / "partition").is_file()
        ):
            raise SafetyError("The report USB partition relationship is invalid.")
        text = (resolved.parent / "dev").read_text(encoding="ascii").strip()
        major_text, minor_text = text.split(":", 1)
        parent_rdev = os.makedev(int(major_text), int(minor_text))
    except (OSError, ValueError) as exc:
        raise SafetyError("The report USB partition relationship could not be verified.") from exc
    if parent_rdev != volume.parent.rdev:
        raise SafetyError("The report USB partition does not belong to its parent disk.")


def _persist_and_verify_report(
    volume: ExportVolume,
    evidence: VerifiedEvidence,
    log_data: bytes,
    log_status: str,
    volume_fd: int,
) -> ExportReceipt:
    """Run the mounted-media state machine after block identity is pinned."""
    lock_fd = -1
    mountpoint: Optional[Path] = None
    mounted = False
    try:
        MOUNT_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(MOUNT_ROOT, 0o700)
        lock_fd = os.open(
            str(MOUNT_ROOT / ".lock"),
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SafetyError("Another report export is already running.") from exc
        mountpoint = MOUNT_ROOT / f"mount-{secrets.token_hex(12)}"
        mountpoint.mkdir(mode=0o700)
        stable_source = f"/proc/self/fd/{volume_fd}"
        rw_options = "rw,nodev,nosuid,noexec,nosymfollow,umask=077"
        proc = _run_command(
            [MOUNT_BIN, "-t", volume.fstype, "-o", rw_options, stable_source, str(mountpoint)],
            pass_fds=(volume_fd,),
        )
        mounted = _mounted_exact(mountpoint, volume)
        if proc.returncode != 0 or not mounted:
            raise SafetyError("The report USB could not be mounted safely.")
        _verify_mount(mountpoint, volume, read_only=False)
        _emit_export_marker("BEAMO_WIPE_EXPORT_RW_MOUNTED")
        session_name, files = write_report_bundle(
            mountpoint, evidence.data, log_data, log_status
        )
        sync_proc = _run_command([SYNC_BIN, "-f", str(mountpoint)])
        if sync_proc.returncode != 0:
            raise SafetyError("The report USB could not be synchronized.")
        _emit_export_marker("BEAMO_WIPE_EXPORT_BUNDLE_WRITTEN")
        if not _ordinary_unmount(mountpoint, volume):
            mounted = _mounted_exact(mountpoint, volume)
            raise SafetyError("The report USB could not be unmounted.")
        mounted = False
        _emit_export_marker("BEAMO_WIPE_EXPORT_RW_UNMOUNTED")

        ro_options = "ro,nodev,nosuid,noexec,nosymfollow"
        proc = _run_command(
            [MOUNT_BIN, "-t", volume.fstype, "-o", ro_options, stable_source, str(mountpoint)],
            pass_fds=(volume_fd,),
        )
        mounted = _mounted_exact(mountpoint, volume)
        if proc.returncode != 0 or not mounted:
            raise SafetyError("The report USB could not be remounted for verification.")
        _verify_mount(mountpoint, volume, read_only=True)
        _emit_export_marker("BEAMO_WIPE_EXPORT_RO_MOUNTED")
        verify_report_bundle(mountpoint, session_name, files)
        _emit_export_marker("BEAMO_WIPE_EXPORT_READBACK_VERIFIED")
        if not _ordinary_unmount(mountpoint, volume):
            mounted = _mounted_exact(mountpoint, volume)
            raise SafetyError("The verified report USB could not be unmounted.")
        mounted = False
        if _mount_record(mountpoint) is not None:
            raise SafetyError("The report USB is still mounted.")
        _emit_export_marker("BEAMO_WIPE_EXPORT_RO_UNMOUNTED")
        return ExportReceipt(
            ok=True,
            safe_to_remove=True,
            code="saved_verified_unmounted",
            evidence_sha256=evidence.sha256,
            session_name=session_name,
            log_status=log_status,
        )
    finally:
        if mountpoint is not None and mounted:
            _ordinary_unmount(mountpoint, volume)
        if lock_fd >= 0:
            os.close(lock_fd)
        if mountpoint is not None:
            try:
                mountpoint.rmdir()
            except OSError:
                pass


def _worker() -> ExportReceipt:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    evidence, expected, baseline, protected, log_data, log_status = _decode_worker_request(raw)
    _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_DECODED")
    fresh_payload1 = run_lsblk()
    fresh1 = select_export_volume(fresh_payload1, baseline)
    fresh_payload2 = run_lsblk()
    fresh2 = select_export_volume(fresh_payload2, baseline)
    if not _same_volume(fresh1, fresh2, include_rdev=False) or not _same_volume(
        fresh2, expected, include_rdev=False
    ):
        raise SafetyError("The report USB changed before mounting.")
    _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_SELECTED")

    for original in baseline:
        if not original.required:
            continue
        if original.rdev <= 0 or _block_rdev(original.path) != original.rdev:
            raise SafetyError("A connected disk identity changed before export.")
    fresh_protected = _protected_rdevs(fresh_payload2, baseline)
    if fresh_protected != protected:
        raise SafetyError("A protected disk identity changed before export.")
    volume = _volume_with_rdev(fresh2)
    if volume.rdev in protected or volume.parent.rdev in protected:
        raise SafetyError("The report USB aliases a connected protected disk.")
    if not _same_volume(volume, expected, include_rdev=True):
        raise SafetyError("The report USB block identity changed.")
    _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_IDENTIFIED")
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    parent_fd = os.open(volume.parent.path, flags)
    volume_fd = -1
    try:
        volume_fd = os.open(volume.path, flags)
        if os.fstat(parent_fd).st_rdev != volume.parent.rdev or os.fstat(volume_fd).st_rdev != volume.rdev:
            raise SafetyError("The report USB identity changed while opening it.")
        _assert_partition_parent(volume)
        _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_OPENED")
        return _persist_and_verify_report(
            volume, evidence, log_data, log_status, volume_fd
        )
    finally:
        if volume_fd >= 0:
            os.close(volume_fd)
        os.close(parent_fd)


def worker_main() -> int:
    try:
        receipt = _worker()
    except Exception as exc:  # noqa: BLE001 - worker must return one bounded failure receipt
        _emit_export_failure(exc)
        _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_FAILED")
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("report_export", "worker_failed", type(exc).__name__)
        except Exception:
            pass
        receipt = ExportReceipt(False, False, "export_failed")
    sys.stdout.write(json.dumps(asdict(receipt), separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit(2)
    raise SystemExit(worker_main())
