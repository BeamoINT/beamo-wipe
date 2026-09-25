# SPDX-License-Identifier: GPL-3.0-or-later
"""Release receipt regressions from a second evidence audit."""

from __future__ import annotations

import json

import pytest

from beamo_wipe.verification_evidence import (
    REQUIRED_GATES,
    build_gate_receipt,
    build_test_evidence,
    main,
    parse_junit_xml,
    verify_release_evidence,
)


def _receipt(gate: str) -> dict:
    return build_gate_receipt(
        gate=gate,
        status="pass",
        command=f"run {gate}",
        source_commit="a" * 40,
        build_id="pass8",
        environment={"platform": "linux"},
        measured={
            "passed": 1, "failed": 0, "errors": 0,
            "skipped": 0, "xfailed": 0, "deselected": 0, "total": 1,
        },
        skips=[],
        log_sha256="b" * 64,
        started_at="2026-09-24T00:00:00Z",
        ended_at="2026-09-24T00:00:01Z",
    )


def test_release_evidence_requires_aggregate_digest():
    evidence = build_test_evidence([_receipt(gate) for gate in REQUIRED_GATES])
    evidence.pop("evidence_sha256")
    with pytest.raises(RuntimeError, match="evidence digest"):
        verify_release_evidence(evidence)


def test_verify_receipts_cli_rejects_duplicate_gate_files(tmp_path):
    files = []
    for gate in REQUIRED_GATES:
        path = tmp_path / f"{gate}.json"
        path.write_text(json.dumps(_receipt(gate)), encoding="utf-8")
        files.append(path)
    args = ["verify-receipts"]
    for path in [*files, files[0]]:
        args.extend(["--receipt", str(path)])
    with pytest.raises(RuntimeError, match="duplicate gate receipts"):
        main(args)


def test_junit_skip_reason_does_not_publish_private_host_path():
    xml = (
        '<testsuite tests="1" failures="0" errors="0" skipped="1">'
        '<testcase classname="pkg" name="test_display">'
        '<skipped message="no display at /home/runner/private/screenshot.png"/>'
        '</testcase></testsuite>'
    )
    report = parse_junit_xml(xml)
    assert "/home/runner" not in json.dumps(report)
    assert "no display" in report["skips"][0]["reason"]


def test_gate_receipt_rejects_private_host_path_in_manual_skip_reason():
    with pytest.raises(RuntimeError, match="private host path"):
        build_gate_receipt(
            gate="tests", status="pass", command="run tests",
            source_commit="a" * 40, build_id="pass8", environment={},
            measured={
                "passed": 1, "failed": 0, "errors": 0,
                "skipped": 1, "xfailed": 0, "deselected": 0, "total": 2,
            },
            skips=[{
                "id": "pkg.test_display", "kind": "skip",
                "reason": "see /home/runner/private/screenshot.png",
            }],
            log_sha256="b" * 64,
            started_at="2026-09-24T00:00:00Z",
            ended_at="2026-09-24T00:00:01Z",
        )


def test_aggregate_note_cannot_carry_secret():
    with pytest.raises(RuntimeError, match="secret material"):
        build_test_evidence(
            [_receipt(gate) for gate in REQUIRED_GATES],
            measured_note="secret=pass8-planted-token",
        )
