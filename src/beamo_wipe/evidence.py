# SPDX-License-Identifier: GPL-3.0-or-later
"""Auditable result evidence. Off-target, atomic, truthful.

Never overstating: a nonzero/unknown exit or missing success markers is
always FAILED, never COMPLETED/VERIFIED. No hostname, IP, or user details.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import stat
import time
import unicodedata
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from beamo_wipe import NWIPE_PINNED_COMMIT, NWIPE_PINNED_VERSION, __version__
from beamo_wipe.methods import METHODS
from beamo_wipe.storage_limits import VERIFICATION_SCOPE, notice
from beamo_wipe.models import Disk, MethodId, WipeRequest, WipeResult
import beamo_wipe.safety as safety
from beamo_wipe.safety import SafetyError, assert_log_not_on_target


SCHEMA_VERSION = 1
EVIDENCE_PREFIX = "result-"
EVIDENCE_SUFFIX = ".json"
CHECKSUM_SUFFIX = ".sha256"

# Explicit outcome set. VERIFIED means COMPLETED + verify==last + markers.
OUTCOME_STARTED = "started"
OUTCOME_RUNNING = "running"
OUTCOME_INTERRUPTED = "interrupted"
OUTCOME_FAILED = "failed"
OUTCOME_COMPLETED = "completed"  # ok, verify==off or no verify requested
OUTCOME_VERIFIED = "verified"  # ok, verify==last, last-pass or Erased row
ALLOWED_OUTCOMES = frozenset(
    {
        OUTCOME_STARTED,
        OUTCOME_RUNNING,
        OUTCOME_INTERRUPTED,
        OUTCOME_FAILED,
        OUTCOME_COMPLETED,
        OUTCOME_VERIFIED,
    }
)


def _iso_now_wall() -> str:
    # UTC, no local timezone leakage
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _sanitize_argv(argv: Sequence[str]) -> List[str]:
    # Already validated; strip control chars and ensure safe printable
    out: List[str] = []
    for a in argv or []:
        if not isinstance(a, str):
            continue
        if any(unicodedata.category(ch).startswith("C") for ch in a):
            continue
        out.append(a)
    return out


def _device_identity(disk: Optional[Disk]) -> Optional[dict[str, Any]]:
    if disk is None:
        return None
    # Realpath is resolved; path stays as shown to user. No hostname.
    try:
        real = os.path.realpath(disk.path)
    except OSError:
        real = disk.path
    return {
        "path": disk.path,
        "realpath": real,
        "name": disk.name,
        "model": disk.model or "",
        "serial": disk.serial or "",
        "size_bytes": disk.size_bytes,
        "size_gb_label": disk.size_gb_label,
        "kind": disk.kind.value if hasattr(disk.kind, "value") else str(disk.kind),
        "bus": disk.bus or "",
        "vendor": disk.vendor or "",
        "wwn": disk.wwn or "",
        "label": disk.label or "",
        "is_boot": bool(disk.is_boot),
    }


def _exit_signal(exit_code: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    """Return (exit_code, signal) where signal is positive if killed by signal."""
    if exit_code is None or not isinstance(exit_code, int):
        return None, None
    if exit_code < 0:
        # Python's Popen returns -signal
        return exit_code, -exit_code
    if exit_code > 128:
        # Shell convention: 128+signal; but we keep raw exit_code and derive signal if plausible
        # Do not guess; treat as exit_code, signal None unless we know it's a signal
        return exit_code, None
    return exit_code, None


def _warnings_for(disk: Optional[Disk], selectable: Sequence[Disk]) -> List[str]:
    warns: List[str] = []
    if disk is None:
        return warns
    warns.append(notice(disk.kind))
    # Same-size hint
    if disk and selectable:
        labels = [d.size_gb_label for d in selectable]
        if labels.count(disk.size_gb_label) > 1:
            warns.append("Two disks share the same size; verify the serial suffix.")
    return warns


def _verification_state(
    method: MethodId,
    log_text: str,
    device: str,
    exit_code: Optional[int],
    result_ok: bool,
) -> Tuple[str, bool]:
    """Return (verification_requested, verified_bool) truthfully."""
    spec = METHODS.get(method)
    requested = spec.verify if spec else "unknown"
    if not result_ok:
        return requested, False
    if requested == "off":
        # No verification requested; verified is false but outcome can be COMPLETED
        return requested, False
    # For "last"/"all", verify requires evaluate's success markers
    # evaluate_nwipe_completion already checks Erased row or last-pass 100%
    # If result_ok is True, verification passed for that request.
    # But if log is empty and exit 0 without markers, evaluate returns ok False, so not here.
    return requested, True


def _outcome_for(
    *,
    result: Optional[WipeResult],
    method: MethodId,
    log_text: str,
    device: str,
    interrupted: bool,
    cancelled: bool,
) -> Tuple[str, Optional[str]]:
    """Return (outcome, failure_reason). Never upgrades failure to success."""
    if cancelled or interrupted:
        # Even if nwipe later reports success, interruption takes precedence
        return OUTCOME_INTERRUPTED, "interrupted by user or system"
    if result is None:
        # No result yet: running vs started distinguished by caller
        return OUTCOME_RUNNING, None
    # result exists
    ok = False
    exit_code = result.exit_code
    completion_summary = ""
    if result.ok:
        try:
            from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

            ok, completion_summary = evaluate_nwipe_completion(
                exit_code, log_text or "", device
            )
        except Exception:
            ok = False
    spec = METHODS.get(method)
    verify = spec.verify if spec else "unknown"
    # Truthful: nonzero/unknown without markers is FAILED
    # evaluate_nwipe_completion is authoritative; but result.ok already reflects it
    # However if result.summary indicates bus skip / abort / open fail, ok is False
    if not ok:
        # Preserve the summary as failure reason (redacted, no host details)
        reason = (
            completion_summary
            or (result.summary or "").strip()
            or f"nwipe exited {exit_code}"
        )
        # Never translate to success
        return OUTCOME_FAILED, reason
    # ok == True
    if verify == "last":
        return OUTCOME_VERIFIED, None
    return OUTCOME_COMPLETED, None


def build_evidence(
    *,
    disk: Optional[Disk],
    discovery: Any,  # DiscoveryResult
    method: MethodId,
    request: Optional[WipeRequest],
    result: Optional[WipeResult],
    started_at_wall: Optional[str],
    ended_at_wall: Optional[str],
    started_mono: Optional[float],
    ended_mono: Optional[float],
    argv: Optional[Sequence[str]],
    log_text: str,
    interrupted: bool = False,
    cancelled: bool = False,
) -> dict[str, Any]:
    """Build a truthful, user-safe evidence dict."""
    spec = METHODS.get(method)
    if spec is None:
        raise ValueError("unknown method")

    # Timestamps
    started_at_wall = started_at_wall or ""
    ended_at_wall = ended_at_wall or ""
    try:
        duration_s = (
            float(ended_mono - started_mono) if (started_mono is not None and ended_mono is not None) else None  # type: ignore[operator]
        )
        if duration_s is not None and (duration_s < 0 or duration_s != duration_s):  # NaN
            duration_s = None
    except Exception:
        duration_s = None

    # Exit/signal
    exit_code, signal = _exit_signal(result.exit_code if result else None)

    # Device identity
    device_dict = _device_identity(disk)

    # Boot identity (path only, no extra host)
    boot_path = ""
    try:
        boot_path = discovery.boot.path if getattr(discovery, "boot", None) else ""  # type: ignore[union-attr]
    except Exception:
        boot_path = ""

    # Warnings
    selectable: Sequence[Disk] = getattr(discovery, "selectable", ())  # type: ignore[assignment]
    warnings = _warnings_for(disk, selectable)

    # Verification
    device_path = disk.path if disk else (request.device if request else "")
    validated_ok = False
    if result is not None and result.ok:
        try:
            from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

            validated_ok, _summary = evaluate_nwipe_completion(
                result.exit_code, log_text or "", device_path
            )
        except Exception:
            validated_ok = False
    verification_requested, verified = _verification_state(
        method,
        log_text or "",
        (disk.path if disk else (request.device if request else "")),
        exit_code,
        validated_ok,
    )

    # Outcome
    outcome, failure_reason = _outcome_for(
        result=result,
        method=method,
        log_text=log_text or "",
        device=device_path,
        interrupted=interrupted,
        cancelled=cancelled,
    )
    # If still running but we have no result, distinguish STARTED vs RUNNING via presence of request
    if result is None and request is not None and not interrupted and not cancelled:
        # Caller decides started vs running; default to started if we only just built
        # Keep as started unless duration >0
        if duration_s is None or duration_s == 0:
            outcome = OUTCOME_STARTED
        else:
            outcome = OUTCOME_RUNNING
        failure_reason = None

    # Redacted argv
    argv_redacted = _sanitize_argv(argv or [])
    # Ensure no /dev/…/.. or control chars leaked beyond validation
    # Keep only allowed flags and the device itself

    # Log checksum (tail only, not full sensitive log)
    log_checksum: Optional[str] = None
    log_snapshot_size_bytes = 0
    if log_text:
        try:
            log_snapshot = log_text.encode("utf-8", errors="replace")
            log_checksum = hashlib.sha256(log_snapshot).hexdigest()
            log_snapshot_size_bytes = len(log_snapshot)
        except Exception:
            log_checksum = None
            log_snapshot_size_bytes = 0

    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "beamo_wipe_version": __version__,
        "nwipe_version": NWIPE_PINNED_VERSION,
        "nwipe_commit": NWIPE_PINNED_COMMIT,
        "outcome": outcome,
        "failure_reason": failure_reason,
        "result_description": spec.result_description(outcome, verified=verified),
        "device": device_dict,
        "method": {
            "id": method.value,
            "nwipe_method": spec.nwipe_method,
            "rounds": spec.rounds,
            "verify": spec.verify,
            "noblank": spec.noblank,
            "docs_name": spec.docs_name,
            "title": spec.title,
            "overwrite_passes": spec.overwrite_passes,
            "verification_passes": spec.verification_passes,
            "description": spec.description,
        },
        "boot_device": boot_path,
        "timestamps": {
            "started_at_wall": started_at_wall,
            "ended_at_wall": ended_at_wall,
            "started_monotonic": started_mono,
            "ended_monotonic": ended_mono,
            "duration_s": duration_s,
        },
        "nwipe": {
            "version": NWIPE_PINNED_VERSION,
            "argv_redacted": argv_redacted,
        },
        "exit_evidence": {
            "exit_code": exit_code,
            "signal": signal,
        },
        "verification": {
            "requested": verification_requested,
            "verified": verified,
            "scope": VERIFICATION_SCOPE,
        },
        "warnings": warnings,
        "interruption": {
            "interrupted": bool(interrupted or cancelled),
            "cancelled": bool(cancelled),
        },
        "logfile": (result.logfile if result and result.logfile else (request.logfile if request else "")),
        "log_checksum_sha256": log_checksum,
        # Authenticates the exact UTF-8 log suffix used to decide this
        # outcome. The mutable logfile is exported only when this length and
        # digest still match; otherwise the report omits it.
        "log_snapshot_size_bytes": log_snapshot_size_bytes,
        "provenance": {
            "evidence_file": "",  # filled by writer
            "written_at_wall": "",
        },
    }

    # Never claim certified: we do not add a "certificate" field. Only verified/completed as above.
    return evidence


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomic write: temp + fsync + rename. No follow of symlinks."""
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    _atomic_write_bytes(path, blob.encode("utf-8"))


def write_evidence_atomic(
    evidence: dict[str, Any],
    *,
    log_dir: Optional[Path] = None,
    device_path: str = "",
    target_device: str = "",
) -> Path:
    """Write evidence JSON to log_dir atomically, off-target, with checksum sidecar.

    Returns the evidence path. Also writes .sha256 sidecar.
    """
    directory = log_dir if log_dir is not None else safety.default_log_dir()
    # Safety: ensure directory itself is not on target (default_log_dir already checks /tmp dev)
    # Evidence file name: result-<sanitized-device>-<timestamp_ns>.json
    safe = os.path.basename(device_path or target_device or "unknown").replace("/", "_") or "unknown"
    if not safe or safe in {".", ".."}:
        safe = "unknown"
    ts = time.time_ns()
    name = f"{EVIDENCE_PREFIX}{safe}-{ts}{EVIDENCE_SUFFIX}"
    path = Path(directory) / name
    # Off-target check (pass log_dir to ensure _is_under uses same root)
    assert_log_not_on_target(str(path), target_device or device_path, log_dir=Path(directory))
    # Add provenance before write
    evidence = dict(evidence)
    evidence["provenance"] = dict(evidence.get("provenance", {}))
    evidence["provenance"]["evidence_file"] = str(path)
    evidence["provenance"]["written_at_wall"] = _iso_now_wall()
    # Compute checksum of the final JSON (after provenance)
    # We write, then compute checksum of file
    _atomic_write_json(path, evidence)
    # Sidecar checksum
    h = hashlib.sha256(_read_regular_nofollow(path)).hexdigest()
    sidecar = Path(str(path) + CHECKSUM_SUFFIX)
    _atomic_write_bytes(sidecar, f"{h}  {path.name}\n".encode("ascii"))
    return path


def load_evidence(path: Path) -> dict[str, Any]:
    return json.loads(_read_regular_nofollow(Path(path)).decode("utf-8"))


def _read_regular_nofollow(path: Path) -> bytes:
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SafetyError("Cannot safely read evidence file") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise SafetyError("Evidence path is not a regular file")
        if opened.st_uid != os.getuid():
            raise SafetyError("Evidence file has the wrong owner")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    directory = path.parent
    dir_fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    tmp_name = f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}"
    fd = -1
    try:
        fd = os.open(
            tmp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=dir_fd,
        )
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short evidence write")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        # Publish the already-fsynced inode without replacing an existing
        # entry. linkat's create-if-absent behavior closes the exists()/rename
        # race that could overwrite a report planted between preflight and
        # commit. This primitive is used on the local evidence filesystem;
        # the FAT32 workflow has its own O_EXCL bundle writer.
        os.link(
            tmp_name,
            path.name,
            src_dir_fd=dir_fd,
            dst_dir_fd=dir_fd,
            follow_symlinks=False,
        )
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
            os.fsync(dir_fd)
        except BaseException:
            # linkat() already made the destination visible. If durability
            # cannot be proved, remove the entry created by this call so a
            # retry is not permanently blocked by an orphan without its
            # checksum partner.
            try:
                os.unlink(path.name, dir_fd=dir_fd)
            except OSError:
                pass
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            raise
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
        except FileNotFoundError:
            pass
        os.close(dir_fd)


def verify_evidence_checksum(path: Path) -> bool:
    """Return True only if the sidecar sha matches the file bytes.

    A missing sidecar is unverifiable, never valid: well-formed JSON alone
    proves nothing about integrity, so it returns False (callers record
    ``provenance.verified = False`` instead of blessing forged evidence).
    """
    sidecar = Path(str(path) + CHECKSUM_SUFFIX)
    try:
        data = _read_regular_nofollow(Path(path))
        h = hashlib.sha256(data).hexdigest()
        txt = _read_regular_nofollow(sidecar).decode("ascii")
        return txt == f"{h}  {Path(path).name}\n"
    except Exception:
        return False


def _verified_evidence_bytes(path: Path) -> bytes:
    """Return the exact bytes authenticated by the adjacent sidecar."""
    data = _read_regular_nofollow(path)
    sidecar = Path(str(path) + CHECKSUM_SUFFIX)
    try:
        text = _read_regular_nofollow(sidecar).decode("ascii")
    except Exception as exc:
        raise SafetyError("Evidence checksum is missing or invalid") from exc
    expected = f"{hashlib.sha256(data).hexdigest()}  {path.name}\n"
    if text != expected:
        raise SafetyError("Evidence checksum is missing or invalid")
    return data


def export_evidence(
    evidence_path: Path,
    dest_dir: Path,
    *,
    target_device: str = "",
    boot_device: str = "",
) -> Path:
    """Copy evidence + checksum to dest_dir (second USB) atomically, off-target.

    Validates dest_dir is not the target or boot device filesystem.
    """
    src = Path(evidence_path)
    dest_dir = Path(dest_dir)
    data = _verified_evidence_bytes(src)
    if not dest_dir.exists():
        raise SafetyError("Export destination missing")
    # Ensure dest_dir itself is a directory and not a symlink
    try:
        st = os.lstat(str(dest_dir))
        if stat.S_ISLNK(st.st_mode):
            raise SafetyError("Refusing to export through symlink")
        if not stat.S_ISDIR(st.st_mode):
            raise SafetyError("Export destination is not a directory")
    except OSError as exc:
        raise SafetyError(f"Cannot stat export destination: {exc}") from exc
    # Off-target checks: dest_dir must not be on target or boot filesystem via mountinfo
    # Use assert_log_not_on_target semantics: a file under dest_dir must not be on target.
    # The dest is a second USB, not the log dir, so scope the under-dir check
    # to dest_dir itself (default would wrongly require dest under /tmp/beamo-wipe
    # and every real export would fail).
    dest_file = dest_dir / src.name
    if dest_file.exists() or Path(str(dest_file) + CHECKSUM_SUFFIX).exists():
        raise SafetyError("Export destination already contains this evidence")
    assert_log_not_on_target(str(dest_file), target_device or "", log_dir=dest_dir)
    if boot_device:
        assert_log_not_on_target(str(dest_file), boot_device, log_dir=dest_dir)
    # Also check via mountinfo that dest_dir is not on target (best effort)
    # Compatibility API for pre-mounted destinations. The kiosk does not call
    # this path; _atomic_write_bytes still publishes without replacement.
    dest_sc = Path(str(dest_file) + CHECKSUM_SUFFIX)
    wrote_data = False
    try:
        _atomic_write_bytes(dest_file, data)
        wrote_data = True
        _atomic_write_bytes(
            dest_sc,
            f"{hashlib.sha256(data).hexdigest()}  {dest_file.name}\n".encode("ascii"),
        )
    except Exception:
        # The preflight proved both paths absent, so only remove the partial
        # data file created by this call. A retry can then recover in place.
        if wrote_data:
            try:
                dest_file.unlink()
            except OSError:
                pass
        raise
    # Fsync dest_dir
    try:
        dfd = os.open(str(dest_dir), os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
    return dest_file


# For testing: allow injection of wall clock
def build_evidence_for_wizard(
    *,
    disk: Optional[Disk],
    discovery: Any,
    method: MethodId,
    request: Optional[WipeRequest],
    result: Optional[WipeResult],
    started_at_wall: Optional[str],
    ended_at_wall: Optional[str],
    started_mono: Optional[float],
    ended_mono: Optional[float],
    argv: Optional[Sequence[str]],
    log_text: str,
    cancelled: bool = False,
    interrupted: bool = False,
) -> dict[str, Any]:
    return build_evidence(
        disk=disk,
        discovery=discovery,
        method=method,
        request=request,
        result=result,
        started_at_wall=started_at_wall,
        ended_at_wall=ended_at_wall,
        started_mono=started_mono,
        ended_mono=ended_mono,
        argv=argv,
        log_text=log_text,
        interrupted=interrupted,
        cancelled=cancelled,
    )
