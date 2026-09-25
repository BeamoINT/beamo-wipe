# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic plain-text result summary from validated evidence only."""

from __future__ import annotations

import html
import math
import os
import re
import unicodedata
from typing import Any, Mapping

from beamo_wipe.build_identity import BUILD_ID_RE, COMMIT_RE as WRAPPER_COMMIT_RE, STATUSES
from beamo_wipe.evidence import valid_wall
from beamo_wipe import identity as _identity
from beamo_wipe.lang import LANGUAGE_ORDER, current as _lang_current
from beamo_wipe.outcomes import (
    ResultView,
    _method_copy_for_locale,
    present_evidence,
    view_needs_support,
)
from beamo_wipe.support_contact import qr_svg as _support_qr_svg
from beamo_wipe import privacy as _privacy
from beamo_wipe.privacy import SHARE_JSON, is_sharing_copy
from beamo_wipe.progress import duration

UNAVAILABLE = "unavailable"
WITHHELD = "withheld"
TRUNCATED_SUFFIX = " (truncated)"
MAX_VALUE = 240
RESULT_FILE_RE = re.compile(r"^result-[A-Za-z0-9._-]{1,120}\.json$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
STATUS_PRODUCTION = "production"
STATUS_DEVELOPMENT = "development"
STATUS_DIRTY = "dirty"
STATUS_MISMATCH = "source mismatch"


def _build_status_labels() -> dict[str, str]:
    return {
        "production": STATUS_PRODUCTION,
        "development": STATUS_DEVELOPMENT,
        "dirty": STATUS_DIRTY,
        "source_mismatch": STATUS_MISMATCH,
        "unavailable": UNAVAILABLE,
    }


STATUS_LABELS = _build_status_labels()


def _apply_language() -> None:
    global STATUS_LABELS
    STATUS_LABELS = _build_status_labels()


H_DISK = "Disk"
H_CAPACITY = "Capacity"
H_CONNECTION = "Connection"
H_METHOD = "Method"
H_OVERWRITES = "Overwrites"
METHOD_BOTH = "{title}. {summary}"
H_APPLICATION = "Application"
H_WRAPPER_COMMIT = "Wrapper commit"
H_RELEASE_BUILD = "Release build"
H_BUILD_STATUS = "Build status"
H_ENGINE = "Engine"
H_ENGINE_COMMIT = "Engine commit"
H_REPORT_FILE = "Report file"
H_REPORT_CHECKSUM = "Report checksum"
H_ELAPSED = "Elapsed"
H_RESULT = "Result"
H_VERIFICATION = "Verification"
H_WARNINGS = "Warnings"
H_LIMITATIONS = "Limitations"
H_CLOCK = "Clock"
H_STARTED = "Started (clock not verified)"
H_ENDED = "Ended (clock not verified)"
H_IDENTITY_EVIDENCE = "Identity evidence"
WARNINGS_NONE = "None recorded"
VERIFY_PASSED = "Read-back verification passed"
VERIFY_SKIPPED = "Verification was not performed"
CLOCK_UNVERIFIED = "unverified"
CLOCK_UNVERIFIED_SRC = "unverified ({source})"
SHARING_REDACTED_NOTICE = "Sharing copy. Serials and hardware IDs withheld."
HEADER_RESULT = "Beamo Wipe result"
HTML_CAPTION = "Report details"
HTML_NOTE = "Readable copy of RESULT.txt. result.json is the machine-readable original."
HTML_SUPPORT_TITLE = "Support"

def _object_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _current_language() -> str:
    try:
        code = _lang_current()
    except Exception:
        return "en"
    return code if code in LANGUAGE_ORDER else "en"


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
        return cleaned[:limit].rstrip() + TRUNCATED_SUFFIX
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
    try:
        number = float(value)
    except OverflowError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _wall(value: object) -> str:
    # Rendering an imported or damaged report needs the same calendar check
    # as evidence creation; a shape-only match can print impossible dates.
    return valid_wall(value) or UNAVAILABLE


def _schema_version(evidence: Mapping[str, Any]) -> int:
    version = evidence.get("schema_version")
    return version if type(version) is int else 0


def _clock_line(timestamps: Mapping[str, Any], schema_version: int) -> str:
    if schema_version >= 2:
        confidence = timestamps.get("wall_confidence")
        provenance = timestamps.get("wall_provenance")
        if confidence == "verified":
            return UNAVAILABLE
        if (
            confidence == "unverified"
            and isinstance(provenance, str)
            and provenance in {"os_utc", "injected"}
        ):
            return CLOCK_UNVERIFIED_SRC.format(source=provenance)
        return UNAVAILABLE
    if _wall(timestamps.get("started_at_wall")) != UNAVAILABLE or _wall(
        timestamps.get("ended_at_wall")
    ) != UNAVAILABLE:
        return CLOCK_UNVERIFIED
    return UNAVAILABLE


def _wall_display(timestamps: Mapping[str, Any], key: str, schema_version: int) -> str:
    if schema_version >= 2:
        if timestamps.get("wall_confidence") != "unverified":
            return UNAVAILABLE
        provenance = timestamps.get("wall_provenance")
        if not isinstance(provenance, str) or provenance not in {
            "os_utc", "injected"
        }:
            return UNAVAILABLE
    return _wall(timestamps.get(key))


def _elapsed(timestamps: object) -> str:
    """Prefer monotonic stamps. Wall time is never used for elapsed duration."""
    if not isinstance(timestamps, dict):
        return UNAVAILABLE
    started = _finite_number(timestamps.get("started_monotonic"))
    ended = _finite_number(timestamps.get("ended_monotonic"))
    if started is not None and ended is not None:
        # Contradictory monotonic stamps make the elapsed time untrustworthy,
        # even if an imported report also supplies a duration hint.
        return duration(ended - started) if ended >= started else UNAVAILABLE
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
    if value in {UNAVAILABLE, _identity.SERIAL_NOT_REPORTED}:
        return value
    return WITHHELD


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    out = text
    for secret in secrets:
        out = re.sub(re.escape(secret), WITHHELD, out, flags=re.IGNORECASE)
    return out


def _report_file(evidence: Mapping[str, Any]) -> str:
    if is_sharing_copy(evidence):
        return SHARE_JSON
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
    device = _object_mapping(evidence.get("device"))
    presentation = (
        _object_mapping(evidence.get("device_presentation"))
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
    if serial == UNAVAILABLE and label == _identity.SERIAL_LABEL:
        serial = presented
    if hardware == UNAVAILABLE and label == _identity.HARDWARE_ID_LABEL:
        hardware = presented
    if redacted or is_sharing_copy(evidence):
        title = _scrub(title, secrets)
        capacity = _scrub(capacity, secrets)
        connection = _scrub(connection, secrets)
        serial = WITHHELD
        hardware = WITHHELD
    return [
        (H_DISK, title),
        (H_CAPACITY, capacity),
        (H_CONNECTION, connection),
        (_identity.SERIAL_LABEL, serial if serial else UNAVAILABLE),
        (_identity.HARDWARE_ID_LABEL, hardware if hardware else UNAVAILABLE),
    ]


def _method_lines(evidence: Mapping[str, Any]) -> list[tuple[str, str]]:
    method = _object_mapping(evidence.get("method"))
    # Saved prose is not authority for the operation the engine ran. The
    # report uses the pinned method and the record's language instead.
    from beamo_wipe.methods import METHODS
    from beamo_wipe.models import MethodId

    try:
        spec = METHODS[MethodId(method["id"])]
        language = _object_mapping(evidence.get("locale")).get("language")
        if language not in LANGUAGE_ORDER:
            language = _current_language()
        if is_sharing_copy(evidence):
            # A sharing copy may have replaced part of a canonical label with
            # a withheld marker. Preserve that redaction in the readable copy.
            if present_evidence(evidence).code == "indeterminate":
                raise ValueError("Invalid sharing method")
            title = _optional_text(method, "title")
            summary = _optional_text(method, "operation_summary")
        else:
            canonical = _method_copy_for_locale(spec, language)
            title = _text(canonical["title"])
            summary = _text(canonical["operation_summary"])
        overwrites = str(spec.overwrite_passes)
    except (KeyError, TypeError, ValueError, AttributeError):
        title = summary = overwrites = UNAVAILABLE
    if title != UNAVAILABLE and summary != UNAVAILABLE:
        method_line = METHOD_BOTH.format(title=title, summary=summary)
    elif summary != UNAVAILABLE:
        method_line = summary
    else:
        method_line = title
    return [(H_METHOD, method_line), (H_OVERWRITES, overwrites)]


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
        return WARNINGS_NONE
    return "\n".join(f"- {item}" for item in items)


def _limitations(evidence: Mapping[str, Any]) -> str:
    view = present_evidence(evidence)
    step = sanitize_value(view.next_step) if view.next_step else UNAVAILABLE
    if step != UNAVAILABLE:
        return step
    verification = (
        _object_mapping(evidence.get("verification"))
    )
    return _optional_text(verification, "scope")


def _verification_status(evidence: Mapping[str, Any]) -> str:
    view = present_evidence(evidence)
    if view.code == "verified":
        return VERIFY_PASSED
    if view.code == "unverified":
        return VERIFY_SKIPPED
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
    wrapper = evidence.get("source_commit")
    if not isinstance(wrapper, str) or not WRAPPER_COMMIT_RE.fullmatch(wrapper):
        wrapper_text = UNAVAILABLE
    else:
        wrapper_text = wrapper
    build_id = evidence.get("build_id")
    if not isinstance(build_id, str) or not BUILD_ID_RE.fullmatch(build_id):
        build_text = UNAVAILABLE
    else:
        build_text = build_id
    status = evidence.get("build_status")
    status_text = (
        STATUS_LABELS.get(status, UNAVAILABLE)
        if isinstance(status, str) and status in STATUSES
        else UNAVAILABLE
    )
    if status_text == UNAVAILABLE:
        wrapper_text = UNAVAILABLE
        build_text = UNAVAILABLE
    return [
        (H_APPLICATION, application),
        (H_WRAPPER_COMMIT, wrapper_text),
        (H_RELEASE_BUILD, build_text),
        (H_BUILD_STATUS, status_text),
        (H_ENGINE, engine),
        (H_ENGINE_COMMIT, commit_text),
    ]


def _recovery_fields(view: ResultView) -> list[tuple[str, str]]:
    from beamo_wipe.recovery import recovery_for_view

    sections = recovery_for_view(view)
    if sections is None:
        return []
    return list(sections.labeled_pairs())


def _result_fields(
    payload: Mapping[str, Any],
    view: ResultView,
    secrets: tuple[str, ...],
    checksum: str,
    timestamps: Mapping[str, Any],
    *,
    redacted: bool = False,
) -> list[tuple[str, str]]:
    """Canonical owner field list shared by RESULT.txt and REPORT.html."""
    return [
        (H_REPORT_FILE, _report_file(payload)),
        (H_REPORT_CHECKSUM, checksum),
        *_disk_lines(payload, redacted=redacted),
        *_method_lines(payload),
        (H_ELAPSED, _elapsed(timestamps)),
        (H_RESULT, view.message),
        *_recovery_fields(view),
        (H_VERIFICATION, _verification_status(payload)),
        (H_WARNINGS, _warnings(payload, secrets)),
        (H_LIMITATIONS, _limitations(payload)),
        *_application(payload),
        (H_CLOCK, _clock_line(timestamps, _schema_version(payload))),
        (H_STARTED, _wall_display(timestamps, "started_at_wall", _schema_version(payload))),
        (H_ENDED, _wall_display(timestamps, "ended_at_wall", _schema_version(payload))),
    ]


def _html_value(value: str) -> str:
    if "\n" in value:
        items = []
        for line in value.split("\n"):
            item = line[2:] if line.startswith("- ") else line
            items.append(f"<li>{html.escape(item, quote=True)}</li>")
        return "<ul>" + "".join(items) + "</ul>"
    return html.escape(value, quote=True)


_REPORT_HTML_STYLE = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.5;"
    "color:#111;background:#fff;max-width:48rem;margin:2rem auto;padding:0 1rem}"
    "table{border-collapse:collapse;width:100%;margin-top:1rem}"
    ".table-wrap{overflow-x:auto}"
    "td{overflow-wrap:anywhere}"
    "caption{text-align:left;font-weight:bold;padding:.4rem 0}"
    "th,td{border:1px solid #666;padding:.4rem .6rem;text-align:left;vertical-align:top}"
    "th{background:#f2f2f2;white-space:nowrap}"
    "td ul{margin:0;padding-left:1.2rem}"
    ".announcement{font-size:1.05rem}"
    ".note{font-size:.9rem;color:#333}"
    "h2{font-size:1.1rem;margin:1.4rem 0 .4rem}"
    ".supportqr{width:132px;height:auto;border:1px solid #666;background:#fff}"
    "@media print{body{margin:0;max-width:none}th{background:#fff}}"
)


def build_result_report_html(
    evidence: object,
    *,
    evidence_sha256: str = "",
) -> str:
    """Self-contained offline readable report. Same canonical fields as RESULT.txt.

    No scripts, images, links, or external references: safe to open from the
    report USB on any browser, including without network access. Every value is
    escaped; headings never come from evidence or logs.
    """
    payload = evidence if isinstance(evidence, dict) else {}
    view = present_evidence(payload)
    checksum = evidence_sha256 if HEX64_RE.fullmatch(evidence_sha256 or "") else UNAVAILABLE
    timestamps = _object_mapping(payload.get("timestamps"))
    fields = _result_fields(payload, view, (), checksum, timestamps)
    page_lang = _current_language()
    support_section = ""
    if view_needs_support(view.code):
        from beamo_wipe import copy as C

        support_section = (
            f"<h2>{html.escape(HTML_SUPPORT_TITLE, quote=True)}</h2>\n"
            f"<p>{html.escape(C.support_lead(), quote=True)}</p>\n"
            f'<div class="supportqr" aria-hidden="true">{_support_qr_svg()}</div>\n'
        )
    rows = "\n".join(
        f'    <tr><th scope="row">{html.escape(label, quote=True)}</th>'
        f"<td>{_html_value(value)}</td></tr>"
        for label, value in fields
    )
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{page_lang}">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(HEADER_RESULT, quote=True)}</title>\n"
        f"<style>{_REPORT_HTML_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        f"<h1>{html.escape(HEADER_RESULT, quote=True)}</h1>\n"
        '<p class="announcement">'
        f"{html.escape(view.announcement, quote=True)}</p>\n"
        '<div class="table-wrap">\n'
        "<table>\n"
        f"<caption>{html.escape(HTML_CAPTION, quote=True)}</caption>\n"
        "<tbody>\n"
        f"{rows}\n"
        "</tbody>\n"
        "</table>\n"
        "</div>\n"
        f"{support_section}"
        f'<p class="note">{html.escape(HTML_NOTE, quote=True)}</p>\n'
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_result_summary(
    evidence: object,
    *,
    evidence_sha256: str = "",
    redacted: bool = False,
) -> str:
    """Stable labeled summary. Headings never come from evidence or logs."""
    payload = evidence if isinstance(evidence, dict) else {}
    sharing = is_sharing_copy(payload)
    view = present_evidence(payload)
    device = _object_mapping(payload.get("device"))
    secrets = _privacy.collect_secrets(payload) if redacted else (_secrets(device) if sharing else ())
    checksum = evidence_sha256 if HEX64_RE.fullmatch(evidence_sha256 or "") else UNAVAILABLE
    timestamps = _object_mapping(payload.get("timestamps"))
    if sharing:
        header = _privacy.NOTICE
    elif redacted:
        header = SHARING_REDACTED_NOTICE
    else:
        header = HEADER_RESULT
    lines: list[str] = [header]
    fields = _result_fields(
        payload, view, secrets, checksum, timestamps, redacted=redacted
    )
    if sharing:
        fields.append((H_IDENTITY_EVIDENCE, _privacy.UNSUITABLE))
    for label, value in fields:
        if "\n" in value:
            lines.append(f"{label}:")
            lines.extend(value.split("\n"))
        else:
            lines.append(f"{label}: {value}")
    text = "\n".join(lines)
    if redacted or sharing:
        text = _scrub(text, secrets)
    return text
