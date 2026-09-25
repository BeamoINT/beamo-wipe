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
from typing import TypeGuard, Any, Callable, Iterable, Mapping, Optional, Sequence

from beamo_wipe.discover import run_lsblk
from beamo_wipe.evidence import _verified_evidence_bytes
from beamo_wipe.models import Disk, DiscoveryResult
from beamo_wipe.nwipe_runner import NWIPE_COMPLETION_LOG_BYTES, NWIPE_PROGRESS_LOG_BYTES
from beamo_wipe.safety import (
    CLEAN_SUBPROCESS_ENV,
    SafetyError,
    canonical_wwn,
    meaningful_serial,
    meaningful_wwn,
)


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
REPORT_FOLDER_RE = re.compile(r"^BEAMO-WIPE-REPORTS/report-[0-9a-f]{24}$")
USB_META_INCOMPLETE = "The report USB metadata is incomplete."
USB_META_MALFORMED = "The report USB metadata is malformed."
USB_SIZE_INVALID = "The report USB size is invalid."
USB_MOUNT_META_INCOMPLETE = "The report USB mount metadata is incomplete."
USB_MOUNT_META_MALFORMED = "The report USB mount metadata is malformed."
USB_DEVICE_PATH_UNSUPPORTED = "The report USB device path is unsupported."
DISCOVERY_MALFORMED = "Disk discovery returned malformed data."
DISCOVERY_DUPLICATES = "Disk discovery returned duplicate devices."
BASELINE_KEEP_CONNECTED = "Leave the Beamo USB and selected disk connected, then try again."
NEW_NOT_REMOVABLE = "The new device is not identified as a removable USB."
USB_NONE_FOUND = "No new report USB found."
USB_MANY_FOUND = "More than one new report USB found."
USB_MUST_BE_WRITABLE = "The report USB must be writable and not already mounted."
USB_LAYOUT_MALFORMED = "The report USB layout is malformed."
USB_LAYOUT_AMBIGUOUS = "The report USB layout is ambiguous."
USB_NEED_ONE_VOLUME = "The report USB must contain exactly one FAT32 volume."
USB_LAYOUT_UNSUPPORTED = "The report USB layout is unsupported."
USB_PARTITION_ORPHAN = "The report USB partition does not belong to its parent disk."
USB_VOLUME_PATH_UNSUPPORTED = "The report USB volume path is unsupported."
USB_VOLUME_WRITABLE = "The report USB volume must be writable and unmounted."
USB_VOLUME_SMALL = "The report USB volume is too small."
USB_FAT32_ONLY = "Use a FAT32 report USB. Other filesystems are not mounted."
USB_FAT32_NOT_12_16 = "Use a FAT32 report USB. FAT12 and FAT16 are not accepted."
EVIDENCE_MALFORMED = "The saved wipe evidence is malformed."
EVIDENCE_SCHEMA = "The saved wipe evidence has an unsupported schema."
EVIDENCE_NOT_FINISHED = "Only a finished wipe report can be exported."
EVIDENCE_NO_IDENTITY = "The saved wipe evidence is missing its disk identity."
EVIDENCE_WRONG_DISK = "The saved wipe evidence is for a different disk."
EVIDENCE_PROVENANCE = "The saved wipe evidence provenance does not match."
EVIDENCE_LOG_META = "The saved wipe evidence has malformed log metadata."
USB_GONE = "The report USB disappeared before it could be opened."
USB_NOT_BLOCK = "The report USB path is not a block device."
PROTECTED_LAYOUT_BAD = "A protected disk layout is malformed or ambiguous."
PROTECTED_IDENTITY_UNVERIFIED = "A protected disk identity could not be verified."
REPORT_CHANGED_BEFORE_EXPORT = "The finished wipe report changed before export."
BASELINE_PREPARE_FIRST = "Prepare a protected disk baseline before inserting the report USB."
BOOT_IDENTITY_UNAVAILABLE = "Boot identity unavailable."
NO_BASELINE = "No bounded baseline available."
BOOT_ABSENT_BASELINE = "Boot identity is absent from the baseline."
UNSTABLE_BASELINE = "Unstable baseline."
CANNOT_VERIFY_BOOT = "Cannot verify the boot USB and connected disks. Diagnostic export is blocked. Leave existing disks connected and try Prepare again."
DISK_CHANGED_PREPARE = "A connected disk changed. Remove the report USB and Prepare again."
USB_CHANGED_DISCOVERY = "The report USB changed during discovery. Try again."
DISK_IDENTITY_CHANGED = "A connected disk identity changed before export."
USB_IS_PROTECTED = "The report USB is the boot device or selected disk."
EXPORT_TIMEOUT = "Saving the report timed out. Shut down before removing the USB."
HELPER_NO_START = "The isolated report helper could not start."
HELPER_FAILED = "The isolated report helper failed. Shut down before removing the USB."
HELPER_BAD_RECEIPT = "The isolated report helper returned an invalid receipt."
RECEIPT_INVALID = "The exported report success receipt is invalid."
RECEIPT_FAILURE_INVALID = "The exported report returned an invalid receipt for failure."
REPORT_FILENAME_INVALID = "Invalid report filename."
REPORT_UNSAFE_FILE = "The exported report contains an unsafe file."
REPORT_TOO_BIG = "The exported report exceeded its size limit."
DIAG_NO_RAW_LOGS = "Diagnostic reports cannot include raw logs."
SESSION_NAME_INVALID = "Invalid report session name."
REPORT_DIR_ALLOC = "Could not allocate a unique report directory."
RECEIPT_DIR_INVALID = "The report receipt contains an invalid directory name."
REPORT_FILES_CHANGED = "The exported report file set changed."
REPORT_READBACK_FAILED = "The exported report did not pass read-back verification."
MOUNT_UNVERIFIED = "Could not verify the report USB mount."
MOUNTPOINT_AMBIGUOUS = "The report mountpoint is ambiguous."
USB_NOT_MOUNTED = "The report USB was not mounted."
MOUNT_IDENTITY_MISMATCH = "The report mount identity does not match the selected USB."
MOUNT_IDENTITY_UNCHECKED = "The report mount identity could not be checked."
MOUNT_SOURCE_CHANGED = "The report mount source changed."
MOUNT_MISSING_OPTIONS = "The report USB mount is missing required safety options."
REQUEST_SIZE_INVALID = "Invalid report request size."
REQUEST_MALFORMED = "Malformed report request."
REQUEST_CHECKSUM = "Report request checksum mismatch."
LOG_STATUS_MALFORMED = "Malformed report log status."
LOG_PAYLOAD_MALFORMED = "Malformed report log payload."
USB_BLOCK_CHANGED = "The report USB block identity changed."
USB_PARTITION_INVALID = "The report USB partition relationship is invalid."
USB_PARTITION_UNVERIFIED = "The report USB partition relationship could not be verified."
EXPORT_RUNNING = "Another report export is already running."
USB_MOUNT_FAILED = "The report USB could not be mounted safely."
USB_SYNC_FAILED = "The report USB could not be synchronized."
USB_UNMOUNT_FAILED = "The report USB could not be unmounted."
USB_REMOUNT_FAILED = "The report USB could not be remounted for verification."
USB_VERIFIED_UNMOUNT_FAILED = "The verified report USB could not be unmounted."
USB_STILL_MOUNTED = "The report USB is still mounted."
USB_CHANGED_BEFORE_MOUNT = "The report USB changed before mounting."
PROTECTED_CHANGED = "A protected disk identity changed before export."
USB_ALIASES_PROTECTED = "The report USB aliases a connected protected disk."
USB_IDENTITY_CHANGED_OPEN = "The report USB identity changed while opening it."
USB_NOT_SINGLE = "{detail} Insert exactly one new FAT32 report USB, then try again."

NEXT_REPLUG = "Unplug only the report USB, plug it back in, then try again."
NEXT_DIFFERENT_STICK = (
    "Use a different USB stick with one FAT32 volume. "
    "This USB cannot format or repair report media."
)
NEXT_TRY_SUPPORT = (
    "Try again. If it fails again, note the exact message and contact support."
)
NEXT_SUPPORT = "Note the exact message above and contact support."
NEXT_SHUTDOWN_RETRY = "Try again. If it fails again, shut down before removing the USB."
NEXT_SORT_WHILE_OFF = "Shut down first, then sort the USB sticks while the computer is off."
NEXT_WAIT_OTHER = "Wait for the other export to finish, then try again."

# Next safe step per refusal detail. Details that already carry their own
# instruction map to "". Unknown details map to "" (generic retry applies).
def _build_next_steps() -> dict[str, str]:
    return {
        USB_NOT_SINGLE.format(detail=USB_NONE_FOUND): "",
        USB_NOT_SINGLE.format(detail=USB_MANY_FOUND): "",
        BASELINE_KEEP_CONNECTED: "",
        DISK_CHANGED_PREPARE: "",
        BASELINE_PREPARE_FIRST: "",
        CANNOT_VERIFY_BOOT: "",
        USB_CHANGED_DISCOVERY: "",
        EXPORT_TIMEOUT: "",
        HELPER_FAILED: "",
        NEW_NOT_REMOVABLE: NEXT_DIFFERENT_STICK,
        USB_NEED_ONE_VOLUME: NEXT_DIFFERENT_STICK,
        USB_FAT32_ONLY: NEXT_DIFFERENT_STICK,
        USB_FAT32_NOT_12_16: NEXT_DIFFERENT_STICK,
        USB_VOLUME_SMALL: NEXT_DIFFERENT_STICK,
        USB_LAYOUT_MALFORMED: NEXT_DIFFERENT_STICK,
        USB_LAYOUT_AMBIGUOUS: NEXT_DIFFERENT_STICK,
        USB_LAYOUT_UNSUPPORTED: NEXT_DIFFERENT_STICK,
        USB_PARTITION_ORPHAN: NEXT_DIFFERENT_STICK,
        USB_PARTITION_INVALID: NEXT_DIFFERENT_STICK,
        USB_PARTITION_UNVERIFIED: NEXT_DIFFERENT_STICK,
        USB_DEVICE_PATH_UNSUPPORTED: NEXT_DIFFERENT_STICK,
        USB_VOLUME_PATH_UNSUPPORTED: NEXT_DIFFERENT_STICK,
        USB_NOT_BLOCK: NEXT_DIFFERENT_STICK,
        USB_MUST_BE_WRITABLE: NEXT_REPLUG,
        USB_VOLUME_WRITABLE: NEXT_REPLUG,
        USB_NOT_MOUNTED: NEXT_REPLUG,
        USB_MOUNT_FAILED: NEXT_REPLUG,
        USB_GONE: NEXT_REPLUG,
        USB_CHANGED_BEFORE_MOUNT: NEXT_REPLUG,
        USB_BLOCK_CHANGED: NEXT_REPLUG,
        USB_IDENTITY_CHANGED_OPEN: NEXT_REPLUG,
        MOUNT_SOURCE_CHANGED: NEXT_REPLUG,
        MOUNT_IDENTITY_MISMATCH: NEXT_REPLUG,
        MOUNT_IDENTITY_UNCHECKED: NEXT_REPLUG,
        MOUNTPOINT_AMBIGUOUS: NEXT_REPLUG,
        MOUNT_MISSING_OPTIONS: NEXT_REPLUG,
        MOUNT_UNVERIFIED: NEXT_REPLUG,
        USB_SYNC_FAILED: NEXT_SHUTDOWN_RETRY,
        USB_UNMOUNT_FAILED: NEXT_SHUTDOWN_RETRY,
        USB_REMOUNT_FAILED: NEXT_SHUTDOWN_RETRY,
        USB_VERIFIED_UNMOUNT_FAILED: NEXT_SHUTDOWN_RETRY,
        USB_STILL_MOUNTED: NEXT_SHUTDOWN_RETRY,
        USB_IS_PROTECTED: NEXT_SORT_WHILE_OFF,
        USB_ALIASES_PROTECTED: NEXT_SORT_WHILE_OFF,
        DISK_IDENTITY_CHANGED: NEXT_SORT_WHILE_OFF,
        PROTECTED_CHANGED: NEXT_SORT_WHILE_OFF,
        PROTECTED_LAYOUT_BAD: NEXT_SORT_WHILE_OFF,
        PROTECTED_IDENTITY_UNVERIFIED: NEXT_SORT_WHILE_OFF,
        USB_META_INCOMPLETE: NEXT_TRY_SUPPORT,
        USB_META_MALFORMED: NEXT_TRY_SUPPORT,
        USB_SIZE_INVALID: NEXT_TRY_SUPPORT,
        USB_MOUNT_META_INCOMPLETE: NEXT_TRY_SUPPORT,
        USB_MOUNT_META_MALFORMED: NEXT_TRY_SUPPORT,
        DISCOVERY_MALFORMED: NEXT_TRY_SUPPORT,
        DISCOVERY_DUPLICATES: NEXT_TRY_SUPPORT,
        REPORT_CHANGED_BEFORE_EXPORT: NEXT_TRY_SUPPORT,
        HELPER_NO_START: NEXT_TRY_SUPPORT,
        HELPER_BAD_RECEIPT: NEXT_TRY_SUPPORT,
        RECEIPT_INVALID: NEXT_TRY_SUPPORT,
        RECEIPT_FAILURE_INVALID: NEXT_TRY_SUPPORT,
        REQUEST_SIZE_INVALID: NEXT_TRY_SUPPORT,
        REQUEST_MALFORMED: NEXT_TRY_SUPPORT,
        REQUEST_CHECKSUM: NEXT_TRY_SUPPORT,
        LOG_STATUS_MALFORMED: NEXT_TRY_SUPPORT,
        LOG_PAYLOAD_MALFORMED: NEXT_TRY_SUPPORT,
        REPORT_FILENAME_INVALID: NEXT_TRY_SUPPORT,
        REPORT_UNSAFE_FILE: NEXT_TRY_SUPPORT,
        SESSION_NAME_INVALID: NEXT_TRY_SUPPORT,
        REPORT_DIR_ALLOC: NEXT_TRY_SUPPORT,
        RECEIPT_DIR_INVALID: NEXT_TRY_SUPPORT,
        REPORT_FILES_CHANGED: NEXT_TRY_SUPPORT,
        REPORT_READBACK_FAILED: NEXT_TRY_SUPPORT,
        BOOT_IDENTITY_UNAVAILABLE: NEXT_TRY_SUPPORT,
        NO_BASELINE: NEXT_TRY_SUPPORT,
        BOOT_ABSENT_BASELINE: NEXT_TRY_SUPPORT,
        UNSTABLE_BASELINE: NEXT_TRY_SUPPORT,
        EVIDENCE_MALFORMED: NEXT_SUPPORT,
        EVIDENCE_SCHEMA: NEXT_SUPPORT,
        EVIDENCE_NOT_FINISHED: NEXT_SUPPORT,
        EVIDENCE_NO_IDENTITY: NEXT_SUPPORT,
        EVIDENCE_WRONG_DISK: NEXT_SUPPORT,
        EVIDENCE_PROVENANCE: NEXT_SUPPORT,
        EVIDENCE_LOG_META: NEXT_SUPPORT,
        REPORT_TOO_BIG: NEXT_SUPPORT,
        DIAG_NO_RAW_LOGS: NEXT_SUPPORT,
        EXPORT_RUNNING: NEXT_WAIT_OTHER,
    }


EXPORT_NEXT_STEPS = _build_next_steps()
def next_step_for(detail: str) -> str:
    """Next safe step for a refusal detail, or "" when the detail already
    carries its own instruction or is not a known refusal."""
    return EXPORT_NEXT_STEPS.get(detail, "")


def next_step_needs_support(detail: str) -> bool:
    """True when the mapped step refers the owner to support."""
    return next_step_for(detail) in (NEXT_SUPPORT, NEXT_TRY_SUPPORT)


TRUNCATED_SUFFIX = " (truncated)"
RECEIPT_DIAG_LEAD = "Diagnostic report saved and verified on {label}. The report USB is safe to remove. This is not erase evidence."
RECEIPT_WIPE_LEAD = "Report saved and verified on {label}. The report USB is safe to remove. Saving this report does not confirm erase success."
RECEIPT_FOLDER = "Folder: {folder}"
RECEIPT_ORIGINAL = "{file} is the original report."
RECEIPT_SHARE = (
    "SHARE.json is a privacy-reduced sharing copy. "
    "It omits serials, hardware IDs, device paths, and engine logs. "
    "It is not identity evidence. SHARE.txt is its summary. "
    "The original report is kept. To share, copy only SHARE.json and SHARE.txt."
)
README_TITLE = "Beamo Wipe report"
README_ORIGINAL = "result.json, RESULT.txt, and REPORT.html are the original report. They include disk identifiers."
README_SHARE = (
    "SHARE.json and SHARE.txt are a privacy-reduced sharing copy. "
    "They omit serials, hardware IDs, device paths, and engine logs. "
    "They are not identity evidence."
)
README_SHARE_HOW = "To share, copy only SHARE.json and SHARE.txt. Do not share result.json, RESULT.txt, REPORT.html, or engine logs."
README_SIMPLE = "RESULT.txt is the owner result summary. REPORT.html is the same summary as a readable page. result.json records the wipe outcome and disk identifiers."
README_LOG = "nwipe log: {status} (original report only)."
README_LOG_SIMPLE = "nwipe log: {status}."
README_COMPLETE = "COMPLETE authenticates these file contents only. It does not claim that the USB is safe to remove."
README_SUPPORT = "Support: beamosupport.com."
README_CHECK = "Check {ident}: {status}. {summary}"
README_DIAG_TIME = "Calendar time is unverified. COMPLETE authenticates contents only; it does not mean safe to remove."

GENERIC_DESTINATION = "the report USB"
DESTINATION_MAX = 64
OWNER_WIPE_FILE = "RESULT.txt"
OWNER_DIAGNOSTIC_FILE = "diagnostic.json"
OWNER_FILES = frozenset({OWNER_WIPE_FILE, OWNER_DIAGNOSTIC_FILE})
LOG_COMPLETE = "Engine log: complete."
LOG_TAIL = "Engine log: only a final tail."
LOG_UNAVAILABLE = "Engine log: unavailable."


def _build_log_status_lines() -> dict[str, str]:
    return {
        "complete": LOG_COMPLETE,
        "tail": LOG_TAIL,
        "unavailable": LOG_UNAVAILABLE,
    }


LOG_STATUS_LINES = _build_log_status_lines()


def _apply_language() -> None:
    global LOG_STATUS_LINES, EXPORT_NEXT_STEPS
    LOG_STATUS_LINES = _build_log_status_lines()
    EXPORT_NEXT_STEPS = _build_next_steps()
RECEIPT_KEYS = frozenset(
    {
        "ok",
        "safe_to_remove",
        "code",
        "evidence_sha256",
        "session_name",
        "log_status",
        "destination_label",
        "report_folder",
        "share_copy",
        "owner_file",
    }
)


def _emit_export_marker(marker: str) -> None:
    """Best-effort, identifier-free progress for isolated QEMU diagnostics."""
    try:
        from beamo_wipe.diagnostics import emit_serial_marker

        emit_serial_marker(marker)
    except Exception:
        pass


def _marker_for(detail: str) -> str:
    """Map a failure message to one fixed marker without exporting metadata.

    Explicit constants first, so translated messages map identically in
    every language; the English substring chain stays as a fallback for
    messages raised outside this module. Explicit groups preserve the
    legacy chain order ("mounted" precedes "FAT", "exactly one" precedes
    "FAT", "path" is layout).
    """
    if detail == USB_DEVICE_PATH_UNSUPPORTED:
        return "BEAMO_WIPE_EXPORT_FAIL_DEVICE_PATH"
    if detail == USB_LAYOUT_MALFORMED:
        return "BEAMO_WIPE_EXPORT_FAIL_CHILDREN"
    if detail == USB_LAYOUT_AMBIGUOUS:
        return "BEAMO_WIPE_EXPORT_FAIL_AMBIGUOUS"
    if detail == USB_LAYOUT_UNSUPPORTED:
        return "BEAMO_WIPE_EXPORT_FAIL_UNSUPPORTED_LAYOUT"
    if detail == USB_PARTITION_ORPHAN:
        return "BEAMO_WIPE_EXPORT_FAIL_PARENT_LINK"
    if detail == USB_VOLUME_PATH_UNSUPPORTED:
        return "BEAMO_WIPE_EXPORT_FAIL_VOLUME_PATH"
    if detail in (
        USB_META_INCOMPLETE,
        USB_META_MALFORMED,
        USB_MOUNT_META_INCOMPLETE,
        USB_MOUNT_META_MALFORMED,
        DISCOVERY_MALFORMED,
        EVIDENCE_LOG_META,
    ):
        return "BEAMO_WIPE_EXPORT_FAIL_METADATA"
    if detail == BASELINE_KEEP_CONNECTED:
        return "BEAMO_WIPE_EXPORT_FAIL_BASELINE"
    if detail == NEW_NOT_REMOVABLE:
        return "BEAMO_WIPE_EXPORT_FAIL_REMOVABLE"
    if detail in (
        USB_NOT_SINGLE.format(detail=USB_NONE_FOUND),
        USB_NOT_SINGLE.format(detail=USB_MANY_FOUND),
        USB_NEED_ONE_VOLUME,
    ):
        return "BEAMO_WIPE_EXPORT_FAIL_COUNT"
    if detail in (
        USB_MUST_BE_WRITABLE,
        USB_VOLUME_WRITABLE,
        USB_NOT_MOUNTED,
        USB_REMOUNT_FAILED,
        USB_VERIFIED_UNMOUNT_FAILED,
        USB_STILL_MOUNTED,
        USB_MOUNT_FAILED,
        USB_UNMOUNT_FAILED,
        USB_FAT32_ONLY,
    ):
        return "BEAMO_WIPE_EXPORT_FAIL_MOUNTED"
    if detail in (
        PROTECTED_LAYOUT_BAD,
        USB_PARTITION_INVALID,
        USB_PARTITION_UNVERIFIED,
        USB_NOT_BLOCK,
    ):
        return "BEAMO_WIPE_EXPORT_FAIL_LAYOUT"
    if detail in (USB_SIZE_INVALID, USB_VOLUME_SMALL, REQUEST_SIZE_INVALID, REPORT_TOO_BIG):
        return "BEAMO_WIPE_EXPORT_FAIL_SIZE"
    if detail in (USB_FAT32_NOT_12_16,):
        return "BEAMO_WIPE_EXPORT_FAIL_FAT32"
    if "metadata" in detail or "malformed data" in detail:
        return "BEAMO_WIPE_EXPORT_FAIL_METADATA"
    if detail.startswith("Leave the Beamo USB"):
        return "BEAMO_WIPE_EXPORT_FAIL_BASELINE"
    if "removable USB" in detail:
        return "BEAMO_WIPE_EXPORT_FAIL_REMOVABLE"
    if "exactly one" in detail:
        return "BEAMO_WIPE_EXPORT_FAIL_COUNT"
    if "mounted" in detail or "unmounted" in detail:
        return "BEAMO_WIPE_EXPORT_FAIL_MOUNTED"
    if "layout" in detail or "partition" in detail or "path" in detail:
        return "BEAMO_WIPE_EXPORT_FAIL_LAYOUT"
    if "small" in detail or "size" in detail:
        return "BEAMO_WIPE_EXPORT_FAIL_SIZE"
    if "FAT" in detail or "filesystem" in detail:
        return "BEAMO_WIPE_EXPORT_FAIL_FAT32"
    return "BEAMO_WIPE_EXPORT_FAIL_OTHER"


def _emit_export_failure(exc: Exception) -> None:
    """Map a failure message to one fixed marker without exporting metadata."""
    detail = str(exc)
    _emit_export_marker(_marker_for(detail))
    try:
        from beamo_wipe.support_code import code_for_export_detail, record_identity, SupportIdentity, public_build_id

        ident = SupportIdentity(
            code=code_for_export_detail(detail),
            build_id=public_build_id(),
        )
        record_identity(ident)
    except Exception:
        pass


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
    destination_label: str = ""
    report_folder: str = ""
    share_copy: bool = False
    owner_file: str = ""


def _is_diagnostic_evidence(data: bytes) -> bool:
    try:
        return json.loads(data).get("report_type") == "startup_diagnostic"
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
        return False


def _has_display_line_break(value: str) -> bool:
    # These Unicode separators split lines in terminals and text renderers,
    # but are not covered by checks for ASCII CR and LF.
    return any(ch == "\x85" or unicodedata.category(ch) in {"Zl", "Zp"} for ch in value)


def destination_label_for(model: str, size_bytes: int) -> str:
    """Safe USB identity for owners. Never a mount, device, or relative path."""
    cleaned = (model or "").strip()
    unsafe = (
        not cleaned
        or "/" in cleaned
        or "\\" in cleaned
        or cleaned.startswith(".")
        or cleaned.lower().startswith("dev/")
        or _has_display_line_break(cleaned)
    )
    if unsafe:
        name = GENERIC_DESTINATION
    else:
        name = cleaned
        if len(name) > DESTINATION_MAX:
            name = name[:DESTINATION_MAX].rstrip() + TRUNCATED_SUFFIX
        if not SAFE_ID_RE.fullmatch(name):
            name = GENERIC_DESTINATION
    from beamo_wipe.discover import size_gb_label

    if type(size_bytes) is not int or isinstance(size_bytes, bool) or size_bytes <= 0:
        return name
    size = size_gb_label(size_bytes)
    if not size or size == "0":
        return name
    return f"{name}, {size} GB"


def report_folder_for(session_name: str) -> str:
    if not SESSION_RE.fullmatch(session_name):
        return ""
    return f"{REPORTS_DIR}/{session_name}"


def _destination_label_ok(label: str) -> bool:
    if (
        not isinstance(label, str)
        or not label
        or len(label) > DESTINATION_MAX + 24
        or "/" in label
        or "\\" in label
        or "\n" in label
        or "\r" in label
        or _has_display_line_break(label)
        or label.startswith(".")
        or label.lower().startswith("dev/")
        or not SAFE_ID_RE.fullmatch(label)
    ):
        return False
    return True


def build_success_receipt(
    *,
    evidence_sha256: str,
    session_name: str,
    log_status: str,
    volume: ExportVolume,
    privacy_reduced: bool,
    diagnostic: bool,
) -> ExportReceipt:
    folder = report_folder_for(session_name)
    owner_file = OWNER_DIAGNOSTIC_FILE if diagnostic else OWNER_WIPE_FILE
    share_copy = bool(privacy_reduced) and not diagnostic
    return ExportReceipt(
        ok=True,
        safe_to_remove=True,
        code="saved_verified_unmounted",
        evidence_sha256=evidence_sha256,
        session_name=session_name,
        log_status=log_status,
        destination_label=destination_label_for(
            volume.parent.model, volume.parent.size_bytes
        ),
        report_folder=folder,
        share_copy=share_copy,
        owner_file=owner_file,
    )


def receipt_is_saved(
    receipt: object,
    *,
    expected_sha256: str,
    owner_file: str = OWNER_WIPE_FILE,
    share_copy: bool | None = None,
) -> TypeGuard[ExportReceipt]:
    """True only for a structurally valid, verified, unmounted success receipt."""
    if not isinstance(receipt, ExportReceipt):
        return False
    if share_copy is not None and receipt.share_copy is not bool(share_copy):
        return False
    return (
        receipt.ok is True
        and receipt.safe_to_remove is True
        and receipt.code == "saved_verified_unmounted"
        and receipt.evidence_sha256 == expected_sha256
        and SESSION_RE.fullmatch(receipt.session_name) is not None
        and receipt.log_status in LOG_STATUS_LINES
        and receipt.report_folder == report_folder_for(receipt.session_name)
        and REPORT_FOLDER_RE.fullmatch(receipt.report_folder) is not None
        and receipt.owner_file == owner_file
        and receipt.owner_file in OWNER_FILES
        and type(receipt.share_copy) is bool
        and not (receipt.share_copy and receipt.owner_file != OWNER_WIPE_FILE)
        and _destination_label_ok(receipt.destination_label)
    )


def present_export_receipt(receipt: ExportReceipt) -> str:
    """Owner-facing success copy. Call only after receipt_is_saved()."""
    log_line = LOG_STATUS_LINES[receipt.log_status]
    if receipt.owner_file == OWNER_DIAGNOSTIC_FILE:
        lead = RECEIPT_DIAG_LEAD.format(label=receipt.destination_label)
    else:
        lead = RECEIPT_WIPE_LEAD.format(label=receipt.destination_label)
    lines = [
        lead,
        RECEIPT_FOLDER.format(folder=receipt.report_folder),
        RECEIPT_ORIGINAL.format(file=receipt.owner_file),
    ]
    if receipt.share_copy:
        lines.append(RECEIPT_SHARE)
    lines.append(log_line)
    return "\n".join(lines)


def _strict_text(node: Mapping[str, Any], key: str, *, required: bool = False) -> str:
    value = node.get(key)
    if value is None:
        if required:
            raise SafetyError(USB_META_INCOMPLETE)
        return ""
    if (
        not isinstance(value, str)
        or (value and not SAFE_ID_RE.fullmatch(value))
        or any(unicodedata.category(ch).startswith("C") for ch in value)
    ):
        raise SafetyError(USB_META_MALFORMED)
    text = value.strip()
    if text != value or (required and not text):
        raise SafetyError(USB_META_MALFORMED)
    return text


def _strict_int(node: Mapping[str, Any], key: str) -> int:
    value = node.get(key)
    if isinstance(value, bool):
        raise SafetyError(USB_META_MALFORMED)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        # Linux block sizes are unsigned 64-bit values. Reject impossible
        # decimal strings before converting arbitrarily large lsblk input.
        if len(value) > 20:
            raise SafetyError(USB_SIZE_INVALID)
        parsed = int(value)
    else:
        raise SafetyError(USB_META_INCOMPLETE)
    if not 0 < parsed <= (1 << 64) - 1:
        raise SafetyError(USB_SIZE_INVALID)
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
    raise SafetyError(USB_META_INCOMPLETE)


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = node.get("children", [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(child, dict) for child in value):
        raise SafetyError(USB_LAYOUT_MALFORMED)
    return value


def _unmounted(node: Mapping[str, Any]) -> bool:
    if "mountpoints" not in node or "mountpoint" not in node:
        raise SafetyError(USB_MOUNT_META_INCOMPLETE)
    mountpoints = node.get("mountpoints")
    if not isinstance(mountpoints, list):
        raise SafetyError(USB_MOUNT_META_MALFORMED)
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
        raise SafetyError(USB_DEVICE_PATH_UNSUPPORTED)
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
    left_wwn, right_wwn = canonical_wwn(left.wwn), canonical_wwn(right.wwn)
    if left_wwn and right_wwn:
        # Reused serials cannot make two distinct hardware IDs into one
        # baseline disk. Linux can also reuse the same /dev path after a
        # device swap. Otherwise a newly inserted USB can vanish from the
        # exactly-one-report-volume check.
        return left_wwn == right_wwn
    left_serial = meaningful_serial(left.serial).casefold()
    right_serial = meaningful_serial(right.serial).casefold()
    if left_serial and right_serial and left_serial != right_serial:
        # A kernel path can be reused after unplugging a baseline USB.
        return False
    if left.path == right.path:
        return True
    return bool(
        left_serial
        and right_serial
        and left_serial == right_serial
        and left.size_bytes == right.size_bytes
        and left.model.casefold() == right.model.casefold()
    )


def _blank_identity(item: DeviceFingerprint) -> bool:
    return not meaningful_serial(item.serial) and not meaningful_wwn(item.wwn)


def _refuse_ambiguous_blank_disks(
    roots: Sequence[Mapping[str, Any]], baseline: Sequence[DeviceFingerprint]
) -> None:
    """Refuse when a blank disk could be a relocated boot stick or target.

    A disk with no serial and no WWN is only recognizable by its path. After
    the kernel renames devices, that path can belong to a different disk, and
    the original disk looks newly inserted. A same-size replacement that grew
    a serial, WWN, or model is not proof the original disk stayed put. Two
    blank disks that share size and model are not separable. A report stick
    with a different size, model, serial, or WWN is still a new disk when
    the blank disk at the original path is unchanged.
    """
    current = [_fingerprint_node(node) for node in roots]
    for old in baseline:
        if not _blank_identity(old):
            continue
        at_path = [
            item
            for item in current
            if item.path == old.path and item.size_bytes == old.size_bytes
        ]
        if len(at_path) == 1:
            item = at_path[0]
            if not _blank_identity(item) or (
                (item.model or "").casefold() != (old.model or "").casefold()
            ):
                raise SafetyError(PROTECTED_IDENTITY_UNVERIFIED)
        for item in current:
            if item.path == old.path or not _blank_identity(item):
                continue
            if item.size_bytes != old.size_bytes:
                continue
            if (item.model or "").casefold() != (old.model or "").casefold():
                continue
            raise SafetyError(PROTECTED_IDENTITY_UNVERIFIED)


def _refuse_duplicate_wwns(roots: Sequence[Mapping[str, Any]]) -> None:
    """Two disks with one WWN are not separable, even when the sizes differ."""
    seen: set[str] = set()
    for node in roots:
        wwn = canonical_wwn(_fingerprint_node(node).wwn)
        if not wwn:
            continue
        if wwn in seen:
            raise SafetyError(PROTECTED_IDENTITY_UNVERIFIED)
        seen.add(wwn)


def _refuse_ambiguous_serials(roots: Sequence[Mapping[str, Any]]) -> None:
    """A shared serial without two distinct WWNs cannot identify one USB."""
    seen: dict[str, list[str]] = {}
    for node in roots:
        item = _fingerprint_node(node)
        serial = meaningful_serial(item.serial).casefold()
        if not serial:
            continue
        wwn = canonical_wwn(item.wwn)
        if any(not wwn or not earlier or wwn == earlier for earlier in seen.get(serial, ())):
            raise SafetyError(PROTECTED_IDENTITY_UNVERIFIED)
        seen.setdefault(serial, []).append(wwn)


def _refuse_lost_optional_identity(
    roots: Sequence[Mapping[str, Any]], baseline: Sequence[DeviceFingerprint]
) -> None:
    """A same-path optional disk with lost IDs cannot be called unchanged."""
    current = {}
    for node in roots:
        item = _fingerprint_node(node)
        current[item.path] = item
    for old in baseline:
        if old.required or old.path not in current:
            continue
        item = current[old.path]
        if (
            item.size_bytes != old.size_bytes
            or item.model.casefold() != old.model.casefold()
        ):
            raise SafetyError(PROTECTED_IDENTITY_UNVERIFIED)
        old_wwn, item_wwn = canonical_wwn(old.wwn), canonical_wwn(item.wwn)
        old_serial = meaningful_serial(old.serial)
        item_serial = meaningful_serial(item.serial)
        # A different ID at the same path is not evidence that this is a
        # newly inserted stick. It may be an existing optional USB whose
        # metadata changed between Prepare and Save. Only a matching WWN can
        # make a changed or missing serial harmless.
        if (
            bool(old_wwn) != bool(item_wwn)
            or (old_wwn and old_wwn != item_wwn)
            or (
                not old_wwn
                and old_serial
                and (not item_serial or old_serial.casefold() != item_serial.casefold())
            )
        ):
            raise SafetyError(PROTECTED_IDENTITY_UNVERIFIED)


def _refuse_relocated_weak_identity(
    roots: Sequence[Mapping[str, Any]], baseline: Sequence[DeviceFingerprint]
) -> None:
    """A serial alone cannot prove a moved USB is the old, optional device."""
    current = [_fingerprint_node(node) for node in roots]
    paths = {item.path for item in current}
    for old in baseline:
        if old.required or old.path in paths:
            continue
        for item in current:
            if _same_device(item, old) and not (
                canonical_wwn(item.wwn) and canonical_wwn(old.wwn)
            ):
                raise SafetyError(PROTECTED_IDENTITY_UNVERIFIED)


def _root_disks(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise SafetyError(DISCOVERY_MALFORMED)
    devices = payload.get("blockdevices")
    if not isinstance(devices, list) or any(not isinstance(node, dict) for node in devices):
        raise SafetyError(DISCOVERY_MALFORMED)
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
            raise SafetyError(DISCOVERY_DUPLICATES)
        seen_paths.add(path)
        # An empty optical reader is exposed as a zero-size ROM by lsblk.
        # It cannot be a report destination or contain the live medium, and
        # including it makes every report export fail the positive-size check.
        # Keep mounted, populated, or malformed readers in the checked set.
        if (
            node_type == "rom"
            and re.fullmatch(r"/dev/sr[0-9]+", path)
            and (
                (type(node.get("size")) is int and node["size"] == 0)
                or (type(node.get("size")) is str and node["size"] == "0")
            )
            and not _children(node)
            and _unmounted(node)
        ):
            continue
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
            # A previously blank identity field becoming populated is still
            # a changed required-disk identity. The boot stick and erased
            # target must remain the exact devices in the baseline.
            and canonical_wwn(item.wwn) == canonical_wwn(expected.wwn)
            and item.serial == expected.serial
            and item.model == expected.model
        ]
        if len(matches) != 1:
            raise SafetyError(
                BASELINE_KEEP_CONNECTED
            )


def select_export_volume(
    payload: Mapping[str, Any], baseline: Sequence[DeviceFingerprint]
) -> ExportVolume:
    """Return exactly one new, simple, writable FAT32 USB volume."""
    roots = _root_disks(payload)
    _require_baseline_present(roots, baseline)
    _refuse_duplicate_wwns(roots)
    _refuse_ambiguous_serials(roots)
    _refuse_lost_optional_identity(roots, baseline)
    _refuse_relocated_weak_identity(roots, baseline)
    _refuse_ambiguous_blank_disks(roots, baseline)
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
            raise SafetyError(NEW_NOT_REMOVABLE)
        new_usb.append(node)
    if len(new_usb) != 1:
        detail = USB_NONE_FOUND if not new_usb else USB_MANY_FOUND
        raise SafetyError(USB_NOT_SINGLE.format(detail=detail))

    parent_node = new_usb[0]
    parent = _fingerprint_node(parent_node, export_parent=True)
    if _strict_bool(parent_node, "ro") or not _unmounted(parent_node):
        raise SafetyError(USB_MUST_BE_WRITABLE)
    children = _children(parent_node)
    parent_fstype = _strict_text(parent_node, "fstype")
    if parent_fstype:
        if children:
            raise SafetyError(USB_LAYOUT_AMBIGUOUS)
        volume_node = parent_node
    else:
        if len(children) != 1:
            raise SafetyError(USB_NEED_ONE_VOLUME)
        volume_node = children[0]
        if _strict_text(volume_node, "type", required=True) != "part" or _children(volume_node):
            raise SafetyError(USB_LAYOUT_UNSUPPORTED)
        if (
            _strict_text(volume_node, "pkname", required=True)
            != os.path.basename(parent.path)
        ):
            raise SafetyError(USB_PARTITION_ORPHAN)

    volume_path = _strict_text(volume_node, "path", required=True)
    if not DEVICE_PATH_RE.fullmatch(volume_path):
        raise SafetyError(USB_VOLUME_PATH_UNSUPPORTED)
    if volume_node is not parent_node and not re.fullmatch(
        re.escape(parent.path) + r"[0-9]+", volume_path
    ):
        raise SafetyError(USB_PARTITION_ORPHAN)
    if _strict_bool(volume_node, "ro") or not _unmounted(volume_node):
        raise SafetyError(USB_VOLUME_WRITABLE)
    size_bytes = _strict_int(volume_node, "size")
    if size_bytes > parent.size_bytes:
        raise SafetyError(USB_LAYOUT_MALFORMED)
    if size_bytes < MIN_VOLUME_BYTES:
        raise SafetyError(USB_VOLUME_SMALL)
    fstype = _strict_text(volume_node, "fstype", required=True)
    if fstype not in SUPPORTED_FILESYSTEMS:
        raise SafetyError(USB_FAT32_ONLY)
    fsver = _strict_text(volume_node, "fsver", required=True)
    if fsver != "FAT32":
        raise SafetyError(USB_FAT32_NOT_12_16)
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
    from beamo_wipe.evidence import SUPPORTED_SCHEMA_VERSIONS, _unique_evidence_fields

    try:
        payload = json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_evidence_fields
        )
    except (UnicodeDecodeError, json.JSONDecodeError, SafetyError, RecursionError) as exc:
        raise SafetyError(EVIDENCE_MALFORMED) from exc

    if (
        not isinstance(payload, dict)
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise SafetyError(EVIDENCE_SCHEMA)
    outcome = payload.get("outcome")
    if not isinstance(outcome, str) or outcome not in TERMINAL_OUTCOMES:
        raise SafetyError(EVIDENCE_NOT_FINISHED)
    if outcome in {"verified", "completed"}:
        # A checksum authenticates bytes, not the claim they make. The result
        # JSON and the owner-facing report must agree before either is copied.
        from beamo_wipe.outcomes import present_evidence

        expected_code = "verified" if outcome == "verified" else "unverified"
        if present_evidence(payload).code != expected_code:
            raise SafetyError(EVIDENCE_MALFORMED)
    device = payload.get("device")
    if (
        not isinstance(device, dict)
        or not isinstance(device.get("path"), str)
        or not ROOT_PATH_RE.fullmatch(device["path"])
    ):
        raise SafetyError(EVIDENCE_NO_IDENTITY)
    try:
        matches_target = os.path.realpath(device["path"]) == os.path.realpath(target_path)
    except (OSError, ValueError) as exc:
        raise SafetyError(EVIDENCE_NO_IDENTITY) from exc
    if not matches_target:
        raise SafetyError(EVIDENCE_WRONG_DISK)
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("evidence_file") != str(path):
        raise SafetyError(EVIDENCE_PROVENANCE)
    logfile = payload.get("logfile")
    if not isinstance(logfile, str):
        raise SafetyError(EVIDENCE_LOG_META)
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
        raise SafetyError(EVIDENCE_LOG_META)
    from beamo_wipe.outcomes import present_evidence

    claim = present_evidence(payload).code
    if claim in {"occupied", "open_failed", "geometry_unusable"}:
        # These views tell the owner that nothing was erased. Unlike other
        # failures, their original negative marker must still be available.
        from beamo_wipe.nwipe_runner import completion_for_method

        snapshot, status = read_export_log(
            logfile,
            expected_sha256=log_sha256,
            expected_size_bytes=log_size_bytes,
        )
        if status not in {"complete", "tail"}:
            raise SafetyError(EVIDENCE_LOG_META)
        ok, _detail, reason = completion_for_method(
            payload["exit_evidence"]["exit_code"],
            snapshot.decode("utf-8"),
            device["path"],
            payload["method"]["id"],
        )
        if ok or reason != claim:
            raise SafetyError(EVIDENCE_LOG_META)
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
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
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
        for capture_bytes in (NWIPE_COMPLETION_LOG_BYTES, NWIPE_PROGRESS_LOG_BYTES):
            capture_tail = raw_data[-capture_bytes:]
            capture_data = capture_tail.decode("utf-8", errors="replace").encode("utf-8")
            if (len(capture_data) == expected_size_bytes
                    and hashlib.sha256(capture_data).hexdigest() == expected_sha256):
                complete = not truncated and before.st_size <= capture_bytes
                return capture_data, "complete" if complete else "tail"
        normalized = raw_data.decode("utf-8", errors="replace").encode("utf-8")
        if expected_size_bytes > len(normalized):
            return b"", "unavailable"
        data = normalized[-expected_size_bytes:]
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            return b"", "unavailable"
        complete = not truncated and expected_size_bytes == len(normalized)
        return data, "complete" if complete else "tail"
    except OSError:
        # The log is optional; failed metadata/seek/read operations must omit
        # it just like a failed open, without blocking the evidence export.
        return b"", "unavailable"
    finally:
        try:
            os.close(fd)
        except OSError:
            # A failed close also makes the optional log read untrustworthy.
            return b"", "unavailable"


def _block_rdev(path: str) -> int:
    try:
        opened = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SafetyError(USB_GONE) from exc
    if not stat.S_ISBLK(opened.st_mode) or opened.st_rdev <= 0:
        raise SafetyError(USB_NOT_BLOCK)
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
            raise SafetyError(PROTECTED_LAYOUT_BAD)
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
        raise SafetyError(PROTECTED_IDENTITY_UNVERIFIED)
    return values


def _same_volume(left: ExportVolume, right: ExportVolume, *, include_rdev: bool) -> bool:
    same_metadata = (
        left.path,
        left.size_bytes,
        left.fstype,
        left.fsver,
        left.uuid,
        left.parent.path,
        left.parent.size_bytes,
        left.parent.model,
        left.parent.serial,
        canonical_wwn(left.parent.wwn),
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
        canonical_wwn(right.parent.wwn),
    )
    if not same_metadata or not include_rdev:
        return same_metadata
    return (
        left.rdev == right.rdev
        and left.parent.rdev == right.parent.rdev
        and left.parent.required == right.parent.required
    )


def _request_dict(
    evidence: VerifiedEvidence,
    volume: ExportVolume,
    baseline: Sequence[DeviceFingerprint],
    protected_rdevs: Sequence[int],
    log_data: bytes,
    log_status: str,
    privacy_reduced: bool = False,
) -> dict[str, Any]:
    return {
        "evidence": base64.b64encode(evidence.data).decode("ascii"),
        "evidence_sha256": evidence.sha256,
        "volume": asdict(volume),
        "baseline": [asdict(item) for item in baseline],
        "protected_rdevs": list(protected_rdevs),
        "log": base64.b64encode(log_data).decode("ascii"),
        "log_status": log_status,
        "privacy_reduced": bool(privacy_reduced),
    }


def export_to_new_usb(
    *,
    evidence_path: Path,
    discovery: DiscoveryResult,
    target_path: str,
    target_rdev: int = 0,
    boot_rdev: int = 0,
    expected_evidence_sha256: str = "",
    privacy_reduced: bool = False,
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
        raise SafetyError(REPORT_CHANGED_BEFORE_EXPORT)
    required_paths = {target_path}
    if discovery.boot is not None:
        required_paths.add(discovery.boot.path)
    baseline_without_rdev = baseline_fingerprints(
        discovery.disks, required_paths=required_paths
    )
    return _export_prepared(
        evidence,
        baseline_without_rdev,
        target_rdev=target_rdev,
        boot_rdev=boot_rdev,
        expected_required_rdevs={
            os.path.realpath(path): rdev
            for path, rdev in (
                (target_path, target_rdev),
                (discovery.boot.path if discovery.boot is not None else "", boot_rdev),
            )
            if path and rdev > 0
        },
        privacy_reduced=privacy_reduced,
        scan=scan,
        run=run,
    )


def capture_diagnostic_baseline(*, scan=run_lsblk) -> tuple[DeviceFingerprint, ...]:
    """Protect all existing roots before insertion; re-establish boot identity."""
    try:
        first_payload = scan()
        from beamo_wipe.discover import discover, read_cmdline, read_mount_sources
        from beamo_wipe.safety import assert_boot_excluded
        # This payload came from a real scan, even though discover receives it
        # through its injectable argument. Supply the live boot evidence and
        # ignore preview-only environment overrides for this safety check.
        boot_scan = discover(
            lsblk_payload=first_payload,
            mount_sources=read_mount_sources(),
            cmdline=read_cmdline(),
            env={},
        )
        assert_boot_excluded(boot_scan)
        if not boot_scan.boot_identified or boot_scan.boot is None or boot_scan.error:
            raise SafetyError(BOOT_IDENTITY_UNAVAILABLE)
        roots = _root_disks(first_payload)
        if not roots or len(roots) > 256:
            raise SafetyError(NO_BASELINE)
        first = _baseline_with_rdev(tuple(sorted(
            (_fingerprint_node(node) for node in roots), key=lambda item: item.path
        )))
        if boot_scan.boot.path not in {item.path for item in first}:
            raise SafetyError(BOOT_ABSENT_BASELINE)
        _protected_rdevs(first_payload, first)
        second_payload = scan()
        second = _baseline_with_rdev(tuple(sorted(
            (_fingerprint_node(node) for node in _root_disks(second_payload)),
            key=lambda item: item.path,
        )))
        if first != second or _protected_rdevs(first_payload, first) != _protected_rdevs(second_payload, second):
            raise SafetyError(UNSTABLE_BASELINE)
        return first
    except Exception as exc:
        raise SafetyError(CANNOT_VERIFY_BOOT) from exc


def export_diagnostic_to_new_usb(*, data: bytes, baseline: Sequence[DeviceFingerprint],
                                 scan=run_lsblk, run=subprocess.run) -> ExportReceipt:
    from beamo_wipe.diagnostic_report import verified_report
    report = verified_report(data)
    if not baseline or any(not item.required or item.rdev <= 0 for item in baseline):
        raise SafetyError(BASELINE_PREPARE_FIRST)
    for item in baseline:
        if _block_rdev(item.path) != item.rdev:
            raise SafetyError(DISK_CHANGED_PREPARE)
    return _export_prepared(report, baseline, scan=scan, run=run)


def _export_prepared(evidence: VerifiedEvidence, baseline_without_rdev: Sequence[DeviceFingerprint],
                     *, target_rdev=0, boot_rdev=0,
                     expected_required_rdevs: Mapping[str, int] | None = None,
                     privacy_reduced=False, scan=run_lsblk, run=subprocess.run) -> ExportReceipt:
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
        raise SafetyError(USB_CHANGED_DISCOVERY)
    _emit_export_marker("BEAMO_WIPE_EXPORT_CONTROLLER_SELECTED")
    baseline = _baseline_with_rdev(baseline_without_rdev)
    if any(old.rdev and old.rdev != new.rdev for old, new in zip(baseline_without_rdev, baseline)):
        raise SafetyError(DISK_IDENTITY_CHANGED)
    # The result claim records the boot and erased target kernel devices at
    # launch. A same-path replacement can duplicate lsblk's model/serial/WWN;
    # do not discard the kernel identity when preparing a later report copy.
    for item in baseline:
        expected = (expected_required_rdevs or {}).get(os.path.realpath(item.path))
        if expected is not None and item.rdev != expected:
            raise SafetyError(DISK_IDENTITY_CHANGED)
    protected_rdevs = set(_protected_rdevs(second_payload, baseline_without_rdev))
    protected_rdevs.update(item.rdev for item in baseline if item.rdev > 0)
    protected_rdevs.update(value for value in (target_rdev, boot_rdev) if value > 0)
    volume = _volume_with_rdev(second)
    if volume.rdev in protected_rdevs or volume.parent.rdev in protected_rdevs:
        raise SafetyError(USB_IS_PROTECTED)
    _emit_export_marker("BEAMO_WIPE_EXPORT_CONTROLLER_IDENTIFIED")
    log_data, log_status = read_export_log(
        evidence.logfile,
        expected_sha256=evidence.log_sha256,
        expected_size_bytes=evidence.log_size_bytes,
    )
    if evidence.outcome in {"verified", "completed"}:
        # Recovery checks the saved snapshot before showing success. Export
        # must apply the same rule: a sidecar proves bytes were copied intact,
        # but cannot prove a completion claim when its log is gone or disagrees.
        if log_status not in {"complete", "tail"}:
            raise SafetyError(EVIDENCE_LOG_META)
        try:
            claim = json.loads(evidence.data)
            from beamo_wipe.nwipe_runner import completion_for_method

            ok, _detail, reason = completion_for_method(
                claim["exit_evidence"]["exit_code"],
                log_data.decode("utf-8"),
                claim["device"]["path"],
                claim["method"]["id"],
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise SafetyError(EVIDENCE_LOG_META) from exc
        if not ok or reason != "completed":
            raise SafetyError(EVIDENCE_LOG_META)
    if evidence.outcome == "failed":
        claim = json.loads(evidence.data)
        from beamo_wipe.outcomes import present_evidence

        code = present_evidence(claim).code
        if code in {"occupied", "open_failed", "geometry_unusable"}:
            if log_status not in {"complete", "tail"}:
                raise SafetyError(EVIDENCE_LOG_META)
            from beamo_wipe.nwipe_runner import completion_for_method

            ok, _detail, reason = completion_for_method(
                claim["exit_evidence"]["exit_code"],
                log_data.decode("utf-8"),
                claim["device"]["path"],
                claim["method"]["id"],
            )
            if ok or reason != code:
                raise SafetyError(EVIDENCE_LOG_META)
    request = json.dumps(
        _request_dict(
            evidence,
            volume,
            baseline,
            sorted(protected_rdevs),
            log_data,
            log_status,
            privacy_reduced,
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
        raise SafetyError(EXPORT_TIMEOUT) from exc
    except OSError as exc:
        raise SafetyError(HELPER_NO_START) from exc
    if proc.returncode != 0 or len(proc.stdout or "") > 8192:
        raise SafetyError(HELPER_FAILED)
    try:
        raw = json.loads(
            (proc.stdout or "").strip(), object_pairs_hook=_unique_request_fields
        )
        if (
            not isinstance(raw, dict)
            or set(raw) != RECEIPT_KEYS
            or type(raw["ok"]) is not bool
            or type(raw["safe_to_remove"]) is not bool
            or type(raw["share_copy"]) is not bool
            or any(
                not isinstance(raw[key], str)
                for key in (
                    "code",
                    "evidence_sha256",
                    "session_name",
                    "log_status",
                    "destination_label",
                    "report_folder",
                    "owner_file",
                )
            )
        ):
            raise TypeError("invalid receipt schema")
        receipt = ExportReceipt(**raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SafetyError(HELPER_BAD_RECEIPT) from exc
    if receipt.ok is True:
        diagnostic = _is_diagnostic_evidence(evidence.data)
        expected = build_success_receipt(
            evidence_sha256=evidence.sha256,
            session_name=receipt.session_name,
            log_status=log_status,
            volume=volume,
            privacy_reduced=privacy_reduced,
            diagnostic=diagnostic,
        )
        if receipt != expected or not receipt_is_saved(
            receipt,
            expected_sha256=evidence.sha256,
            owner_file=expected.owner_file,
            share_copy=expected.share_copy,
        ):
            raise SafetyError(RECEIPT_INVALID)
    elif receipt != ExportReceipt(False, False, "export_failed"):
        # Failure is an exact fail-closed state. In particular, never return a
        # contradictory safe-to-remove flag from untrusted worker stdout.
        raise SafetyError(RECEIPT_FAILURE_INVALID)
    return receipt


def _full_write(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "short report write")
        view = view[written:]


def _write_exclusive(directory_fd: int, name: str, data: bytes) -> None:
    temporary = "." + name + ".partial"
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        _full_write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    # Session directory is new and exclusively owned by this export attempt.
    os.rename(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)


def _read_at(directory_fd: int, name: str, *, limit: int = MAX_REQUEST_BYTES) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,100}", name) or name in {".", ".."}:
        raise SafetyError(REPORT_FILENAME_INVALID)
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > limit:
            raise SafetyError(REPORT_UNSAFE_FILE)
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise SafetyError(REPORT_TOO_BIG)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _bundle_files(
    evidence: bytes,
    log_data: bytes,
    log_status: str,
    *,
    privacy_reduced: bool = False,
) -> dict[str, bytes]:
    try:
        diagnostic = json.loads(evidence).get("report_type") == "startup_diagnostic"
    except (ValueError, AttributeError):
        diagnostic = False
    if diagnostic:
        from beamo_wipe.diagnostic_report import validate_report, NOTICE
        diagnostic_payload = validate_report(evidence)
        if log_data or log_status != "unavailable":
            raise SafetyError(DIAG_NO_RAW_LOGS)
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
    from beamo_wipe.privacy import (
        POLICY_VERSION,
        SHARE_JSON,
        SHARE_SUMMARY,
        encode_sharing_copy,
        make_sharing_copy,
    )
    from beamo_wipe.result_summary import (
        build_result_report_html,
        build_result_summary,
        encode_summary,
    )
    try:
        payload = json.loads(evidence)
        result_view = present_evidence(payload)
    except (ValueError, UnicodeDecodeError, TypeError):
        payload = {}
        result_view = present_evidence(None)
    if not diagnostic:
        owner_summary = encode_summary(
            build_result_summary(
                payload, evidence_sha256=evidence_hash, redacted=False
            )
        )
        files["RESULT.txt"] = owner_summary
        files["RESULT.txt.sha256"] = (
            f"{hashlib.sha256(owner_summary).hexdigest()}  RESULT.txt\n".encode("ascii")
        )
        owner_page = build_result_report_html(
            payload, evidence_sha256=evidence_hash
        ).encode("utf-8")
        files["REPORT.html"] = owner_page
        files["REPORT.html.sha256"] = (
            f"{hashlib.sha256(owner_page).hexdigest()}  REPORT.html\n".encode("ascii")
        )
        if privacy_reduced and isinstance(payload, dict):
            sharing = make_sharing_copy(payload)
            share_json = encode_sharing_copy(sharing)
            share_hash = hashlib.sha256(share_json).hexdigest()
            files[SHARE_JSON] = share_json
            files[f"{SHARE_JSON}.sha256"] = (
                f"{share_hash}  {SHARE_JSON}\n".encode("ascii")
            )
            share_summary = encode_summary(
                build_result_summary(
                    sharing, evidence_sha256=share_hash
                )
            )
            files[SHARE_SUMMARY] = share_summary
            files[f"{SHARE_SUMMARY}.sha256"] = (
                f"{hashlib.sha256(share_summary).hexdigest()}  {SHARE_SUMMARY}\n".encode("ascii")
            )
    if privacy_reduced and not diagnostic:
        readme = (
            f"{result_view.announcement}\r\n"
            f"{README_TITLE}\r\n"
            f"{README_ORIGINAL}\r\n"
            f"{README_SHARE}\r\n"
            f"{README_SHARE_HOW}\r\n"
            f"{README_LOG.format(status=log_status)}\r\n"
            f"{README_COMPLETE}\r\n"
            f"{README_SUPPORT}\r\n"
        ).encode("utf-8")
    else:
        readme = (
            f"{result_view.announcement}\r\n"
            f"{README_TITLE}\r\n"
            f"{README_SIMPLE}\r\n"
            f"{README_LOG_SIMPLE.format(status=log_status)}\r\n"
            f"{README_COMPLETE}\r\n"
            f"{README_SUPPORT}\r\n"
        ).encode("utf-8")
    if isinstance(payload, dict) and isinstance(payload.get("checks"), list):
        from beamo_wipe import engine_checks as checks

        # The JSON is copied verbatim for the owner, but README is a short
        # human-facing summary. Never interpolate arbitrary saved check text:
        # it can contain disk IDs, line breaks, or a fabricated assurance.
        approved = {
            ("hidden_capacity", "unavailable"): checks.HIDDEN_UNAVAILABLE,
            ("hidden_capacity", "warning"): checks.HIDDEN_MAYBE,
            ("hidden_capacity", "pass"): checks.HIDDEN_NONE,
            ("io_media", "unavailable"): checks.IO_UNAVAILABLE,
            ("io_media", "fail"): checks.IO_ERRORS,
            ("io_media", "pass"): checks.IO_CLEAN,
            ("coverage", "warning"): checks.COVERAGE_SUMMARY,
        }
        # A saved JSON digest proves byte integrity, not that an advisory
        # "pass" still agrees with the log copied beside it. A tail cannot
        # rule out an earlier contradictory line, so only a complete log may
        # corroborate pass claims in this short owner-facing README.
        corroborated_passes: set[str] = set()
        device = payload.get("device")
        device_path = device.get("path") if isinstance(device, dict) else None
        if log_status == "complete" and log_data and isinstance(device_path, str):
            observed = checks.evaluate_engine_checks(
                log_data.decode("utf-8", errors="replace"), device_path
            )
            corroborated_passes = {
                item.id for item in observed if item.status == "pass"
            }
        safe_lines: list[str] = []
        seen: set[str] = set()
        saved_checks = payload["checks"]
        if len(saved_checks) <= len(checks.CHECK_IDS):
            for check in saved_checks:
                if not isinstance(check, dict):
                    safe_lines.clear()
                    break
                ident, status, summary = (
                    check.get(key) for key in ("id", "status", "summary")
                )
                if (
                    not isinstance(ident, str)
                    or not isinstance(status, str)
                    or not isinstance(summary, str)
                    or ident in seen
                    or approved.get((ident, status)) != summary
                ):
                    safe_lines.clear()
                    break
                seen.add(ident)
                if status == "pass" and ident not in corroborated_passes:
                    continue
                safe_lines.append(
                    README_CHECK.format(ident=ident, status=status, summary=summary)
                )
        for line in safe_lines:
            readme += (line + "\r\n").encode("utf-8")
    if diagnostic:
        files = {"diagnostic.json": evidence,
                 "diagnostic.json.sha256": f"{evidence_hash}  diagnostic.json\n".encode("ascii")}
        from beamo_wipe.compat_story import sentence_from_application

        identity_line = sentence_from_application(diagnostic_payload.get("application"))
        readme = (
            diagnostic_payload["title"]
            + "\r\n"
            + NOTICE
            + "\r\n"
            + identity_line
            + "\r\n"
            + README_DIAG_TIME
            + "\r\n"
        ).encode()
    files["README.txt"] = readme
    manifest = {
        "manifest_scope": "content_only",
        "safe_to_remove": False,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "log_status": log_status,
        "schema_version": 1,
        "result_summary": "RESULT.txt" if "RESULT.txt" in files else "",
        "share_copy": "SHARE.json" if "SHARE.json" in files else "",
        "share_summary": "SHARE.txt" if "SHARE.txt" in files else "",
        "privacy_policy_version": POLICY_VERSION if "SHARE.json" in files else 0,
    }
    files["COMPLETE"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return files


def _close_directory_fds(*fds: int) -> None:
    """Close every owned directory even if an earlier close reports an error."""
    first_error: BaseException | None = None
    for fd in fds:
        if fd < 0:
            continue
        try:
            os.close(fd)
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def write_report_bundle(
    mountpoint: Path,
    evidence: bytes,
    log_data: bytes,
    log_status: str,
    *,
    session_name: Optional[str] = None,
    privacy_reduced: bool = False,
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
                raise SafetyError(SESSION_NAME_INVALID)
            try:
                os.mkdir(candidate, 0o700, dir_fd=reports_fd)
                chosen = candidate
                break
            except FileExistsError:
                continue
        if not chosen:
            raise SafetyError(REPORT_DIR_ALLOC)
        session_fd = os.open(
            chosen,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=reports_fd,
        )
        files = _bundle_files(
            evidence, log_data, log_status, privacy_reduced=privacy_reduced
        )
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
        _close_directory_fds(session_fd, reports_fd, mount_fd)


def verify_report_bundle(mountpoint: Path, session_name: str, files: Mapping[str, bytes]) -> None:
    if not SESSION_RE.fullmatch(session_name):
        raise SafetyError(RECEIPT_DIR_INVALID)
    mount_fd = os.open(str(mountpoint), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    reports_fd = directory_fd = -1
    try:
        reports_fd = os.open(REPORTS_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=mount_fd)
        directory_fd = os.open(session_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=reports_fd)
        names = sorted(os.listdir(directory_fd))
        if names != sorted(files):
            raise SafetyError(REPORT_FILES_CHANGED)
        for name, expected in files.items():
            if _read_at(directory_fd, name, limit=len(expected)) != expected:
                raise SafetyError(REPORT_READBACK_FAILED)
    finally:
        _close_directory_fds(directory_fd, reports_fd, mount_fd)


def _mount_record(mountpoint: Path) -> Optional[tuple[str, str, str, frozenset[str]]]:
    try:
        text = Path(MOUNTINFO_PATH).read_text(encoding="utf-8")
    except OSError as exc:
        raise SafetyError(MOUNT_UNVERIFIED) from exc
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
        # mountinfo's pre-separator options describe this mount. The trailing
        # superblock options can differ and cannot prove this mount is
        # read-only or carries nodev/nosuid/noexec/nosymfollow.
        options = frozenset(left_parts[5].split(","))
        matches.append((left_parts[2], right_parts[0], right_parts[1], options))
    if len(matches) > 1:
        raise SafetyError(MOUNTPOINT_AMBIGUOUS)
    return matches[0] if matches else None


def _verify_mount(mountpoint: Path, volume: ExportVolume, *, read_only: bool) -> None:
    record = _mount_record(mountpoint)
    if record is None:
        raise SafetyError(USB_NOT_MOUNTED)
    major_minor, fstype, source, options = record
    if fstype != volume.fstype or major_minor != f"{os.major(volume.rdev)}:{os.minor(volume.rdev)}":
        raise SafetyError(MOUNT_IDENTITY_MISMATCH)
    try:
        source_stat = os.stat(source, follow_symlinks=False)
        mounted_stat = os.stat(mountpoint, follow_symlinks=False)
    except OSError as exc:
        raise SafetyError(MOUNT_IDENTITY_UNCHECKED) from exc
    if source_stat.st_rdev != volume.rdev or mounted_stat.st_dev != volume.rdev:
        raise SafetyError(MOUNT_SOURCE_CHANGED)
    required = {"nodev", "nosuid", "noexec", "nosymfollow", "ro" if read_only else "rw"}
    if not required.issubset(options):
        raise SafetyError(MOUNT_MISSING_OPTIONS)


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


def _unique_request_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate report request field")
        result[key] = value
    return result


def _decode_worker_request(
    raw: bytes,
) -> tuple[
    VerifiedEvidence,
    ExportVolume,
    list[DeviceFingerprint],
    tuple[int, ...],
    bytes,
    str,
    bool,
]:
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise SafetyError(REQUEST_SIZE_INVALID)
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_request_fields
        )
        if not isinstance(payload, dict) or set(payload) != {
            "evidence",
            "evidence_sha256",
            "volume",
            "baseline",
            "protected_rdevs",
            "log",
            "log_status",
            "privacy_reduced",
        }:
            raise TypeError("unexpected request fields")
        evidence_data = base64.b64decode(payload["evidence"], validate=True)
        evidence_payload = json.loads(
            evidence_data, object_pairs_hook=_unique_request_fields
        )
        if not isinstance(evidence_payload, dict):
            raise TypeError("report evidence must be an object")
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
        privacy_reduced = payload["privacy_reduced"]
        if type(privacy_reduced) is not bool:
            raise TypeError("invalid privacy flag")
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise SafetyError(REQUEST_MALFORMED) from exc
    evidence_hash = hashlib.sha256(evidence_data).hexdigest()
    if payload.get("evidence_sha256") != evidence_hash:
        raise SafetyError(REQUEST_CHECKSUM)
    is_diagnostic = evidence_payload.get("report_type") == "startup_diagnostic"
    if is_diagnostic:
        from beamo_wipe.diagnostic_report import validate_report
        validate_report(evidence_data)
        if log_data or log_status != "unavailable":
            raise SafetyError(DIAG_NO_RAW_LOGS)
    if not isinstance(log_status, str) or log_status not in {
        "complete",
        "tail",
        "unavailable",
    }:
        raise SafetyError(LOG_STATUS_MALFORMED)
    if (log_status == "unavailable") != (not log_data):
        raise SafetyError(LOG_PAYLOAD_MALFORMED)
    return (
        VerifiedEvidence(evidence_data, evidence_hash, "", "", "", 0),
        volume,
        baseline,
        protected_rdevs,
        log_data,
        log_status,
        privacy_reduced,
    )


def _assert_partition_parent(volume: ExportVolume) -> None:
    """Prove a partition rdev is a child of the selected whole-disk rdev."""
    if volume.path == volume.parent.path:
        if volume.rdev != volume.parent.rdev:
            raise SafetyError(USB_BLOCK_CHANGED)
        return
    sysfs_link = SYS_DEV_BLOCK_ROOT / f"{os.major(volume.rdev)}:{os.minor(volume.rdev)}"
    resolved = Path(os.path.realpath(sysfs_link))
    try:
        if (
            not str(resolved).startswith("/sys/devices/")
            or not (resolved / "partition").is_file()
        ):
            raise SafetyError(USB_PARTITION_INVALID)
        text = (resolved.parent / "dev").read_text(encoding="ascii").strip()
        major_text, minor_text = text.split(":", 1)
        parent_rdev = os.makedev(int(major_text), int(minor_text))
    except (OSError, ValueError) as exc:
        raise SafetyError(USB_PARTITION_UNVERIFIED) from exc
    if parent_rdev != volume.parent.rdev:
        raise SafetyError(USB_PARTITION_ORPHAN)


def _persist_and_verify_report(
    volume: ExportVolume,
    evidence: VerifiedEvidence,
    log_data: bytes,
    log_status: str,
    volume_fd: int,
    privacy_reduced: bool = False,
) -> ExportReceipt:
    """Run the mounted-media state machine after block identity is pinned."""
    lock_fd = -1
    root_fd = -1
    mountpoint: Optional[Path] = None
    mount_name = ""
    mounted = False
    try:
        try:
            MOUNT_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
            root_fd = os.open(MOUNT_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if os.fstat(root_fd).st_uid != os.getuid():
                raise SafetyError(MOUNT_UNVERIFIED)
            os.fchmod(root_fd, 0o700)
        except OSError as exc:
            raise SafetyError(MOUNT_UNVERIFIED) from exc
        try:
            lock_fd = os.open(
                ".lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=root_fd,
            )
            lock_stat = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or lock_stat.st_uid != os.getuid()
                or stat.S_IMODE(lock_stat.st_mode) != 0o600
                or lock_stat.st_nlink != 1
                or lock_stat.st_size != 0
            ):
                raise SafetyError(MOUNT_UNVERIFIED)
        except OSError as exc:
            raise SafetyError(MOUNT_UNVERIFIED) from exc
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SafetyError(EXPORT_RUNNING) from exc
        except OSError as exc:
            raise SafetyError(MOUNT_UNVERIFIED) from exc
        # Reject a lock name replaced between open and acquisition. The open
        # descriptor alone would otherwise serialize a different file.
        try:
            named_lock = os.stat(".lock", dir_fd=root_fd, follow_symlinks=False)
        except OSError as exc:
            raise SafetyError(MOUNT_UNVERIFIED) from exc
        if (named_lock.st_dev, named_lock.st_ino) != (
            lock_stat.st_dev,
            lock_stat.st_ino,
        ):
            raise SafetyError(MOUNT_UNVERIFIED)
        mount_name = f"mount-{secrets.token_hex(12)}"
        os.mkdir(mount_name, 0o700, dir_fd=root_fd)
        mountpoint = MOUNT_ROOT / mount_name
        stable_source = f"/proc/self/fd/{volume_fd}"
        rw_options = "rw,nodev,nosuid,noexec,nosymfollow,umask=077"
        proc = _run_command(
            [MOUNT_BIN, "-t", volume.fstype, "-o", rw_options, stable_source, str(mountpoint)],
            pass_fds=(volume_fd,),
        )
        mounted = _mounted_exact(mountpoint, volume)
        if proc.returncode != 0 or not mounted:
            raise SafetyError(USB_MOUNT_FAILED)
        _verify_mount(mountpoint, volume, read_only=False)
        _emit_export_marker("BEAMO_WIPE_EXPORT_RW_MOUNTED")
        session_name, files = write_report_bundle(
            mountpoint,
            evidence.data,
            log_data,
            log_status,
            privacy_reduced=privacy_reduced,
        )
        sync_proc = _run_command([SYNC_BIN, "-f", str(mountpoint)])
        if sync_proc.returncode != 0:
            raise SafetyError(USB_SYNC_FAILED)
        _emit_export_marker("BEAMO_WIPE_EXPORT_BUNDLE_WRITTEN")
        if not _ordinary_unmount(mountpoint, volume):
            mounted = _mounted_exact(mountpoint, volume)
            raise SafetyError(USB_UNMOUNT_FAILED)
        mounted = False
        _emit_export_marker("BEAMO_WIPE_EXPORT_RW_UNMOUNTED")

        ro_options = "ro,nodev,nosuid,noexec,nosymfollow"
        proc = _run_command(
            [MOUNT_BIN, "-t", volume.fstype, "-o", ro_options, stable_source, str(mountpoint)],
            pass_fds=(volume_fd,),
        )
        mounted = _mounted_exact(mountpoint, volume)
        if proc.returncode != 0 or not mounted:
            raise SafetyError(USB_REMOUNT_FAILED)
        _verify_mount(mountpoint, volume, read_only=True)
        _emit_export_marker("BEAMO_WIPE_EXPORT_RO_MOUNTED")
        verify_report_bundle(mountpoint, session_name, files)
        _emit_export_marker("BEAMO_WIPE_EXPORT_READBACK_VERIFIED")
        if not _ordinary_unmount(mountpoint, volume):
            mounted = _mounted_exact(mountpoint, volume)
            raise SafetyError(USB_VERIFIED_UNMOUNT_FAILED)
        mounted = False
        if _mount_record(mountpoint) is not None:
            raise SafetyError(USB_STILL_MOUNTED)
        _emit_export_marker("BEAMO_WIPE_EXPORT_RO_UNMOUNTED")
        return build_success_receipt(
            evidence_sha256=evidence.sha256,
            session_name=session_name,
            log_status=log_status,
            volume=volume,
            privacy_reduced=privacy_reduced,
            diagnostic=_is_diagnostic_evidence(evidence.data),
        )
    finally:
        if mountpoint is not None and mounted:
            _ordinary_unmount(mountpoint, volume)
        if lock_fd >= 0:
            os.close(lock_fd)
        if mount_name and root_fd >= 0:
            try:
                os.rmdir(mount_name, dir_fd=root_fd)
            except OSError:
                pass
        if root_fd >= 0:
            os.close(root_fd)


def _worker() -> ExportReceipt:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    evidence, expected, baseline, protected, log_data, log_status, privacy_reduced = _decode_worker_request(raw)
    _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_DECODED")
    fresh_payload1 = run_lsblk()
    fresh1 = select_export_volume(fresh_payload1, baseline)
    fresh_payload2 = run_lsblk()
    fresh2 = select_export_volume(fresh_payload2, baseline)
    if not _same_volume(fresh1, fresh2, include_rdev=False) or not _same_volume(
        fresh2, expected, include_rdev=False
    ):
        raise SafetyError(USB_CHANGED_BEFORE_MOUNT)
    _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_SELECTED")

    for original in baseline:
        if not original.required:
            continue
        if original.rdev <= 0 or _block_rdev(original.path) != original.rdev:
            raise SafetyError(DISK_IDENTITY_CHANGED)
    fresh_protected = _protected_rdevs(fresh_payload2, baseline)
    if fresh_protected != protected:
        raise SafetyError(PROTECTED_CHANGED)
    volume = _volume_with_rdev(fresh2)
    if volume.rdev in protected or volume.parent.rdev in protected:
        raise SafetyError(USB_ALIASES_PROTECTED)
    if not _same_volume(volume, expected, include_rdev=True):
        raise SafetyError(USB_BLOCK_CHANGED)
    _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_IDENTIFIED")
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    parent_fd = os.open(volume.parent.path, flags)
    volume_fd = -1
    try:
        volume_fd = os.open(volume.path, flags)
        if os.fstat(parent_fd).st_rdev != volume.parent.rdev or os.fstat(volume_fd).st_rdev != volume.rdev:
            raise SafetyError(USB_IDENTITY_CHANGED_OPEN)
        _assert_partition_parent(volume)
        _emit_export_marker("BEAMO_WIPE_EXPORT_WORKER_OPENED")
        return _persist_and_verify_report(
            volume, evidence, log_data, log_status, volume_fd, privacy_reduced
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
