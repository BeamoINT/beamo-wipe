# SPDX-License-Identifier: GPL-3.0-or-later
"""One conservative result vocabulary for UI, reports, and recovered evidence."""

from dataclasses import asdict, dataclass
import re
from typing import Any


@dataclass(frozen=True)
class ResultView:
    code: str
    message: str
    next_step: str
    tone: str
    icon: str
    success: bool = False

    @property
    def announcement(self) -> str:
        return f"{self.message}. {self.next_step}"

    def payload(self) -> dict[str, Any]:
        return {**asdict(self), "announcement": self.announcement}


STOP_WARNING = "Stopping cannot restore files already erased."

SUPPORT = (
    "Files may still be on the disk. Save the report if available and contact support. "
    "Shut down before disconnecting."
)
AFTERCARE_SUCCESS = (
    "Only this validated selected disk was processed. Other disks were not. "
    "Putting an operating system back on is a separate task."
)
MSG_START_FAILED = "The erase could not start"
NEXT_START_FAILED = "Keep the disks connected and contact support. Do not bypass protection."
MSG_VERIFIED = "Erase completed; verification passed"
# Trailing space joins the lead to AFTERCARE_SUCCESS in every language.
NEXT_VERIFIED_LEAD = "Read-back checked exposed storage only. Hidden copies may remain. Save the report if needed. "
MSG_UNVERIFIED = "Erase completed; verification was not performed"
NEXT_UNVERIFIED_LEAD = "The erase was not checked by a read-back pass. Save the report if needed. "
MSG_OCCUPIED = "The disk is in use"
NEXT_OCCUPIED = "The erase did not complete. Save the report and ask support what is using the disk. Do not force access."
MSG_OPEN_FAILED = "The disk could not be opened"
MSG_GEOMETRY = "The disk could not be used safely"
MSG_VERIFICATION_FAILED = "Read-back verification failed"
MSG_INTERRUPTED = "The erase was interrupted"
MSG_CANCELLED = "Stopped by you"
MSG_COMPLETION_MISSING = "Erase completion could not be confirmed"
MSG_PROCESS_FAILED = "The erase did not finish"
MSG_ENGINE_FAILED = "The disk reported an erase error"
MSG_INDETERMINATE = "The result could not be confirmed"
MSG_STOP_UNCONFIRMED = "Stop could not be confirmed"
NEXT_STOP_UNCONFIRMED = "The erase may still be running. Keep the disk and Beamo USB connected. Do not start another erase. Contact support."
PREVIEW_OK = "Preview finished"
PREVIEW_FAILED = "Preview of a failed erase"
PREVIEW_NEXT = "Nothing on this computer was erased. No overwrite or verification was performed."


def _build_views() -> dict[str, ResultView]:
    stop_next = STOP_WARNING + " " + SUPPORT
    return {
        "start_failed": ResultView(
            "start_failed",
            MSG_START_FAILED,
            NEXT_START_FAILED,
            "danger",
            "danger",
        ),
        "verified": ResultView(
            "verified",
            MSG_VERIFIED,
            NEXT_VERIFIED_LEAD + AFTERCARE_SUCCESS,
            "ok",
            "check",
            True,
        ),
        "unverified": ResultView(
            "unverified",
            MSG_UNVERIFIED,
            NEXT_UNVERIFIED_LEAD + AFTERCARE_SUCCESS,
            "warn",
            "warn",
            True,
        ),
        "occupied": ResultView(
            "occupied",
            MSG_OCCUPIED,
            NEXT_OCCUPIED,
            "danger",
            "danger",
        ),
        "open_failed": ResultView(
            "open_failed", MSG_OPEN_FAILED, SUPPORT, "danger", "danger"
        ),
        "geometry_unusable": ResultView(
            "geometry_unusable",
            MSG_GEOMETRY,
            SUPPORT,
            "danger",
            "danger",
        ),
        "verification_failed": ResultView(
            "verification_failed",
            MSG_VERIFICATION_FAILED,
            SUPPORT,
            "danger",
            "danger",
        ),
        "interrupted": ResultView(
            "interrupted", MSG_INTERRUPTED, stop_next, "warn", "warn"
        ),
        "cancelled": ResultView("cancelled", MSG_CANCELLED, stop_next, "warn", "warn"),
        "completion_missing": ResultView(
            "completion_missing",
            MSG_COMPLETION_MISSING,
            SUPPORT,
            "warn",
            "warn",
        ),
        "process_failed": ResultView(
            "process_failed", MSG_PROCESS_FAILED, SUPPORT, "danger", "danger"
        ),
        "engine_failed": ResultView(
            "engine_failed", MSG_ENGINE_FAILED, SUPPORT, "danger", "danger"
        ),
        "indeterminate": ResultView(
            "indeterminate", MSG_INDETERMINATE, SUPPORT, "warn", "warn"
        ),
        "stop_unconfirmed": ResultView(
            "stop_unconfirmed",
            MSG_STOP_UNCONFIRMED,
            NEXT_STOP_UNCONFIRMED,
            "danger",
            "danger",
        ),
    }


VIEWS = _build_views()

NOTHING_ERASED_CODES = frozenset(
    {"preview", "start_failed", "occupied", "open_failed", "geometry_unusable"}
)

# Outcome codes whose message or next step refers the owner to support.
# Derived from the vocabulary so copy edits cannot silently orphan the
# support destination shown beside them.
SUPPORT_CODES = frozenset(
    code
    for code, view in VIEWS.items()
    if "support" in (view.message + " " + view.next_step).lower()
)


def view_needs_support(code: object) -> bool:
    """True when the outcome's copy refers the owner to support."""
    return isinstance(code, str) and code in SUPPORT_CODES


def may_have_erased(code: str) -> bool:
    """True unless the outcome proves nothing was erased.

    Unknown codes show guidance: the post-erase note is conditional
    ("may"), so it stays honest when the erase state is uncertain.
    """
    return code not in NOTHING_ERASED_CODES


def _apply_language() -> None:
    global VIEWS
    VIEWS = _build_views()


def preview_view(ok: bool) -> ResultView:
    return ResultView(
        "preview",
        PREVIEW_OK if ok else PREVIEW_FAILED,
        PREVIEW_NEXT,
        "info",
        "info",
        ok,
    )


def present_evidence(evidence: object) -> ResultView:
    """Interpret a generated/validated record; malformed combinations fail closed.

    File callers must first authenticate the saved bytes. This checks semantic
    consistency, not authenticity of arbitrary user-supplied dictionaries.
    """
    unknown = VIEWS["indeterminate"]
    if not isinstance(evidence, dict):
        return unknown
    try:
        from beamo_wipe.methods import METHODS
        from beamo_wipe.models import MethodId

        from beamo_wipe.evidence import SUPPORTED_SCHEMA_VERSIONS
        from beamo_wipe.privacy import is_sharing_copy

        if (
            type(evidence.get("schema_version")) is not int
            or evidence["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS
        ):
            return unknown
        if is_sharing_copy(evidence):
            presentation = evidence.get("presentation")
            if (
                isinstance(presentation, dict)
                and presentation.get("code") in VIEWS
                and VIEWS[presentation["code"]].message == presentation.get("message")
            ):
                return VIEWS[presentation["code"]]
            return unknown
        device = evidence["device"]
        if (
            not isinstance(device, dict)
            or not isinstance(device.get("path"), str)
            or not device["path"].startswith("/dev/")
        ):
            return unknown
        exit_evidence = evidence["exit_evidence"]
        if type(exit_evidence["exit_code"]) is not int:
            return unknown
        method = evidence["method"]
        if type(method["rounds"]) is not int or type(method["noblank"]) is not bool:
            return unknown
        spec = METHODS[MethodId(method["id"])]
        if any(
            method.get(k) != getattr(spec, k)
            for k in ("nwipe_method", "rounds", "verify", "noblank")
        ):
            return unknown
        interruption = evidence["interruption"]
        verification = evidence["verification"]
        completion = evidence["completion"]
        outcome = evidence["outcome"]
        reason = completion["reason"]
        if (
            type(interruption["interrupted"]) is not bool
            or type(interruption["cancelled"]) is not bool
        ):
            return unknown
        if (
            type(verification["verified"]) is not bool
            or verification["requested"] != spec.verify
        ):
            return unknown
        if completion.get("validated") is not True:
            return unknown
        if outcome == "interrupted":
            if not interruption["interrupted"] or verification["verified"]:
                return unknown
            if (
                reason == "cancelled"
                and interruption["cancelled"]
                and interruption.get("origin") == "user"
            ):
                return VIEWS["cancelled"]
            if reason == "interrupted" and not interruption["cancelled"]:
                return VIEWS["interrupted"]
            return unknown
        if interruption["interrupted"] or interruption["cancelled"]:
            return unknown
        if outcome == "failed":
            if reason == "verification_failed" and spec.verify == "off":
                return unknown
            if verification["verified"] or reason not in {
                "occupied",
                "open_failed",
                "geometry_unusable",
                "verification_failed",
                "interrupted",
                "completion_missing",
                "process_failed",
                "engine_failed",
            }:
                return unknown
            return VIEWS[reason]
        exit_evidence = evidence["exit_evidence"]
        if (
            type(exit_evidence["exit_code"]) is not int
            or exit_evidence["exit_code"] != 0
            or exit_evidence["signal"] is not None
        ):
            return unknown
        if reason != "completed" or not re.fullmatch(
            r"[0-9a-f]{64}", evidence["log_checksum_sha256"]
        ):
            return unknown
        if (
            type(evidence["log_snapshot_size_bytes"]) is not int
            or not 0 < evidence["log_snapshot_size_bytes"] <= 1024 * 1024
        ):
            return unknown
        if outcome == "verified" and spec.verify == "last" and verification["verified"]:
            return VIEWS["verified"]
        if (
            outcome == "completed"
            and spec.verify == "off"
            and not verification["verified"]
        ):
            return VIEWS["unverified"]
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return unknown
