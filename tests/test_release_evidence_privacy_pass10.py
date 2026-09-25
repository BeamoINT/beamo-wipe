"""Release receipts must not preserve machine-local paths."""

import json

import pytest

from beamo_wipe.verification_evidence import (
    build_gate_receipt,
    build_package_inventory,
    parse_junit_xml,
)


def _receipt(**overrides):
    fields = dict(
        gate="preview",
        status="pass",
        command="bash scripts/ci-hosted.sh preview",
        source_commit="a" * 40,
        build_id="local",
        environment={"runner": "fixture"},
        measured=dict(passed=1, failed=0, errors=0, skipped=0, xfailed=0, deselected=0, total=1),
        skips=[],
        log_sha256="b" * 64,
        started_at="2026-09-24T00:00:00Z",
        ended_at="2026-09-24T00:00:01Z",
    )
    fields.update(overrides)
    return build_gate_receipt(**fields)


@pytest.mark.parametrize(
    "field,value",
    [
        ("command", "pytest /Users/alice/private/test.py"),
        ("command", "/opt/runner/venv/bin/python -m pytest"),
        ("build_id", "/home/alice/build"),
        ("reason", "see /home/alice/failure.txt"),
    ],
)
def test_receipt_rejects_private_host_path_in_scalar_fields(field, value):
    overrides = {field: value}
    if field == "reason":
        overrides.update(
            status="skip",
            measured=dict(passed=0, failed=0, errors=0, skipped=1, xfailed=0, deselected=0, total=1),
            skips=[{"id": "preview", "kind": "skip", "reason": "fixture"}],
            log_sha256="",
        )
    with pytest.raises(RuntimeError, match="private host path"):
        _receipt(**overrides)


def test_junit_skip_reason_redacts_path_after_colon():
    report = parse_junit_xml(
        '<testsuite tests="1" failures="0" errors="0" skipped="1">'
        '<testcase name="fixture"><skipped message="see:/Users/alice/private/log.txt"/></testcase>'
        '</testsuite>'
    )
    assert "/Users/alice" not in json.dumps(report)
    assert "[path]" in report["skips"][0]["reason"]


@pytest.mark.parametrize(
    "source",
    [
        "https://alice:private-password@repo.example/debian",
        "https://repo.example/debian?access_token=private-value",
    ],
)
def test_inventory_rejects_repository_uri_with_embedded_credentials(source):
    with pytest.raises(RuntimeError, match="credential"):
        build_package_inventory(
            packages=[{"name": "base-files", "version": "1", "arch": "amd64"}],
            collected_from="squashfs var/lib/dpkg/status",
            apt_sources=[source],
            source_commit="a" * 40,
            generated_at="2026-09-24T00:00:00Z",
        )
