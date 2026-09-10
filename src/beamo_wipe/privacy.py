# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned allowlist for a privacy-reduced sharing copy.

The owner's original evidence bytes are never mutated. A sharing copy is a
new document that keeps outcome, method, duration, verification, warnings,
safe build identity, and support codes, and drops disk identifiers, paths,
host details, and engine logs.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

POLICY_VERSION = 1
POLICY_ID = "beamo-wipe-sharing-v1"
SHARE_JSON = "SHARE.json"
SHARE_SUMMARY = "SHARE.txt"
WITHHELD = "withheld"
NOTICE = (
    "Privacy-reduced sharing copy. Not identity evidence. "
    "Do not use this copy where a serial, hardware ID, or device path is required."
)
UNSUITABLE = (
    "Unsuitable where full identity evidence is required. "
    "Use the original report for serials, hardware IDs, or device paths."
)

_IDENTIFIER_DEVICE_KEYS = ("serial", "wwn", "path", "realpath", "name", "label")
_KEEP_ROOT = frozenset(
    {
        "schema_version",
        "beamo_wipe_version",
        "source_commit",
        "build_id",
        "build_status",
        "source_dirty",
        "nwipe_version",
        "nwipe_commit",
        "outcome",
        "completion",
        "failure_reason",
        "device",
        "device_presentation",
        "method",
        "timestamps",
        "nwipe",
        "exit_evidence",
        "verification",
        "warnings",
        "interruption",
        "presentation",
        "result_description",
    }
)
_KEEP_DEVICE = frozenset({"model", "size_bytes", "size_gb_label", "kind", "bus"})
_KEEP_DEVICE_PRESENTATION = frozenset({"title", "capacity", "connection", "kind"})
_KEEP_METHOD = frozenset(
    {
        "id",
        "nwipe_method",
        "rounds",
        "verify",
        "noblank",
        "docs_name",
        "title",
        "overwrite_passes",
        "verification_passes",
        "description",
        "operation_summary",
    }
)
_KEEP_TIMESTAMPS = frozenset(
    {
        "started_at_wall",
        "ended_at_wall",
        "started_monotonic",
        "ended_monotonic",
        "duration_s",
        "duration_source",
        "wall_confidence",
        "wall_provenance",
    }
)
_KEEP_NWIPE = frozenset({"version"})
_KEEP_EXIT = frozenset({"exit_code", "signal"})
_KEEP_VERIFICATION = frozenset({"requested", "verified", "scope"})
_KEEP_COMPLETION = frozenset({"validated", "reason"})
_KEEP_INTERRUPTION = frozenset({"interrupted", "cancelled", "origin"})
_KEEP_PRESENTATION = frozenset(
    {"code", "message", "next_step", "tone", "icon", "success"}
)


def is_sharing_copy(evidence: object) -> bool:
    if not isinstance(evidence, dict):
        return False
    privacy = evidence.get("privacy")
    return (
        isinstance(privacy, dict)
        and privacy.get("copy") == "sharing"
        and privacy.get("unsuitable_for_identity_evidence") is True
        and privacy.get("policy_version") == POLICY_VERSION
        and privacy.get("policy") == POLICY_ID
    )


def collect_secrets(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    found: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str):
            text = value.strip()
            if text:
                found.append(text)
                base = os.path.basename(text.replace("\\", "/")).strip()
                if base and base != text:
                    found.append(base)

    device = evidence.get("device") if isinstance(evidence.get("device"), dict) else {}
    for key in _IDENTIFIER_DEVICE_KEYS:
        add(device.get(key))
    add(evidence.get("boot_device"))
    add(evidence.get("logfile"))
    provenance = (
        evidence.get("provenance") if isinstance(evidence.get("provenance"), dict) else {}
    )
    add(provenance.get("evidence_file"))
    presentation = (
        evidence.get("device_presentation")
        if isinstance(evidence.get("device_presentation"), dict)
        else {}
    )
    add(presentation.get("id_value"))
    add(presentation.get("system_path"))
    nwipe = evidence.get("nwipe") if isinstance(evidence.get("nwipe"), dict) else {}
    argv = nwipe.get("argv_redacted")
    if isinstance(argv, list):
        for item in argv:
            if isinstance(item, str) and item.startswith("/dev/"):
                add(item)
    unique = sorted(set(found), key=len, reverse=True)
    return tuple(unique)


def _scrub(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        out = value
        for secret in secrets:
            out = out.replace(secret, WITHHELD)
        return out
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item, secrets) for key, item in value.items()}
    return value


def _pick(mapping: Mapping[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    return {key: mapping[key] for key in allowed if key in mapping}


def make_sharing_copy(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Build a new sharing document. Does not mutate ``evidence``."""
    secrets = collect_secrets(evidence)
    root = _pick(evidence, _KEEP_ROOT)
    if isinstance(root.get("device"), dict):
        root["device"] = _pick(root["device"], _KEEP_DEVICE)
    if isinstance(root.get("device_presentation"), dict):
        root["device_presentation"] = _pick(
            root["device_presentation"], _KEEP_DEVICE_PRESENTATION
        )
    if isinstance(root.get("method"), dict):
        root["method"] = _pick(root["method"], _KEEP_METHOD)
    if isinstance(root.get("timestamps"), dict):
        root["timestamps"] = _pick(root["timestamps"], _KEEP_TIMESTAMPS)
    if isinstance(root.get("nwipe"), dict):
        root["nwipe"] = _pick(root["nwipe"], _KEEP_NWIPE)
    if isinstance(root.get("exit_evidence"), dict):
        root["exit_evidence"] = _pick(root["exit_evidence"], _KEEP_EXIT)
    if isinstance(root.get("verification"), dict):
        root["verification"] = _pick(root["verification"], _KEEP_VERIFICATION)
    if isinstance(root.get("completion"), dict):
        root["completion"] = _pick(root["completion"], _KEEP_COMPLETION)
    if isinstance(root.get("interruption"), dict):
        root["interruption"] = _pick(root["interruption"], _KEEP_INTERRUPTION)
    if isinstance(root.get("presentation"), dict):
        root["presentation"] = _pick(root["presentation"], _KEEP_PRESENTATION)
    root["privacy"] = {
        "policy_version": POLICY_VERSION,
        "policy": POLICY_ID,
        "copy": "sharing",
        "unsuitable_for_identity_evidence": True,
        "notice": NOTICE,
    }
    return _scrub(root, secrets)  # type: ignore[return-value]


def encode_sharing_copy(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
