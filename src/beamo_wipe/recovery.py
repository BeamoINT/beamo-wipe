# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner-facing recovery sections for failures.

Technical failures stay fail-closed. This module only presents them as
What happened, What it means for your disk, and What to do next.
Technical detail is separate and never replaces those three.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from beamo_wipe.outcomes import ResultView


RECOVERY_HAPPENED = "What happened"
RECOVERY_MEANING = "What it means for your disk"
RECOVERY_NEXT = "What to do next"
RECOVERY_TECHNICAL = "Technical details"

MEANING_UNCHANGED = "Nothing was erased. This disk is unchanged."
MEANING_INCOMPLETE = (
    "The erase did not complete. This disk is not confirmed erased."
)
MEANING_MAY_REMAIN = (
    "Files may still be on the disk. Do not treat this as a finished erase."
)
MEANING_UNCONFIRMED = (
    "The result could not be confirmed. Treat the disk as still containing data."
)
MEANING_MAY_RUNNING = (
    "The erase may still be running. Do not start another erase."
)
MEANING_STOPPED = (
    "Stopping cannot restore files already erased. Files may still be on the disk."
)
MEANING_REPORT_ONLY = (
    "The report was not saved. This does not change the erase result."
)
MEANING_DIAGNOSTIC = (
    "This is not erase evidence. No disk was selected for erasure from this screen."
)
MEANING_BLOCKED = (
    "No disk can be erased until this is resolved. The Beamo USB stays protected."
)
MEANING_EMPTY = (
    "Nothing can be erased. Protected devices stay listed. Do not bypass protection."
)
MEANING_PREVIEW = (
    "Nothing on this computer was erased. No overwrite or verification was performed."
)
MEANING_UNKNOWN = (
    "This did not confirm a finished erase. Read the exact message. "
    "If you are unsure, keep disks connected."
)
MEANING_EVIDENCE = (
    "The erase result on screen is unchanged. The report copy was not saved."
)

NEXT_UNKNOWN = (
    "Do not bypass protection. Note the exact message and contact support "
    "if you are unsure."
)
NEXT_BLOCKED_IDENTIFY = "Unplug extra USB sticks and start again."
NEXT_BLOCKED_BOOT = (
    "Shut down. Do not erase. The Beamo USB must stay protected."
)
NEXT_BLOCKED_STARTUP = (
    "Save a diagnostic report for support. Do not bypass protection."
)
NEXT_BLOCKED_REFRESH = (
    "Erase did not start. Keep disks connected and try Check disks again, "
    "or shut down."
)
NEXT_EMPTY = (
    "Review the reasons below. Keep the Beamo USB connected. "
    "Shut down before checking drive connections. "
    "If a disk remains unavailable or its identity is uncertain, contact support."
)
NEXT_EVIDENCE = (
    "Keep this session open. Try saving again if the button is offered. "
    "Temporary copies are lost at shutdown or power loss."
)

TECHNICAL_RESULT_CODE = "Result code: {code}"
TECHNICAL_ERROR_CODE = "Error code: {code}"
TECHNICAL_EXPORT_MARKER = "Export marker: {marker}"


@dataclass(frozen=True)
class RecoverySections:
    happened: str
    meaning: str
    next_step: str
    technical: str = ""

    def labeled_pairs(self, *, include_technical: bool = False) -> tuple[tuple[str, str], ...]:
        pairs = (
            (RECOVERY_HAPPENED, self.happened),
            (RECOVERY_MEANING, self.meaning),
            (RECOVERY_NEXT, self.next_step),
        )
        if include_technical and self.technical:
            pairs = pairs + ((RECOVERY_TECHNICAL, self.technical),)
        return tuple((label, body) for label, body in pairs if body)

    def announcement(self) -> str:
        parts = [self.happened, self.meaning, self.next_step]
        return " ".join(part for part in parts if part)


def format_recovery_text(
    sections: RecoverySections, *, include_technical: bool = False
) -> str:
    """Plain-text recovery block. Labels then bodies, in screen-reader order."""
    lines: list[str] = []
    for label, body in sections.labeled_pairs(include_technical=include_technical):
        if lines:
            lines.append("")
        lines.append(label)
        lines.append(body)
    return "\n".join(lines)


def _meaning_for_outcome(code: str) -> str:
    from beamo_wipe.outcomes import NOTHING_ERASED_CODES

    if code == "preview":
        return MEANING_PREVIEW
    if code == "occupied":
        return MEANING_INCOMPLETE
    if code == "stop_unconfirmed":
        return MEANING_MAY_RUNNING
    if code in {"interrupted", "cancelled"}:
        return MEANING_STOPPED
    if code in {"indeterminate", "completion_missing"}:
        return MEANING_UNCONFIRMED
    if code in NOTHING_ERASED_CODES:
        return MEANING_UNCHANGED
    return MEANING_MAY_REMAIN


def recovery_for_view(view: ResultView) -> Optional[RecoverySections]:
    """Three sections for a failed or unconfirmed result. Success stays unlabeled."""
    if view.success:
        return None
    from beamo_wipe import outcomes as O

    happened = view.message
    if view.code == "preview":
        happened = O.PREVIEW_FAILED
    return RecoverySections(
        happened,
        _meaning_for_outcome(view.code),
        view.next_step or O.PREVIEW_NEXT,
        TECHNICAL_RESULT_CODE.format(code=view.code),
    )


def recovery_for_outcome(code: str) -> Optional[RecoverySections]:
    from beamo_wipe import outcomes as O

    if code == "preview":
        return RecoverySections(
            O.PREVIEW_FAILED,
            MEANING_PREVIEW,
            O.PREVIEW_NEXT,
            TECHNICAL_RESULT_CODE.format(code="preview"),
        )
    view = O.VIEWS.get(code)
    if view is None:
        return None
    return recovery_for_view(view)


def recovery_for_export(detail: str, *, diagnostic: bool = False) -> RecoverySections:
    """Map a report-USB refusal. The original detail is always What happened."""
    from beamo_wipe.support_export import _marker_for, next_step_for

    message = detail if isinstance(detail, str) and detail.strip() else MEANING_UNKNOWN
    step = next_step_for(message) if isinstance(detail, str) else ""
    marker = _marker_for(message) if isinstance(detail, str) and detail else ""
    return RecoverySections(
        message,
        MEANING_DIAGNOSTIC if diagnostic else MEANING_REPORT_ONLY,
        step or NEXT_UNKNOWN,
        TECHNICAL_EXPORT_MARKER.format(marker=marker) if marker else "",
    )


def recovery_for_diagnostic(
    code: str, message: str = "", step: str = ""
) -> RecoverySections:
    from beamo_wipe import diagnostic_report as D

    happened = message.strip() if isinstance(message, str) and message.strip() else D.report_title(code)
    next_step = step.strip() if isinstance(step, str) and step.strip() else D.PREPARE
    technical = TECHNICAL_ERROR_CODE.format(code=code) if code else ""
    return RecoverySections(happened, MEANING_DIAGNOSTIC, next_step, technical)


def recovery_for_blocked(error: object, *, recovered: bool = False) -> RecoverySections:
    from beamo_wipe import copy as C
    from beamo_wipe import safety
    from beamo_wipe.app import STARTUP_BLOCKED

    body = error if isinstance(error, str) and error else C.IDENTIFY_ERROR
    if recovered:
        return RecoverySections(
            body,
            MEANING_UNCONFIRMED,
            NEXT_UNKNOWN,
            "",
        )
    next_step = NEXT_UNKNOWN
    if body == C.IDENTIFY_ERROR or not error:
        next_step = NEXT_BLOCKED_IDENTIFY
    elif body in (safety.BOOT_APPEARED_SELECTABLE, safety.BOOT_APPEARED_ALIAS):
        next_step = NEXT_BLOCKED_BOOT
    elif body == STARTUP_BLOCKED:
        next_step = NEXT_BLOCKED_STARTUP
    elif body == C.REDISCOVER_ERROR:
        next_step = NEXT_BLOCKED_REFRESH
    return RecoverySections(body, MEANING_BLOCKED, next_step, "")


def recovery_for_empty() -> RecoverySections:
    from beamo_wipe import copy as C

    return RecoverySections(C.EMPTY_DISKS, MEANING_EMPTY, NEXT_EMPTY, "")


def recovery_for_evidence(code: str, message: str) -> RecoverySections:
    happened = message if isinstance(message, str) and message.strip() else MEANING_UNKNOWN
    technical = TECHNICAL_ERROR_CODE.format(code=code) if code else ""
    return RecoverySections(happened, MEANING_EVIDENCE, NEXT_EVIDENCE, technical)


def recovery_for_unknown(message: str) -> RecoverySections:
    happened = message if isinstance(message, str) and message.strip() else MEANING_UNKNOWN
    return RecoverySections(happened, MEANING_UNKNOWN, NEXT_UNKNOWN, "")


def recovery_for_wizard_error(error: object) -> Optional[RecoverySections]:
    """Map a wizard.error string, or None when there is nothing to present."""
    if not isinstance(error, str) or not error:
        return None
    from beamo_wipe import outcomes as O

    for view in O.VIEWS.values():
        if error == view.announcement or error == view.message:
            return recovery_for_view(view)
    from beamo_wipe import copy as C
    from beamo_wipe import safety
    from beamo_wipe.app import STARTUP_BLOCKED

    if error in {
        C.IDENTIFY_ERROR,
        C.REDISCOVER_ERROR,
        safety.BOOT_APPEARED_SELECTABLE,
        safety.BOOT_APPEARED_ALIAS,
        STARTUP_BLOCKED,
    }:
        return recovery_for_blocked(error)
    return recovery_for_unknown(error)
