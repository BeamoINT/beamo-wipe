# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured diagnostics. Safe, truncated, no secrets."""

from __future__ import annotations

import json
import os
import stat
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

# No secrets: we never log full device paths with serials, full logs, or env dumps.
# We log area, code, truncated message (first 300 chars, no newlines), and wall time.

DIAG_LOG_MAX_BYTES = 256 * 1024
DIAG_DETAIL_MAX = 300


def _sanitize_detail(text: str) -> str:
    # Safe: strip control chars, truncate, no secrets
    if not text:
        return ""
    # Replace all Unicode control/format characters. This includes bidi
    # overrides and C1 terminal controls, not just newlines and NUL.
    s = "".join(
        " " if unicodedata.category(ch).startswith("C") else ch
        for ch in str(text)
    )
    # Never log full nwipe log contents here; caller must truncate before passing
    if len(s) > DIAG_DETAIL_MAX:
        s = s[: DIAG_DETAIL_MAX - 3] + "..."
    return s.strip()


def log_diag(
    area: str,
    code: str,
    detail: str = "",
    *,
    log_dir: Optional[Path] = None,
    device: Optional[str] = None,
    logfile: Optional[str] = None,
    rdev: Optional[int] = None,
    request_id: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> bool:
    """Append one JSON line to diagnostics.log. Returns True on success.

    Structured fields (device, logfile, rdev, request_id, extra) let maintainers
    correlate without parsing free-form detail. All values are sanitized and
    truncated; full serials/logs are never stored. Falls back to stderr on
    failure so swallowed errors become visible. Never raises.
    """
    try:
        from beamo_wipe.safety import default_log_dir

        directory = log_dir if log_dir is not None else default_log_dir()
    except Exception:
        # Never bypass default_log_dir's ownership, no-symlink and filesystem
        # checks by recreating the same raw /tmp path. Diagnostics are optional;
        # a sanitized stderr line is the only safe fallback.
        try:
            import sys

            print(
                f"beamo-wipe [{_sanitize_detail(area)[:64]}] "
                f"{_sanitize_detail(code)[:64]}: {_sanitize_detail(detail)[:80]}",
                file=sys.stderr,
            )
        except Exception:
            pass
        return False
    # Atomic append: open with O_APPEND, write, fsync; best-effort
    path = Path(directory) / "diagnostics.log"
    # Sanitize structured fields (basename only, no serials)
    entry: dict[str, Any] = {
        "ts_wall": _iso_now(),
        "ts_mono": time.monotonic(),
        "area": _sanitize_detail(area)[:64],
        "code": _sanitize_detail(code)[:64],
        "detail": _sanitize_detail(detail),
        "pid": os.getpid(),
    }
    if device is not None:
        # Only basename to avoid leaking serials; full path not needed for correlation
        try:
            entry["device"] = _sanitize_detail(os.path.basename(str(device)))[:32]
        except Exception:
            pass
    if logfile is not None:
        try:
            entry["logfile"] = _sanitize_detail(os.path.basename(str(logfile)))[:64]
        except Exception:
            pass
    if rdev is not None:
        try:
            entry["rdev"] = int(rdev)
        except Exception:
            pass
    if request_id is not None:
        entry["request_id"] = _sanitize_detail(str(request_id))[:32]
    if extra is not None:
        try:
            # Only allow primitive values, truncate any string values
            safe_extra: dict[str, str] = {}
            for k, v in list(extra.items())[:8]:
                sk = _sanitize_detail(str(k))[:32]
                sv = _sanitize_detail(str(v))[:128]
                if sk:
                    safe_extra[sk] = sv
            if safe_extra:
                entry["extra"] = safe_extra
        except Exception:
            pass
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        # Use O_NOFOLLOW to avoid symlink, O_APPEND to atomically append
        # If file doesn't exist, create 0o600; if exists, append.
        # O_RDWR (not O_WRONLY): the size-bound rotation below must read the
        # tail through this fd; a write-only fd fails the read with EBADF.
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError("diagnostics path is not a regular file")
            if opened.st_uid != os.getuid():
                raise OSError("diagnostics path has the wrong owner")
            if stat.S_IMODE(opened.st_mode) != 0o600:
                os.fchmod(fd, 0o600)
            os.write(fd, line.encode("utf-8"))
            # Do not fsync every diagnostic; best-effort
            try:
                os.fsync(fd)
            except OSError:
                pass
            # Bound the log: keep the last half once over max size.
            # Best-effort and loss-tolerant (diagnostics only): a concurrent
            # appender may interleave, but growth stays bounded either way.
            try:
                st = os.fstat(fd)
                if st.st_size > DIAG_LOG_MAX_BYTES:
                    keep = DIAG_LOG_MAX_BYTES // 2
                    os.lseek(fd, -keep, os.SEEK_END)
                    tail = b""
                    while len(tail) < keep:
                        chunk = os.read(fd, keep - len(tail))
                        if not chunk:
                            break
                        tail += chunk
                    os.ftruncate(fd, 0)
                    # O_APPEND lands at end (offset 0 after truncate)
                    os.write(fd, tail)
            except OSError:
                pass
        finally:
            os.close(fd)
        return True
    except OSError as exc:
        # Fallback to stderr so failure is visible to maintainer (sanitized:
        # no newlines, no control chars, truncated — same contract as JSON).
        try:
            import sys

            print(
                f"beamo-wipe [{_sanitize_detail(area)[:64]}] "
                f"{_sanitize_detail(code)[:64]} "
                f"(diag_write_failed:{type(exc).__name__}): "
                f"{_sanitize_detail(detail)[:80]}",
                file=sys.stderr,
            )
        except Exception:
            pass
        return False


def _iso_now() -> str:
    import datetime

    try:
        return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def read_diagnostics(log_dir: Optional[Path] = None, limit: int = 100) -> list[dict[str, Any]]:
    """Read last `limit` diagnostic lines. For support export; never raises."""
    try:
        from beamo_wipe.safety import default_log_dir

        directory = log_dir if log_dir is not None else default_log_dir()
    except Exception:
        return []
    path = Path(directory) / "diagnostics.log"
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid():
                return []
            with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as stream:
                fd = -1
                text = stream.read(DIAG_LOG_MAX_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    except OSError:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    out: list[dict[str, Any]] = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out
