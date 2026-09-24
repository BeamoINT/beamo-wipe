"""Authenticated report export must agree with the owner's result verdict."""

from __future__ import annotations

import copy

import pytest

from beamo_wipe.evidence import write_evidence_atomic
from beamo_wipe.models import MethodId
from beamo_wipe.outcomes import present_evidence
from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import (
    DISCOVERY_MALFORMED,
    prepare_terminal_evidence,
    select_export_volume,
)
from test_result_presentations import case_evidence


def test_export_refuses_success_evidence_with_contradictory_verification(tmp_path):
    _, valid, _ = case_evidence(
        ("verified", MethodId.EVERYDAY, 0, "{name} | Erased |", False, False)
    )
    target = valid["device"]["path"]
    valid_path = write_evidence_atomic(valid, log_dir=tmp_path, device_path=target)
    assert present_evidence(valid).success
    assert prepare_terminal_evidence(valid_path, target).outcome == "verified"

    contradictory = copy.deepcopy(valid)
    contradictory["verification"]["verified"] = False
    assert contradictory["outcome"] == "verified"
    assert not present_evidence(contradictory).success
    path = write_evidence_atomic(contradictory, log_dir=tmp_path, device_path=target)
    with pytest.raises(SafetyError, match="malformed"):
        prepare_terminal_evidence(path, target)


def test_export_bounds_malformed_device_path_before_realpath(tmp_path):
    record = {
        "schema_version": 2,
        "outcome": "failed",
        "device": {"path": "/dev/sda\x00other"},
        "logfile": "",
    }
    path = write_evidence_atomic(record, log_dir=tmp_path, device_path="/dev/sda")
    with pytest.raises(SafetyError, match="identity"):
        prepare_terminal_evidence(path, "/dev/sda")


@pytest.mark.parametrize("inventory", [None, [], "not a disk inventory"])
def test_report_usb_selection_bounds_non_object_inventory(inventory):
    with pytest.raises(SafetyError, match=DISCOVERY_MALFORMED):
        select_export_volume(inventory, ())
