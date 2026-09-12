# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable wrapper build identity. One injection path; never inferred at runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from beamo_wipe.safety import SafetyError

BUILD_PATH = Path("/usr/share/beamo-wipe/build-identity.json")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BUILD_ID_RE = re.compile(
    r"^(?:[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}|local)$"
)
FILE_KEYS = frozenset({"source_commit", "source_sha256", "build_id", "source_dirty"})
STATUSES = frozenset(
    {"production", "development", "dirty", "source_mismatch", "unavailable"}
)
STATUS_UNAVAILABLE = "unavailable"
STATUS_PRODUCTION = "production"
STATUS_DEVELOPMENT = "development"
STATUS_DIRTY = "dirty"
STATUS_MISMATCH = "source_mismatch"


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


def parse_injected_build(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or set(raw) != FILE_KEYS:
        return None
    commit = raw.get("source_commit")
    digest = raw.get("source_sha256")
    build_id = raw.get("build_id")
    dirty = raw.get("source_dirty")
    if (
        not isinstance(commit, str)
        or not COMMIT_RE.fullmatch(commit)
        or not isinstance(digest, str)
        or not SHA256_RE.fullmatch(digest)
        or not isinstance(build_id, str)
        or not BUILD_ID_RE.fullmatch(build_id)
        or type(dirty) is not bool
    ):
        return None
    return {
        "source_commit": commit,
        "source_sha256": digest,
        "build_id": build_id,
        "source_dirty": dirty,
    }


def classify_status(
    *,
    build_id: str,
    source_dirty: bool,
    source_sha256: str,
    runtime_sha256: str | None,
) -> str:
    if source_dirty:
        return STATUS_DIRTY
    if not runtime_sha256 or source_sha256 != runtime_sha256:
        return STATUS_MISMATCH
    if build_id == "local":
        return STATUS_DEVELOPMENT
    return STATUS_PRODUCTION


def load_injected_build(path: Path | None = None) -> dict[str, Any] | None:
    """Read the single injection file. Missing or invalid is unavailable."""
    target = path if path is not None else BUILD_PATH
    try:
        from beamo_wipe.support_export import _read_at

        fd = os.open(str(target.parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            raw = _read_at(fd, target.name, limit=4096)
        finally:
            os.close(fd)
        return parse_injected_build(json.loads(raw))
    except (
        OSError,
        SafetyError,
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None


def injected_payload(
    *,
    source_commit: str,
    source_sha256: str,
    build_id: str,
    source_dirty: bool,
) -> dict[str, Any]:
    payload = parse_injected_build(
        {
            "source_commit": source_commit,
            "source_sha256": source_sha256,
            "build_id": build_id,
            "source_dirty": source_dirty,
        }
    )
    if payload is None:
        raise RuntimeError("invalid build identity")
    return payload


def assert_injectable(
    *,
    build_id: str,
    source_dirty: bool,
    allow_dirty: bool,
    hosted: bool,
) -> None:
    if not BUILD_ID_RE.fullmatch(build_id):
        raise RuntimeError("invalid build identity")
    if hosted and build_id == "local":
        raise RuntimeError("hosted production image requires BUILD_ID")
    if build_id != "local" and source_dirty and not allow_dirty:
        raise RuntimeError("production image refuses dirty source")


def write_injected(
    path: Path,
    *,
    source_commit: str,
    source_sha256: str,
    build_id: str,
    source_dirty: bool,
    allow_dirty: bool = False,
    hosted: bool = False,
) -> dict[str, Any]:
    assert_injectable(
        build_id=build_id,
        source_dirty=source_dirty,
        allow_dirty=allow_dirty,
        hosted=hosted,
    )
    payload = injected_payload(
        source_commit=source_commit,
        source_sha256=source_sha256,
        build_id=build_id,
        source_dirty=source_dirty,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="ascii")
    return payload


def empty_build(runtime: str | None = None) -> dict[str, Any]:
    return {
        "status": STATUS_UNAVAILABLE,
        "source_commit": "",
        "source_sha256": "",
        "build_id": "",
        "source_dirty": False,
        "runtime_source_sha256": runtime or "",
    }


def load_build(path: Path | None = None) -> dict[str, Any]:
    """Closed identity for evidence and summaries. Never uses env or git."""
    runtime = runtime_source_sha256()
    injected = load_injected_build(path)
    if injected is None:
        return empty_build(runtime)
    status = classify_status(
        build_id=injected["build_id"],
        source_dirty=injected["source_dirty"],
        source_sha256=injected["source_sha256"],
        runtime_sha256=runtime,
    )
    return {
        "status": status,
        "source_commit": injected["source_commit"],
        "source_sha256": injected["source_sha256"],
        "build_id": injected["build_id"],
        "source_dirty": injected["source_dirty"],
        "runtime_source_sha256": runtime or "",
    }


def evidence_identity(build: Mapping[str, Any] | None = None) -> dict[str, Any]:
    record = dict(build) if build is not None else load_build()
    status = record.get("status")
    if status not in STATUSES:
        record = empty_build(record.get("runtime_source_sha256") or None)
        status = STATUS_UNAVAILABLE
    commit = record.get("source_commit") if COMMIT_RE.fullmatch(str(record.get("source_commit") or "")) else ""
    build_id = record.get("build_id") if BUILD_ID_RE.fullmatch(str(record.get("build_id") or "")) else ""
    if status == STATUS_UNAVAILABLE:
        commit = ""
        build_id = ""
    return {
        "source_commit": commit,
        "build_id": build_id,
        "build_status": status,
        "source_dirty": bool(record.get("source_dirty")) if status != STATUS_UNAVAILABLE else False,
    }
