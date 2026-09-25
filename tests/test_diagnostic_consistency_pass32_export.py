# SPDX-License-Identifier: GPL-3.0-or-later
"""A self-consistent checksum must not bless contradictory support facts."""

import json

import pytest

from beamo_wipe.diagnostic_report import create_report, validate_report
from beamo_wipe.models import DiscoveryResult
from beamo_wipe.safety import SafetyError


def _report() -> dict:
    return json.loads(
        create_report(
            "discovery_failed",
            DiscoveryResult(error="test failure"),
            ui="console",
            session_started=0,
        )
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda report: report.update(events=[{"code": "startup_refused"}]),
        lambda report: report["discovery"].update(status="ready"),
        lambda report: report["discovery"].update(status="no_eligible_disks"),
        lambda report: report["discovery"].update(
            status="boot_unidentified", boot_identified=True
        ),
    ],
)
def test_diagnostic_rejects_internally_contradictory_status(change):
    report = _report()
    change(report)
    with pytest.raises(SafetyError, match="Invalid or unsanitized diagnostic report"):
        validate_report(json.dumps(report).encode())
