"""Reject ambiguous JSON at identity and release-evidence boundaries."""

from __future__ import annotations

import json

import pytest

from beamo_wipe.build_identity import load_injected_build
from beamo_wipe.verification_evidence import (
    REQUIRED_GATES,
    build_gate_receipt,
    main as evidence_main,
)


def test_injected_identity_rejects_duplicate_dirty_field(tmp_path):
    identity = tmp_path / "build-identity.json"
    identity.write_text(
        '{"source_commit":"'
        + "a" * 40
        + '","source_sha256":"'
        + "b" * 64
        + '","build_id":"00000000-0000-0000-0000-000000000001",'
        '"source_dirty":true,"source_dirty":false}'
    )
    assert load_injected_build(identity) is None


def test_injected_identity_handles_deep_malformed_json(tmp_path):
    identity = tmp_path / "build-identity.json"
    identity.write_text("[" * 1100 + "]" * 1100)
    assert load_injected_build(identity) is None


def test_receipt_cli_rejects_duplicate_status_field(tmp_path):
    receipts = []
    for gate in REQUIRED_GATES:
        receipt = build_gate_receipt(
            gate=gate,
            status="pass",
            command=f"run {gate}",
            source_commit="a" * 40,
            build_id="local",
            environment={"runner": "test"},
            measured={
                "passed": 1,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "xfailed": 0,
                "deselected": 0,
                "total": 1,
            },
            skips=[],
            log_sha256="b" * 64,
            started_at="2026-09-11T00:00:00Z",
            ended_at="2026-09-11T00:00:01Z",
        )
        raw = json.dumps(receipt)
        if gate == "tests":
            raw = raw.replace('"status": "pass"', '"status": "fail", "status": "pass"')
        path = tmp_path / f"{gate}.receipt.json"
        path.write_text(raw)
        receipts.extend(["--receipt", str(path)])
    with pytest.raises(RuntimeError, match="duplicate"):
        evidence_main(["verify-receipts", *receipts])
