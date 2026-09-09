# SPDX-License-Identifier: GPL-3.0-or-later
"""Parse pinned nwipe v0.42 log warnings. Never invoke hdparm or smartctl.

Statuses are pass, warning, fail, unavailable, or not_applicable. Missing,
malformed, localized, or contradictory output is unavailable — never a pass.
These checks do not rewrite wipe or verification outcomes.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from beamo_wipe import NWIPE_PINNED_COMMIT, NWIPE_PINNED_VERSION
from beamo_wipe.models import Disk, DiskKind
from beamo_wipe.storage_limits import notice

STATUSES = frozenset({"pass", "warning", "fail", "unavailable", "not_applicable"})
CHECK_IDS = ("hidden_capacity", "io_media", "coverage")
PARSER = "beamo_wipe.engine_checks"
# nwipe v0.42 logging.c prefixes (debug lines are omitted unless --verbose).
_LEVEL = re.compile(
    r"^(?:\[[^\]\r\n]*\]\s*)?\s*(?:debug|info|notice|warning|error|fatal|sanity):\s*"
)
# v0.42 hpa_dco.c / logging.c English lines. Do not add later-release GUI tokens.
_HIDDEN_DETECTED = re.compile(
    r"\*\*\*\s*HIDDEN SECTORS DETECTED\s*!\s*\*\*\*\s+on\s+(/dev/[A-Za-z0-9._+-]+)"
)
_HIDDEN_INDETERMINATE = re.compile(
    r"HIDDEN SECTORS INDETERMINATE!\s+on\s+(/dev/[A-Za-z0-9._+-]+)"
)
_HIDDEN_NONE = re.compile(r"No hidden sectors on\s+(/dev/[A-Za-z0-9._+-]+)")
_HPA_LINE_UNKNOWN = re.compile(
    r"\[UNKNOWN\] We can't find the HPA line, has hdparm ouput unknown/changed\?\s+"
    r"(/dev/[A-Za-z0-9._+-]+)"
)
_HDPARM_MISSING = re.compile(
    r"(?:hdparm command not found|Installing hdparm is mandatory)"
)
_HDPARM_STREAM = re.compile(r"hpa_dco_status: Failed to create stream to")
_HDPARM_FAILED = re.compile(r"hpa_dco_status\(\): hdparm failed")
_SG_IO = re.compile(r"SG_IO bad/missing sense data")
_HDPARM_INVALID = re.compile(
    r"hdparm reports invalid output, sector information may be invalid"
)
_ERROR_SUMMARY = "Error Summary"
_ERROR_ROW = re.compile(
    r"^[! ]\s*([A-Za-z0-9._+-]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*$"
)
_ERASURE_SUMMARY = "Erasure Summary"
_ERASURE_ROW = re.compile(
    r"^[! ]\s*([A-Za-z0-9._+-]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\S+)\s*$"
)
_FAILURE_MARK = re.compile(
    r"(?:>>> FAILURE! <<<|\|-FAILED-\||\|UABORTED\||\|INSANITY\|)"
)
_VERIFY_MISMATCH = re.compile(r"Verification mismatch on")


@dataclass(frozen=True)
class CheckResult:
    id: str
    status: str
    summary: str
    detail: str
    provenance: dict[str, str]

    def payload(self) -> dict[str, Any]:
        if self.id not in CHECK_IDS or self.status not in STATUSES:
            raise ValueError("invalid check")
        return {
            "id": self.id,
            "status": self.status,
            "summary": self.summary,
            "detail": self.detail,
            "provenance": dict(self.provenance),
        }


def _names(device: str) -> frozenset[str]:
    base = os.path.basename((device or "").rstrip("/"))
    if not base:
        return frozenset()
    return frozenset({base, f"/dev/{base}", device})


def _body(line: str) -> str:
    return _LEVEL.sub("", line.rstrip("\r\n"))


def _mentions(line: str, names: Iterable[str]) -> bool:
    text = line
    for name in names:
        if name and name in text:
            return True
    return False


def _redact(line: str) -> str:
    text = " ".join(_body(line).split())
    return re.sub(r"/dev/[A-Za-z0-9._+-]+", "/dev/<disk>", text)[:240]


def _provenance(parser: str, line: str = "", source: str = "nwipe_log") -> dict[str, str]:
    data = {
        "source": source,
        "parser": parser,
        "engine": "nwipe",
        "engine_version": NWIPE_PINNED_VERSION,
        "engine_commit": NWIPE_PINNED_COMMIT,
    }
    if line:
        data["matched"] = _redact(line)
    return data


def _check(
    check_id: str,
    status: str,
    summary: str,
    detail: str,
    provenance: dict[str, str],
) -> CheckResult:
    result = CheckResult(check_id, status, summary, detail, provenance)
    result.payload()
    return result


def _target_lines(log_text: str, names: frozenset[str]) -> list[str]:
    out = []
    for raw in (log_text or "").splitlines():
        if _mentions(raw, names):
            out.append(raw)
    return out


def _parse_hidden_capacity(log_text: str, device: str) -> CheckResult:
    parser = f"{PARSER}.hidden_capacity"
    names = _names(device)
    if not names:
        return _check(
            "hidden_capacity",
            "unavailable",
            "The hidden-storage check was not available. That is not a pass.",
            "No target device path was supplied.",
            _provenance(parser, source="missing"),
        )
    lines = _target_lines(log_text, names)
    detected = [line for line in lines if _HIDDEN_DETECTED.search(_body(line))]
    none = [line for line in lines if _HIDDEN_NONE.search(_body(line))]
    unknown = [
        line
        for line in lines
        if _HIDDEN_INDETERMINATE.search(_body(line))
        or _HPA_LINE_UNKNOWN.search(_body(line))
        or _SG_IO.search(_body(line))
        or _HDPARM_INVALID.search(_body(line))
    ]
    missing_tool = [
        line
        for line in (log_text or "").splitlines()
        if _HDPARM_MISSING.search(_body(line))
        or _HDPARM_STREAM.search(_body(line))
        or _HDPARM_FAILED.search(_body(line))
    ]
    reduced = _erasure_shortfall(log_text, names)
    if sum(1 for flag in (bool(detected), bool(none), bool(unknown)) if flag) > 1:
        sample = (detected or none or unknown)[0]
        return _check(
            "hidden_capacity",
            "unavailable",
            "The hidden-storage check was not available. That is not a pass.",
            "Contradictory hidden-storage lines were present in the pinned nwipe v0.42 log.",
            _provenance(parser, sample),
        )
    if detected or reduced is True:
        sample = (detected[0] if detected else "")
        return _check(
            "hidden_capacity",
            "warning",
            "This disk may have hidden storage the erase did not reach. Save the report and ask support.",
            "Pinned nwipe v0.42 reported hidden or reduced host-visible capacity. Beamo does not expand hidden areas.",
            _provenance(parser, sample or "Erasure Summary shortfall"),
        )
    if unknown or missing_tool:
        sample = (unknown or missing_tool)[0]
        return _check(
            "hidden_capacity",
            "unavailable",
            "The hidden-storage check was not available. That is not a pass.",
            "Pinned nwipe v0.42 could not determine HPA/DCO status for this disk.",
            _provenance(parser, sample),
        )
    if none and reduced is not True:
        return _check(
            "hidden_capacity",
            "pass",
            "No hidden storage was reported for this disk.",
            "Pinned nwipe v0.42 logged that no hidden sectors were found on the target.",
            _provenance(parser, none[0]),
        )
    return _check(
        "hidden_capacity",
        "unavailable",
        "The hidden-storage check was not available. That is not a pass.",
        "The pinned nwipe v0.42 log did not contain a usable hidden-storage result for this disk.",
        _provenance(parser, source="missing" if not (log_text or "").strip() else "nwipe_log"),
    )


def _erasure_shortfall(log_text: str, names: frozenset[str]) -> Optional[bool]:
    """True if v0.42 Erasure Summary shows bytes erased < bytes total for target."""
    in_table = False
    for raw in (log_text or "").splitlines():
        body = _body(raw)
        if _ERASURE_SUMMARY in body:
            in_table = True
            continue
        if in_table and body.startswith("***"):
            return None
        if not in_table:
            continue
        match = _ERASURE_ROW.match(body)
        if not match:
            continue
        if match.group(1) not in names:
            continue
        erased, total = int(match.group(2)), int(match.group(3))
        if total <= 0:
            return None
        return erased < total
    return None


def _parse_io_media(log_text: str, device: str) -> CheckResult:
    parser = f"{PARSER}.io_media"
    names = _names(device)
    if not names:
        return _check(
            "io_media",
            "unavailable",
            "Disk error counts were not available. That is not a pass.",
            "No target device path was supplied.",
            _provenance(parser, source="missing"),
        )
    fail_lines = [
        line
        for line in _target_lines(log_text, names)
        if _FAILURE_MARK.search(line) or _VERIFY_MISMATCH.search(_body(line))
    ]
    row = _error_summary_row(log_text, names)
    if row is None and not fail_lines:
        return _check(
            "io_media",
            "unavailable",
            "Disk error counts were not available. That is not a pass.",
            "The pinned nwipe v0.42 Error Summary did not include this disk.",
            _provenance(
                parser,
                source="missing" if not (log_text or "").strip() else "nwipe_log",
            ),
        )
    if row is not None:
        pass_errors, verify_errors, fsync_errors = row
        if pass_errors or verify_errors or fsync_errors or fail_lines:
            return _check(
                "io_media",
                "fail",
                "The disk reported write or read-back errors. Files may still be on the disk.",
                (
                    f"Error Summary pass={pass_errors} verify={verify_errors} "
                    f"fsync={fsync_errors} for the target."
                ),
                _provenance(parser, fail_lines[0] if fail_lines else "Error Summary"),
            )
        return _check(
            "io_media",
            "pass",
            "No write or read-back errors were counted for this disk.",
            "Error Summary listed zero pass, verification, and fdatasync errors for the target.",
            _provenance(parser, "Error Summary"),
        )
    return _check(
        "io_media",
        "fail",
        "The disk reported write or read-back errors. Files may still be on the disk.",
        "Pinned nwipe v0.42 logged a failure marker for the target.",
        _provenance(parser, fail_lines[0]),
    )


def _error_summary_row(
    log_text: str, names: frozenset[str]
) -> Optional[tuple[int, int, int]]:
    in_table = False
    malformed = False
    found = None
    for raw in (log_text or "").splitlines():
        body = _body(raw)
        if _ERROR_SUMMARY in body:
            in_table = True
            continue
        if in_table and body.startswith("***"):
            break
        if not in_table:
            continue
        if "Device" in body and "Pass Errors" in body:
            continue
        if set(body) <= {"-", " "}:
            continue
        match = _ERROR_ROW.match(body)
        if not match:
            if body.strip():
                malformed = True
            continue
        if match.group(1) not in names:
            continue
        found = (int(match.group(2)), int(match.group(3)), int(match.group(4)))
    if malformed and found is None:
        return None
    return found


def _parse_coverage(disk: Optional[Disk]) -> CheckResult:
    kind = disk.kind if disk is not None else DiskKind.UNKNOWN
    text = notice(kind)
    return _check(
        "coverage",
        "warning",
        "Overwrite reaches only storage the disk exposes. Hidden copies may remain.",
        text,
        _provenance(f"{PARSER}.coverage", source="storage_limits"),
    )


def evaluate_engine_checks(
    log_text: str,
    device: str,
    disk: Optional[Disk] = None,
) -> list[CheckResult]:
    """Return the three structured checks. Order is stable."""
    return [
        _parse_hidden_capacity(log_text, device),
        _parse_io_media(log_text, device),
        _parse_coverage(disk),
    ]


def check_payloads(
    log_text: str,
    device: str,
    disk: Optional[Disk] = None,
) -> list[dict[str, Any]]:
    return [item.payload() for item in evaluate_engine_checks(log_text, device, disk)]


def alert_summaries(checks: Iterable[dict[str, Any] | CheckResult]) -> tuple[str, ...]:
    """Concise UI lines. Coverage already appears at method selection."""
    alerts: list[str] = []
    seen: set[str] = set()
    for item in checks:
        payload = item.payload() if isinstance(item, CheckResult) else item
        if not isinstance(payload, dict):
            continue
        if payload.get("id") == "coverage":
            continue
        if payload.get("status") not in {"warning", "fail", "unavailable"}:
            continue
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip() or summary in seen:
            continue
        seen.add(summary)
        alerts.append(summary.strip())
    return tuple(alerts)
