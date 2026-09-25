"""Receipt metadata cannot carry common shortened password fields."""

import pytest

from beamo_wipe.verification_evidence import build_gate_receipt, sanitize_environment


@pytest.mark.parametrize("key", ["DB_PASS", "WIFI_PASSPHRASE"])
def test_receipt_environment_rejects_password_aliases(key):
    with pytest.raises(RuntimeError, match="must not carry"):
        sanitize_environment({key: "FAKE-P28-CREDENTIAL"}, what="gate tests")


@pytest.mark.parametrize(
    "assignment",
    ["DB_PASS=FAKE-P28", "API_TOKEN=FAKE-P28", "API_KEY=FAKE-P28"],
)
def test_receipt_command_rejects_secret_assignment_aliases(assignment):
    with pytest.raises(RuntimeError, match="secret material"):
        build_gate_receipt(
            gate="tests",
            status="pass",
            command=f"env {assignment} pytest",
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
