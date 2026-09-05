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


SUPPORT = (
    "Files may still be on the disk. Save the report if available and contact support. "
    "Shut down before disconnecting."
)
VIEWS = {
    "start_failed": ResultView(
        "start_failed",
        "The erase could not start",
        "Keep the disks connected and contact support. Do not bypass protection.",
        "danger",
        "danger",
    ),
    "verified": ResultView(
        "verified",
        "Erase completed; verification passed",
        "Read-back checked exposed storage only. Hidden copies may remain. Save the report if needed.",
        "ok",
        "check",
        True,
    ),
    "unverified": ResultView(
        "unverified",
        "Erase completed; verification was not performed",
        "The erase was not checked by a read-back pass. Save the report if needed.",
        "warn",
        "warn",
        True,
    ),
    "occupied": ResultView(
        "occupied",
        "The disk is in use",
        "The erase did not complete. Save the report and ask support what is using the disk. Do not force access.",
        "danger",
        "danger",
    ),
    "open_failed": ResultView(
        "open_failed", "The disk could not be opened", SUPPORT, "danger", "danger"
    ),
    "geometry_unusable": ResultView(
        "geometry_unusable",
        "The disk could not be used safely",
        SUPPORT,
        "danger",
        "danger",
    ),
    "verification_failed": ResultView(
        "verification_failed",
        "Read-back verification failed",
        SUPPORT,
        "danger",
        "danger",
    ),
    "interrupted": ResultView(
        "interrupted", "The erase was interrupted", SUPPORT, "warn", "warn"
    ),
    "cancelled": ResultView("cancelled", "Stopped by you", SUPPORT, "warn", "warn"),
    "completion_missing": ResultView(
        "completion_missing",
        "Erase completion could not be confirmed",
        SUPPORT,
        "warn",
        "warn",
    ),
    "process_failed": ResultView(
        "process_failed", "The erase did not finish", SUPPORT, "danger", "danger"
    ),
    "engine_failed": ResultView(
        "engine_failed", "The disk reported an erase error", SUPPORT, "danger", "danger"
    ),
    "indeterminate": ResultView(
        "indeterminate", "The result could not be confirmed", SUPPORT, "warn", "warn"
    ),
    "stop_unconfirmed": ResultView(
        "stop_unconfirmed",
        "The erase may still be running",
        "Keep the disk and Beamo USB connected. Do not start another erase. Contact support.",
        "danger",
        "danger",
    ),
}


def preview_view(ok: bool) -> ResultView:
    return ResultView(
        "preview",
        "Preview finished" if ok else "Preview of a failed erase",
        "Nothing on this computer was erased. No overwrite or verification was performed.",
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

        if (
            type(evidence.get("schema_version")) is not int
            or evidence["schema_version"] != 1
        ):
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
