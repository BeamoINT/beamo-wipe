"""A release receipt must account for every JUnit outcome node."""

import pytest

from beamo_wipe.verification_evidence import (
    REQUIRED_GATES,
    build_gate_receipt,
    build_test_evidence,
    parse_junit_xml,
    verify_release_evidence,
)


@pytest.mark.parametrize("outcome", ["failure", "error", "skipped"])
def test_junit_rejects_outcome_hidden_below_testcase_wrapper(outcome):
    xml = (
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        f'<testcase name="apparently-passed"><wrapper><{outcome} /></wrapper></testcase>'
        '</testsuite>'
    )
    with pytest.raises(RuntimeError, match="nested|hidden"):
        parse_junit_xml(xml)


def test_release_evidence_rejects_unreviewed_fields():
    receipts = [
        build_gate_receipt(
            gate=gate,
            status="pass",
            command=f"run {gate}",
            source_commit="a" * 40,
            build_id="fixture",
            environment={"runner": "fixture"},
            measured={"passed": 1, "failed": 0, "errors": 0, "skipped": 0,
                      "xfailed": 0, "deselected": 0, "total": 1},
            skips=[],
            log_sha256="b" * 64,
            started_at="2026-09-11T00:00:00Z",
            ended_at="2026-09-11T00:00:01Z",
        )
        for gate in REQUIRED_GATES
    ]
    evidence = build_test_evidence(receipts)
    evidence["unreviewed_field"] = "password=fixture"

    with pytest.raises(RuntimeError, match="unknown|unexpected"):
        verify_release_evidence(evidence)
