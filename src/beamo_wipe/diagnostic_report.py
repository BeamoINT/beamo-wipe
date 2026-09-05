# SPDX-License-Identifier: GPL-3.0-or-later
"""Allowlisted support diagnostics. Never erase evidence or a raw log export."""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import time

from beamo_wipe import __version__, NWIPE_PINNED_COMMIT, NWIPE_PINNED_VERSION
from beamo_wipe.safety import SafetyError

MAX_BYTES = 16 * 1024
MAX_EVENTS = 32
BUILD_PATH = Path("/usr/share/beamo-wipe/build-identity.json")
CODES = frozenset(
    {
        "startup_refused",
        "dependency_missing",
        "permission_denied",
        "io_failed",
        "discovery_timeout",
        "discovery_command_failed",
        "discovery_invalid",
        "discovery_failed",
        "boot_unidentified",
        "no_eligible_disks",
        "refresh_failed",
        "rediscovery_failed",
        "identity_rejected",
        "preflight_rejected",
        "engine_start_failed",
        "graphical_unavailable",
        "unexpected_startup_failure",
    }
)
TITLE = "Diagnostic report — wipe could not start"
NOTICE = (
    "Support diagnostics only. This is not erase evidence and does not establish "
    "that an operation ran. No disk identifiers or raw logs are included."
)
PREPARE = (
    "Leave all existing disks connected. Remove the report USB, then choose "
    "Prepare. After the baseline is checked, insert one separate removable FAT32 USB."
)


def exception_code(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "dependency_missing"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, subprocess.TimeoutExpired):
        return "discovery_timeout"
    if isinstance(exc, subprocess.CalledProcessError):
        return "discovery_command_failed"
    if isinstance(exc, (ValueError, TypeError, AttributeError)):
        return "discovery_invalid"
    if isinstance(exc, SafetyError):
        return "startup_refused"
    if isinstance(exc, OSError):
        return "io_failed"
    return "unexpected_startup_failure"


def runtime_source_sha256() -> str | None:
    """Hash installed application bytes with the release manifest's framing."""
    root = Path(__file__).parent
    digest = hashlib.sha256()
    total = 0
    try:
        paths = sorted(root.rglob("*"))
        if len(paths) > 512:
            return None
        for path in paths:
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_symlink():
                return None
            if not path.is_file():
                continue
            from beamo_wipe.support_export import _read_at

            fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                data = _read_at(fd, path.name, limit=4 * 1024 * 1024)
            finally:
                os.close(fd)
            total += len(data)
            if total > 16 * 1024 * 1024:
                return None
            name = ("src/beamo_wipe/" + path.relative_to(root).as_posix()).encode()
            sha = hashlib.sha256(data).hexdigest().encode()
            digest.update(f"{len(name)}:".encode() + name)
            digest.update(f"{len(sha)}:".encode() + sha)
        return digest.hexdigest() if total else None
    except (OSError, SafetyError):
        return None


def application_identity() -> dict:
    # Build metadata contains only immutable source/build digests; never use
    # runtime environment overrides, hostname, uname release, or machine IDs.
    identity: dict = {
        "name": "Beamo Wipe",
        "version": __version__,
        "nwipe_pinned_version": NWIPE_PINNED_VERSION,
        "nwipe_pinned_commit": NWIPE_PINNED_COMMIT,
        "build_status": "unavailable",
        "build": {},
        "runtime_source_sha256": runtime_source_sha256(),
    }
    try:
        from beamo_wipe.support_export import _read_at

        fd = os.open(
            str(BUILD_PATH.parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            raw = _read_at(fd, BUILD_PATH.name, limit=4096)
        finally:
            os.close(fd)
        build = json.loads(raw)
        if (
            set(build) != {"source_commit", "source_sha256", "build_id", "source_dirty"}
            or not re.fullmatch(r"[0-9a-f]{40}", build["source_commit"])
            or not re.fullmatch(r"[0-9a-f]{64}", build["source_sha256"])
            or not re.fullmatch(
                r"(?:[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}|local)",
                build["build_id"],
            )
            or type(build["source_dirty"]) is not bool
        ):
            return identity
        identity.update(
            build_status="recorded"
            if build["source_sha256"] == identity["runtime_source_sha256"]
            else "source_mismatch",
            build=build,
        )
    except (OSError, SafetyError, ValueError, TypeError, KeyError):
        pass
    return identity


def create_report(code: str, discovery, *, ui: str, session_started: float) -> bytes:
    if code not in CODES or ui not in {"graphical", "accessible", "console"}:
        raise SafetyError("Invalid diagnostic classification.")
    try:
        wall = (
            datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OSError, ValueError, OverflowError):
        wall = None
    duration = time.monotonic() - session_started
    elapsed = round(duration, 3) if math.isfinite(duration) and duration >= 0 else None
    # An offline RTC is not evidence of correct calendar time. We make no NTP
    # probe and never infer confidence from a plausible-looking date.
    clock = {
        "recorded_at_utc": wall,
        "wall_confidence": "unverified" if wall else "unavailable",
        "session_elapsed_seconds": elapsed,
        "elapsed_source": "monotonic",
    }
    status = (
        "failed"
        if discovery.error
        else "boot_unidentified"
        if not discovery.boot_identified or discovery.boot is None
        else "no_eligible_disks"
        if not discovery.selectable
        else "ready"
    )
    if code in {"rediscovery_failed", "refresh_failed", "identity_rejected"}:
        status = "failed"
    arch = platform.machine()
    system = platform.system()
    payload = {
        "schema_version": 1,
        "report_type": "startup_diagnostic",
        "title": TITLE,
        "notice": NOTICE,
        "application": application_identity(),
        "error_code": code,
        "discovery": {
            "status": status,
            "boot_identified": bool(
                discovery.boot_identified
                and discovery.boot is not None
                and status not in {"failed", "boot_unidentified"}
            ),
        },
        "time": clock,
        "environment": {
            "ui": ui,
            "architecture": arch
            if arch in {"x86_64", "aarch64", "arm64", "i686"}
            else "other",
            "system": system if system in {"Linux", "Darwin", "Windows"} else "other",
        },
        "events": [{"code": code}],
        "raw_logs": "omitted",
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def validate_report(data: bytes) -> dict:
    """Reject added fields, raw logs and identifiers even at the worker boundary."""
    try:
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
            raise ValueError()
        p = json.loads(data)
        if set(p) != {
            "schema_version",
            "report_type",
            "title",
            "notice",
            "application",
            "error_code",
            "discovery",
            "time",
            "environment",
            "events",
            "raw_logs",
        }:
            raise ValueError()
        if (
            type(p["schema_version"]) is not int
            or p["schema_version"] != 1
            or p["report_type"] != "startup_diagnostic"
            or p["title"] != TITLE
            or p["notice"] != NOTICE
            or p["raw_logs"] != "omitted"
            or p["error_code"] not in CODES
        ):
            raise ValueError()
        # Reconstruct the permitted nested schema; equality prevents any
        # extension from silently becoming an identifier-export channel.
        app = p["application"]
        if set(app) != {
            "name",
            "version",
            "nwipe_pinned_version",
            "nwipe_pinned_commit",
            "build_status",
            "build",
            "runtime_source_sha256",
        }:
            raise ValueError()
        if (
            app["name"] != "Beamo Wipe"
            or app["version"] != __version__
            or app["nwipe_pinned_version"] != NWIPE_PINNED_VERSION
            or app["nwipe_pinned_commit"] != NWIPE_PINNED_COMMIT
        ):
            raise ValueError()
        if app != application_identity():
            raise ValueError()
        d = p["discovery"]
        if (
            set(d) != {"status", "boot_identified"}
            or type(d["boot_identified"]) is not bool
            or d["status"]
            not in {"failed", "boot_unidentified", "no_eligible_disks", "ready"}
        ):
            raise ValueError()
        e = p["environment"]
        if (
            set(e) != {"ui", "architecture", "system"}
            or e["ui"] not in {"graphical", "accessible", "console"}
            or e["architecture"] not in {"x86_64", "aarch64", "arm64", "i686", "other"}
            or e["system"] not in {"Linux", "Darwin", "Windows", "other"}
        ):
            raise ValueError()
        t = p["time"]
        if set(t) != {
            "recorded_at_utc",
            "wall_confidence",
            "session_elapsed_seconds",
            "elapsed_source",
        }:
            raise ValueError()
        wall = t["recorded_at_utc"]
        if wall is not None:
            if not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", wall
            ):
                raise ValueError()
            datetime.datetime.fromisoformat(wall.replace("Z", "+00:00"))
        if (
            t["wall_confidence"] != ("unverified" if wall else "unavailable")
            or t["elapsed_source"] != "monotonic"
        ):
            raise ValueError()
        elapsed = t["session_elapsed_seconds"]
        if elapsed is not None and (
            type(elapsed) not in {int, float}
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise ValueError()
        if not isinstance(p["events"], list) or not 1 <= len(p["events"]) <= MAX_EVENTS:
            raise ValueError()
        if any(
            set(event) != {"code"} or event["code"] not in CODES
            for event in p["events"]
        ):
            raise ValueError()
        return p
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise SafetyError("Invalid or unsanitized diagnostic report.") from exc


def verified_report(data: bytes):
    from beamo_wipe.support_export import VerifiedEvidence

    validate_report(data)
    return VerifiedEvidence(data, hashlib.sha256(data).hexdigest(), "", "", "", 0)
