"""Local file URLs are private host paths in release evidence."""

import pytest

from beamo_wipe.verification_evidence import build_gate_receipt, parse_junit_xml


@pytest.mark.parametrize(
    "private_path",
    [
        "file:///Users/alice/private/run.log",
        "file://localhost/home/alice/run.log",
        r"C:\Users\alice\private\run.log",
        r"\\server\share\private\run.log",
        "//server/share/private/run.log",
    ],
)
def test_junit_skip_redacts_local_path(private_path):
    report = parse_junit_xml(
        '<testsuite tests="1" failures="0" errors="0" skipped="1">'
        f'<testcase name="test_skip"><skipped message="see {private_path}"/></testcase>'
        '</testsuite>'
    )
    reason = report["skips"][0]["reason"]
    assert private_path not in reason
    assert "[path]" in reason


@pytest.mark.parametrize(
    "command",
    [
        "python file:///Users/alice/private/check.py",
        r"C:\Users\alice\private\check.py",
        r"\\server\share\private\check.py",
        "//server/share/private/check.py",
    ],
)
def test_gate_receipt_rejects_private_path_in_command(command):
    with pytest.raises(RuntimeError, match="private host path"):
        build_gate_receipt(
            gate="preview", status="pass",
            command=command,
            source_commit="a" * 40, build_id="local",
            environment={"runner": "fixture"},
            measured={"passed": 1, "failed": 0, "errors": 0, "skipped": 0,
                      "xfailed": 0, "deselected": 0, "total": 1},
            skips=[], log_sha256="b" * 64,
            started_at="2026-09-25T00:00:00Z",
            ended_at="2026-09-25T00:00:01Z",
        )


def test_public_https_url_is_not_treated_as_a_network_share():
    report = parse_junit_xml(
        '<testsuite tests="1" failures="0" errors="0" skipped="1">'
        '<testcase name="test_skip"><skipped message="see https://example.test/guide"/>'
        '</testcase></testsuite>'
    )
    assert report["skips"][0]["reason"] == "see https://example.test/guide"
