"""Release receipts must not copy secret-bearing environment fields."""

from __future__ import annotations

import pytest

from beamo_wipe.verification_evidence import (
    build_gate_receipt,
    sanitize_environment,
)


@pytest.mark.parametrize(
    "key",
    ["password", "API_CREDENTIAL", "SERVICE_SECRET", "AWS_ACCESS_KEY_ID"],
)
def test_gate_receipt_rejects_secret_named_environment_fields(key):
    environment = {key: "FAKE-SECRET-REPORT-P27"}
    with pytest.raises(RuntimeError, match="must not carry"):
        sanitize_environment(environment, what="gate tests")
    with pytest.raises(RuntimeError, match="must not carry"):
        build_gate_receipt(
            gate="tests",
            status="pass",
            command="pytest",
            source_commit="a" * 40,
            build_id="local",
            environment=environment,
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


def test_receipt_rejects_quoted_secret_assignment_in_command():
    with pytest.raises(RuntimeError, match="secret material"):
        build_gate_receipt(
            gate="tests",
            status="pass",
            command='run {"password":"FAKE-SECRET-REPORT-P27"}',
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
