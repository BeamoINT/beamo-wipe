# SPDX-License-Identifier: GPL-3.0-or-later
"""Sharing reports must derive their result from retained evidence fields."""

from __future__ import annotations

import copy

import pytest

from beamo_wipe.outcomes import VIEWS, present_evidence
from beamo_wipe.privacy import POLICY_ID, POLICY_VERSION, make_sharing_copy
from test_result_presentations import CASES, case_evidence


@pytest.fixture
def verified_sharing_copy():
    _, evidence, _ = case_evidence(CASES[0])
    sharing = make_sharing_copy(evidence)
    assert present_evidence(sharing) == VIEWS["verified"]
    return sharing


@pytest.mark.parametrize(
    "field,value",
    [
        ("outcome", "failed"),
        ("completion", {"validated": False, "reason": "completed"}),
        ("verification", {"requested": "last", "verified": False}),
        ("interruption", {"interrupted": True, "cancelled": False}),
        ("method", {"id": "unknown"}),
        ("exit_evidence", {"exit_code": 1, "signal": None}),
    ],
)
def test_contradictory_sharing_report_is_indeterminate(
    verified_sharing_copy, field, value
):
    broken = copy.deepcopy(verified_sharing_copy)
    broken[field] = value
    assert present_evidence(broken) == VIEWS["indeterminate"]


def test_sharing_report_cannot_relabel_verification(verified_sharing_copy):
    broken = copy.deepcopy(verified_sharing_copy)
    broken["presentation"]["code"] = "unverified"
    broken["presentation"]["message"] = VIEWS["unverified"].message
    assert present_evidence(broken) == VIEWS["indeterminate"]


def test_sharing_marker_cannot_bypass_original_log_proof():
    _, original, _ = case_evidence(CASES[0])
    original["privacy"] = {
        "copy": "sharing",
        "unsuitable_for_identity_evidence": True,
        "policy_version": POLICY_VERSION,
        "policy": POLICY_ID,
    }
    original.pop("log_checksum_sha256")
    assert present_evidence(original) == VIEWS["indeterminate"]
