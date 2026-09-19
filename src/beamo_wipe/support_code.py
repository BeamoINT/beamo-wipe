# SPDX-License-Identifier: GPL-3.0-or-later
"""Stable, non-sensitive support codes plus build identity.

Shown when a diagnostic or wipe report cannot be saved, so an owner can
read the values from a screenshot or over the phone. Codes are a closed
taxonomy: never disk identifiers, paths, serials, or translated text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional

# Product prefix plus a one-letter family. Tokens use a phone-safe alphabet
# (A–Z and 2–9, no 0/O/1/I/L) so a photo or spoken readout cannot collide
# with look-alikes. Full displayed form: BW-S-DSCV
PREFIX = "BW"
FAMILIES = frozenset({"S", "X", "R", "E", "U"})
PHONE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TOKEN_RE = re.compile(r"^[" + PHONE_ALPHABET + r"]{2,8}$")
CODE_RE = re.compile(r"^BW-[SXREU]-[" + PHONE_ALPHABET + r"]{2,8}$")
UNKNOWN = "BW-U-UNKN"
BUILD_UNAVAILABLE = "unavailable"

# Startup / discovery (diagnostic_report.CODES). Family S.
STARTUP_TOKENS: dict[str, str] = {
    "recovery_indeterminate": "S-PREV",
    "startup_refused": "S-REFU",
    "dependency_missing": "S-DEPS",
    "permission_denied": "S-PERM",
    "io_failed": "S-XFER",
    "discovery_timeout": "S-TME",
    "discovery_command_failed": "S-CMD",
    "discovery_invalid": "S-BADF",
    "discovery_failed": "S-DSCV",
    "boot_unidentified": "S-BUND",
    "no_eligible_disks": "S-EMPTY",
    "refresh_failed": "S-RFRS",
    "rediscovery_failed": "S-RDSV",
    "identity_rejected": "S-NMCH",
    "preflight_rejected": "S-PREP",
    "engine_start_failed": "S-STRT",
    "graphical_unavailable": "S-GRAF",
    "unexpected_startup_failure": "S-UNEX",
}

# Finished-wipe outcome codes. Family R. verified is omitted: export can proceed.
OUTCOME_TOKENS: dict[str, str] = {
    "start_failed": "R-STRT",
    "unverified": "R-NVER",
    "occupied": "R-BUSY",
    "open_failed": "R-NACC",
    "geometry_unusable": "R-GTRY",
    "verification_failed": "R-VRFY",
    "interrupted": "R-BRK",
    "cancelled": "R-ABRT",
    "completion_missing": "R-NCMP",
    "process_failed": "R-PRCS",
    "engine_failed": "R-ENG",
    "indeterminate": "R-UNKN",
    "stop_unconfirmed": "R-STUC",
}

# Local evidence-save failures. Family E.
EVIDENCE_TOKENS: dict[str, str] = {
    "permissions": "E-PERM",
    "storage_full": "E-CAP",
    "finalization": "E-WRAP",
    "invalid_data": "E-DATA",
    "transient_io": "E-TMP",
    "io": "E-XFER",
}


@dataclass(frozen=True)
class SupportIdentity:
    """Owner-facing correlation values. Never includes disk identity."""

    code: str
    build_id: str
    extra_code: str = ""

    def lines(self, *, labels: Mapping[str, str] | None = None) -> str:
        names = labels or _labels()
        rows = [f"{names['code']}  {self.code}"]
        if self.extra_code:
            rows.append(f"{names['save']}  {self.extra_code}")
        rows.append(f"{names['build']}  {self.build_id}")
        return "\n".join(rows)

    def spoken_groups(self) -> tuple[str, ...]:
        """Hyphen groups for phone transcription of the primary code."""
        return tuple(self.code.split("-"))


def display_code(token: str) -> str:
    if not isinstance(token, str) or not token:
        return UNKNOWN
    if CODE_RE.fullmatch(token):
        return token
    if "-" in token and TOKEN_RE.fullmatch(token.split("-", 1)[-1]):
        family, rest = token.split("-", 1)
        if family in FAMILIES and TOKEN_RE.fullmatch(rest):
            return f"{PREFIX}-{family}-{rest}"
    return UNKNOWN


def code_for_startup(error_code: object) -> str:
    if not isinstance(error_code, str) or not error_code:
        return UNKNOWN
    token = STARTUP_TOKENS.get(error_code)
    return display_code(token) if token else UNKNOWN


def code_for_outcome(outcome_code: object) -> str:
    if not isinstance(outcome_code, str) or not outcome_code:
        return UNKNOWN
    token = OUTCOME_TOKENS.get(outcome_code)
    return display_code(token) if token else UNKNOWN


def code_for_evidence(error_code: object) -> str:
    if not isinstance(error_code, str) or not error_code:
        return UNKNOWN
    token = EVIDENCE_TOKENS.get(error_code)
    return display_code(token) if token else UNKNOWN


def _export_pairs() -> list[tuple[str, str]]:
    """Current-language refusal text → token. Rebuilt after language changes."""
    from beamo_wipe import support_export as E
    from beamo_wipe import wizard as W

    none = E.USB_NOT_SINGLE.format(detail=E.USB_NONE_FOUND)
    many = E.USB_NOT_SINGLE.format(detail=E.USB_MANY_FOUND)
    return [
        (E.USB_META_INCOMPLETE, "X-META"),
        (E.USB_META_MALFORMED, "X-MFM"),
        (E.USB_SIZE_INVALID, "X-SZ"),
        (E.USB_MOUNT_META_INCOMPLETE, "X-MMSS"),
        (E.USB_MOUNT_META_MALFORMED, "X-MMFM"),
        (E.USB_DEVICE_PATH_UNSUPPORTED, "X-DPTH"),
        (E.DISCOVERY_MALFORMED, "X-DSC"),
        (E.DISCOVERY_DUPLICATES, "X-DUPD"),
        (E.BASELINE_KEEP_CONNECTED, "X-KEEP"),
        (E.NEW_NOT_REMOVABLE, "X-NREM"),
        (none, "X-NUSB"),
        (many, "X-MANY"),
        (E.USB_MUST_BE_WRITABLE, "X-WRT"),
        (E.USB_LAYOUT_MALFORMED, "X-ARNG"),
        (E.USB_LAYOUT_AMBIGUOUS, "X-AMBG"),
        (E.USB_NEED_ONE_VOLUME, "X-VSNG"),
        (E.USB_LAYOUT_UNSUPPORTED, "X-UNSP"),
        (E.USB_PARTITION_ORPHAN, "X-NPAR"),
        (E.USB_VOLUME_PATH_UNSUPPORTED, "X-VPTH"),
        (E.USB_VOLUME_WRITABLE, "X-VWRT"),
        (E.USB_VOLUME_SMALL, "X-VSZ"),
        (E.USB_FAT32_ONLY, "X-FAT"),
        (E.USB_FAT32_NOT_12_16, "X-FATN"),
        (E.EVIDENCE_MALFORMED, "X-EMFM"),
        (E.EVIDENCE_SCHEMA, "X-ESCH"),
        (E.EVIDENCE_NOT_FINISHED, "X-ENFN"),
        (E.EVIDENCE_NO_IDENTITY, "X-ENKY"),
        (E.EVIDENCE_WRONG_DISK, "X-EWDS"),
        (E.EVIDENCE_PROVENANCE, "X-EPRV"),
        (E.EVIDENCE_LOG_META, "X-EGMT"),
        (E.USB_GONE, "X-VAN"),
        (E.USB_NOT_BLOCK, "X-NDEV"),
        (E.PROTECTED_LAYOUT_BAD, "X-PBAD"),
        (E.PROTECTED_IDENTITY_UNVERIFIED, "X-PVCK"),
        (E.REPORT_CHANGED_BEFORE_EXPORT, "X-RCHG"),
        (E.BASELINE_PREPARE_FIRST, "X-BPRE"),
        (E.BOOT_IDENTITY_UNAVAILABLE, "X-BNKY"),
        (E.NO_BASELINE, "X-NBAS"),
        (E.BOOT_ABSENT_BASELINE, "X-BABS"),
        (E.UNSTABLE_BASELINE, "X-BSTB"),
        (E.CANNOT_VERIFY_BOOT, "X-VRFB"),
        (E.DISK_CHANGED_PREPARE, "X-DCHG"),
        (E.USB_CHANGED_DISCOVERY, "X-UCHG"),
        (E.DISK_IDENTITY_CHANGED, "X-DSGN"),
        (E.USB_IS_PROTECTED, "X-PRTD"),
        (E.EXPORT_TIMEOUT, "X-TME"),
        (E.HELPER_NO_START, "X-HNST"),
        (E.HELPER_FAILED, "X-HERR"),
        (E.HELPER_BAD_RECEIPT, "X-HRCT"),
        (E.RECEIPT_INVALID, "X-RCPT"),
        (E.RECEIPT_FAILURE_INVALID, "X-RBAD"),
        (E.REPORT_FILENAME_INVALID, "X-FNMS"),
        (E.REPORT_UNSAFE_FILE, "X-UNSF"),
        (E.REPORT_TOO_BIG, "X-TSZ"),
        (E.DIAG_NO_RAW_LOGS, "X-NRAW"),
        (E.SESSION_NAME_INVALID, "X-SESS"),
        (E.REPORT_DIR_ALLOC, "X-DNEW"),
        (E.RECEIPT_DIR_INVALID, "X-RNAM"),
        (E.REPORT_FILES_CHANGED, "X-FCHG"),
        (E.REPORT_READBACK_FAILED, "X-READ"),
        (E.MOUNT_UNVERIFIED, "X-MUNV"),
        (E.MOUNTPOINT_AMBIGUOUS, "X-MAMB"),
        (E.USB_NOT_MOUNTED, "X-NMNT"),
        (E.MOUNT_IDENTITY_MISMATCH, "X-MMSM"),
        (E.MOUNT_IDENTITY_UNCHECKED, "X-MCHK"),
        (E.MOUNT_SOURCE_CHANGED, "X-MSRC"),
        (E.MOUNT_MISSING_OPTIONS, "X-MREQ"),
        (E.REQUEST_SIZE_INVALID, "X-RSZ"),
        (E.REQUEST_MALFORMED, "X-RMFM"),
        (E.REQUEST_CHECKSUM, "X-RSUM"),
        (E.LOG_STATUS_MALFORMED, "X-STTS"),
        (E.LOG_PAYLOAD_MALFORMED, "X-NPAY"),
        (E.USB_BLOCK_CHANGED, "X-BDEV"),
        (E.USB_PARTITION_INVALID, "X-PPAR"),
        (E.USB_PARTITION_UNVERIFIED, "X-PUNV"),
        (E.EXPORT_RUNNING, "X-BUSY"),
        (E.USB_MOUNT_FAILED, "X-MNTF"),
        (E.USB_SYNC_FAILED, "X-SYNC"),
        (E.USB_UNMOUNT_FAILED, "X-UMNT"),
        (E.USB_REMOUNT_FAILED, "X-RMNT"),
        (E.USB_VERIFIED_UNMOUNT_FAILED, "X-VUMN"),
        (E.USB_STILL_MOUNTED, "X-SMNT"),
        (E.USB_CHANGED_BEFORE_MOUNT, "X-CBMT"),
        (E.PROTECTED_CHANGED, "X-PCHG"),
        (E.USB_ALIASES_PROTECTED, "X-DUPA"),
        (E.USB_IDENTITY_CHANGED_OPEN, "X-ACHG"),
        (W.NO_FINISHED_REPORT, "X-NEND"),
        (W.EVIDENCE_UNREADABLE, "X-ERED"),
        (W.REPORT_CHANGED_BEFORE_SAVE, "X-RBEF"),
        (W.EXPORT_FAILED, "X-EXPF"),
        (W.REPORT_NOT_SAVED, "X-NSVD"),
        (W.REPORT_CHANGED_DURING_SAVE, "X-RDUR"),
        (W.EXPORT_NO_START, "X-NSTT"),
        (W.DIAG_NO_PREVIEW, "X-DRY"),
        (W.DIAG_NOT_SAVED, "X-DNSV"),
        (W.DIAG_CONTEXT_CHANGED, "X-CTX"),
        (W.DIAG_FAILED, "X-DERR"),
        (W.DIAG_NO_START, "X-DNST"),
        (W.NO_EXPORT_EVIDENCE, "X-NEXP"),
    ]


def code_for_export_detail(detail: object) -> str:
    """Map a refusal message by constant identity, never by English words."""
    if not isinstance(detail, str) or not detail:
        return UNKNOWN
    for message, token in _export_pairs():
        if detail == message:
            return display_code(token)
    return UNKNOWN


def is_progress_message(detail: object) -> bool:
    """True for in-progress export copy that is not a refusal."""
    if not isinstance(detail, str) or not detail:
        return False
    from beamo_wipe import wizard as W

    if detail in {W.DIAG_VERIFYING, W.DIAG_CHECKING, W.REPORT_SAVING}:
        return True
    lead, _, _ = W.DIAG_BASELINE_READY.partition("{")
    return bool(lead) and detail.startswith(lead)


def public_build_id() -> str:
    """Injected build_id only. Runtime env and git are ignored."""
    from beamo_wipe.build_identity import evidence_identity

    record = evidence_identity()
    build_id = record.get("build_id")
    if isinstance(build_id, str) and build_id:
        return build_id
    return BUILD_UNAVAILABLE


def all_codes() -> frozenset[str]:
    """Every assigned displayed code, for collision tests."""
    codes = {UNKNOWN}
    for token in STARTUP_TOKENS.values():
        codes.add(display_code(token))
    for token in OUTCOME_TOKENS.values():
        codes.add(display_code(token))
    for token in EVIDENCE_TOKENS.values():
        codes.add(display_code(token))
    for _message, token in _export_pairs():
        codes.add(display_code(token))
    return frozenset(codes)


def _labels() -> dict[str, str]:
    from beamo_wipe import copy as C

    return {
        "code": C.SUPPORT_CODE_LABEL,
        "save": C.SUPPORT_SAVE_LABEL,
        "build": C.SUPPORT_BUILD_LABEL,
    }


def contains_secrets(text: str, secrets: tuple[str, ...] = ()) -> bool:
    if "/dev/" in text or "\\" in text:
        return True
    return any(secret and secret in text for secret in secrets)


def record_identity(identity: SupportIdentity) -> None:
    """Best-effort log and serial marker using the on-screen code."""
    try:
        from beamo_wipe.diagnostics import emit_serial_marker, log_diag

        extra = {"build": identity.build_id[:64]}
        if identity.extra_code:
            extra["save"] = identity.extra_code
        log_diag("support", identity.code, identity.build_id, extra=extra)
        marker = "BEAMO_WIPE_SUPPORT_" + identity.code.replace("BW-", "").replace("-", "_")
        emit_serial_marker(marker)
        if identity.extra_code:
            extra_marker = (
                "BEAMO_WIPE_SUPPORT_"
                + identity.extra_code.replace("BW-", "").replace("-", "_")
            )
            emit_serial_marker(extra_marker)
    except Exception:
        pass


def identity_for_wizard(wizard: object) -> Optional[SupportIdentity]:
    """Resolve the on-screen identity, or None when export can still proceed."""
    from beamo_wipe.models import Screen

    screen = getattr(wizard, "screen", None)
    preview = bool(getattr(wizard, "preview", False))
    build_id = public_build_id()

    def startup_code() -> str:
        raw = getattr(wizard, "startup_error_code", "") or ""
        if raw:
            return code_for_startup(raw)
        if screen == Screen.PICK_EMPTY or getattr(wizard, "_diagnostic_from", None) == Screen.PICK_EMPTY:
            return code_for_startup("no_eligible_disks")
        if screen == Screen.PICK_BLOCKED:
            discovery = getattr(wizard, "discovery", None)
            discovered = getattr(discovery, "error_code", "") if discovery is not None else ""
            if discovered:
                return code_for_startup(discovered)
            return code_for_startup("boot_unidentified")
        return UNKNOWN

    if screen == Screen.DIAGNOSTIC:
        extra = ""
        message = getattr(wizard, "diagnostic_message", "") or ""
        if message and not is_progress_message(message):
            mapped = code_for_export_detail(message)
            extra = mapped if mapped != UNKNOWN else ""
        return SupportIdentity(code=startup_code(), build_id=build_id, extra_code=extra)

    if screen in {Screen.PICK_BLOCKED, Screen.PICK_EMPTY}:
        return SupportIdentity(code=startup_code(), build_id=build_id)

    if screen == Screen.WHAT and getattr(wizard, "startup_error_code", "") == "graphical_unavailable":
        return SupportIdentity(code=code_for_startup("graphical_unavailable"), build_id=build_id)

    if screen == Screen.LAST_CHANCE and getattr(wizard, "error", None) and getattr(
        wizard, "can_open_diagnostic", False
    ):
        return SupportIdentity(code=startup_code(), build_id=build_id)

    if screen == Screen.DONE and not preview:
        report = getattr(wizard, "report_view", None)
        if report is None:
            return None
        if getattr(report, "status", "") == "saved":
            return None
        evidence_error = getattr(report, "evidence_error", None)
        can_retry = bool(getattr(report, "can_retry_evidence", False))
        if evidence_error and not can_retry:
            extra = ""
            if getattr(report, "status", "") == "error":
                extra = code_for_export_detail(getattr(report, "message", "") or "")
                if extra == UNKNOWN:
                    extra = ""
            return SupportIdentity(
                code=code_for_evidence(getattr(wizard, "evidence_error_code", "")),
                build_id=build_id,
                extra_code=extra,
            )
        if getattr(report, "status", "") == "error":
            export_code = code_for_export_detail(getattr(report, "message", "") or "")
            result = getattr(wizard, "result_view", None)
            outcome = code_for_outcome(getattr(result, "code", "") if result is not None else "")
            if export_code != UNKNOWN:
                extra = outcome if outcome not in {UNKNOWN, export_code} else ""
                return SupportIdentity(code=export_code, build_id=build_id, extra_code=extra)
            return SupportIdentity(code=outcome, build_id=build_id)
        if not getattr(report, "can_save", False):
            result = getattr(wizard, "result_view", None)
            return SupportIdentity(
                code=code_for_outcome(getattr(result, "code", "") if result is not None else ""),
                build_id=build_id,
            )
    return None
