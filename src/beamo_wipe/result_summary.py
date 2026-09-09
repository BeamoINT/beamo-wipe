# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic plain-text result summary from validated evidence only."""

from __future__ import annotations

import math
import os
import re
import unicodedata
from typing import Any, Mapping

from beamo_wipe.identity import HARDWARE_ID_LABEL, SERIAL_LABEL, SERIAL_NOT_REPORTED
from beamo_wipe.outcomes import present_evidence
from beamo_wipe.progress import duration

UNAVAILABLE = "unavailable"
WITHHELD = "withheld"
MAX_VALUE = 240
WALL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
RESULT_FILE_RE = re.compile(r"^result-[A-Za-z0-9._-]{1,120}\.json$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

def sanitize_value(text: object, *, limit: int = MAX_VALUE) -> str:
    """Flatten untrusted text so it cannot inject headings or control codes."""
    if not isinstance(text, str):
        return UNAVAILABLE
    chars = []
    for ch in text.replace("\r\n", "\n").replace("\r", "\n"):
        category = unicodedata.category(ch)
        if ch in "\n\t" or category in {"Zl", "Zp"}:
            chars.append(" ")
            continue
        if category.startswith("C"):
            continue
        chars.append(ch)
    cleaned = " ".join("".join(chars).split())
    if not cleaned:
        return UNAVAILABLE
    if len(cleaned) > limit:
        return cleaned[:limit].rstrip() + " (truncated)"
    return cleaned


def encode_summary(text: str) -> bytes:
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if not body.endswith("\n"):
        body += "\n"
    return body.replace("\n", "\r\n").encode("utf-8")


def _text(value: object) -> str:
    got = sanitize_value(value)
    return got


def _optional_text(mapping: Mapping[str, Any], key: str) -> str:
    if key not in mapping:
        return UNAVAILABLE
    return _text(mapping.get(key))


def _int_text(value: object) -> str:
    if type(value) is int and not isinstance(value, bool) and value >= 0:
        return str(value)
    return UNAVAILABLE


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _wall(value: object) -> str:
    if not isinstance(value, str) or not WALL_RE.fullmatch(value):
        return UNAVAILABLE
    return value


def _elapsed(timestamps: object) -> str:
    """Prefer monotonic stamps. Wall time is never used for elapsed duration."""
    if not isinstance(timestamps, dict):
        return UNAVAILABLE
    started = _finite_number(timestamps.get("started_monotonic"))
    ended = _finite_number(timestamps.get("ended_monotonic"))
    if started is not None and ended is not None and ended >= started:
        return duration(ended - started)
    seconds = _finite_number(timestamps.get("duration_s"))
    if seconds is None:
        return UNAVAILABLE
    return duration(seconds)


def _secrets(device: Mapping[str, Any]) -> tuple[str, ...]:
    found = []
    for key in ("serial", "wwn", "path", "realpath"):
        value = device.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.strip())
    return tuple(sorted(set(found), key=len, reverse=True))


def _maybe_withhold(value: str) -> str:
    if value in {UNAVAILABLE, SERIAL_NOT_REPORTED}:
        return value
    return WITHHELD


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    out = text
    for secret in secrets:
        out = out.replace(secret, WITHHELD)
    return out


def _report_file(evidence: Mapping[str, Any]) -> str:
    provenance = evidence.get("provenance")
    if not isinstance(provenance, dict):
        return UNAVAILABLE
    raw = provenance.get("evidence_file")
    if not isinstance(raw, str) or not raw:
        return UNAVAILABLE
    name = os.path.basename(raw.replace("\\", "/"))
    if not RESULT_FILE_RE.fullmatch(name):
        return UNAVAILABLE
    return name


def _disk_lines(evidence: Mapping[str, Any], *, redacted: bool) -> list[tuple[str, str]]:
    device = evidence.get("device") if isinstance(evidence.get("device"), dict) else {}
    presentation = (
        evidence.get("device_presentation")
        if isinstance(evidence.get("device_presentation"), dict)
        else {}
    )
    secrets = _secrets(device) if redacted else ()
    title = _optional_text(presentation, "title")
    if title == UNAVAILABLE:
        title = _optional_text(device, "model")
    capacity = _optional_text(presentation, "capacity")
    if capacity == UNAVAILABLE:
        label = _optional_text(device, "size_gb_label")
        capacity = f"{label} GB" if label != UNAVAILABLE else UNAVAILABLE
    connection = _optional_text(presentation, "connection")
    if connection == UNAVAILABLE:
        connection = _optional_text(device, "bus")
    serial = _optional_text(device, "serial")
    hardware = _optional_text(device, "wwn")
    presented = _optional_text(presentation, "id_value")
    label = _optional_text(presentation, "id_label")
    if serial == UNAVAILABLE and label == SERIAL_LABEL:
        serial = presented
    if hardware == UNAVAILABLE and label == HARDWARE_ID_LABEL:
        hardware = presented
    if redacted:
        title = _scrub(title, secrets)
        capacity = _scrub(capacity, secrets)
        connection = _scrub(connection, secrets)
        serial = _maybe_withhold(serial)
        hardware = _maybe_withhold(hardware)
    return [
        ("Disk", title),
        ("Capacity", capacity),
        ("Connection", connection),
        (SERIAL_LABEL, serial if serial else UNAVAILABLE),
        (HARDWARE_ID_LABEL, hardware if hardware else UNAVAILABLE),
    ]


def _method_lines(evidence: Mapping[str, Any]) -> list[tuple[str, str]]:
    method = evidence.get("method") if isinstance(evidence.get("method"), dict) else {}
    title = _optional_text(method, "title")
    summary = _optional_text(method, "operation_summary")
    if title != UNAVAILABLE and summary != UNAVAILABLE:
        method_line = f"{title}. {summary}"
    elif summary != UNAVAILABLE:
        method_line = summary
    else:
        method_line = title
    overwrites = _int_text(method.get("overwrite_passes"))
    return [("Method", method_line), ("Overwrites", overwrites)]


def _warnings(evidence: Mapping[str, Any], secrets: tuple[str, ...]) -> str:
    raw = evidence.get("warnings")
    if "warnings" not in evidence:
        return UNAVAILABLE
    if not isinstance(raw, list):
        return UNAVAILABLE
    items = []
    for item in raw:
        text = sanitize_value(item)
        if text == UNAVAILABLE:
            continue
        if secrets:
            text = _scrub(text, secrets)
        items.append(text)
    if not items:
        return "None recorded"
    return "\n".join(f"- {item}" for item in items)


def _limitations(evidence: Mapping[str, Any]) -> str:
    view = present_evidence(evidence)
    step = sanitize_value(view.next_step) if view.next_step else UNAVAILABLE
    if step != UNAVAILABLE:
        return step
    verification = (
        evidence.get("verification") if isinstance(evidence.get("verification"), dict) else {}
    )
    return _optional_text(verification, "scope")


def _verification_status(evidence: Mapping[str, Any]) -> str:
    view = present_evidence(evidence)
    if view.code == "verified":
        return "Read-back verification passed"
    if view.code == "unverified":
        return "Verification was not performed"
    if view.code == "verification_failed":
        return view.message
    return UNAVAILABLE


def _application(evidence: Mapping[str, Any]) -> list[tuple[str, str]]:
    name = "Beamo Wipe"
    version = _optional_text(evidence, "beamo_wipe_version")
    application = name if version == UNAVAILABLE else f"{name} {version}"
    engine_version = _optional_text(evidence, "nwipe_version")
    engine = UNAVAILABLE if engine_version == UNAVAILABLE else f"nwipe {engine_version}"
    commit = evidence.get("nwipe_commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        commit_text = UNAVAILABLE
    else:
        commit_text = commit
    return [
        ("Application", application),
        ("Engine", engine),
        ("Engine commit", commit_text),
    ]


def build_result_summary(
    evidence: object,
    *,
    evidence_sha256: str = "",
    redacted: bool = False,
) -> str:
    """Stable labeled summary. Headings never come from evidence or logs."""
    payload = evidence if isinstance(evidence, dict) else {}
    view = present_evidence(payload)
    device = payload.get("device") if isinstance(payload.get("device"), dict) else {}
    secrets = _secrets(device) if redacted else ()
    checksum = evidence_sha256 if HEX64_RE.fullmatch(evidence_sha256 or "") else UNAVAILABLE
    timestamps = payload.get("timestamps") if isinstance(payload.get("timestamps"), dict) else {}
    lines: list[str] = [
        "Sharing copy. Serials and hardware IDs withheld."
        if redacted
        else "Beamo Wipe result"
    ]
    fields: list[tuple[str, str]] = [
        ("Report file", _report_file(payload)),
        ("Report checksum", checksum),
        *_disk_lines(payload, redacted=redacted),
        *_method_lines(payload),
        ("Elapsed", _elapsed(timestamps)),
        ("Result", view.message),
        ("Verification", _verification_status(payload)),
        ("Warnings", _warnings(payload, secrets)),
        ("Limitations", _limitations(payload)),
        *_application(payload),
        ("Started (clock not verified)", _wall(timestamps.get("started_at_wall"))),
        ("Ended (clock not verified)", _wall(timestamps.get("ended_at_wall"))),
    ]
    for label, value in fields:
        if "\n" in value:
            lines.append(f"{label}:")
            lines.extend(value.split("\n"))
        else:
            lines.append(f"{label}: {value}")
    text = "\n".join(lines)
    if redacted:
        text = _scrub(text, secrets)
    return text
