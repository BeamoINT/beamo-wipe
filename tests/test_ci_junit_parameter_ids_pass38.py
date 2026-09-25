"""Path-bearing pytest parameter IDs must not block secret-free CI receipts."""

from __future__ import annotations

from pathlib import Path
import sys

from beamo_wipe.ci_evidence import run_gate
from beamo_wipe.verification_evidence import parse_junit_xml


ROOT = Path(__file__).resolve().parents[1]


def test_junit_redacts_path_parameter_ids_without_merging_skips():
    xml = (
        '<testsuite tests="3" failures="0" errors="0" skipped="2">'
        '<testcase classname="tests.test_fixture" name="test_disk[/dev/fake0]">'
        '<skipped message="fake device unavailable"/></testcase>'
        '<testcase classname="tests.test_fixture" name="test_disk[/dev/fake1]">'
        '<skipped message="fake device unavailable"/></testcase>'
        '<testcase classname="tests.test_fixture" name="test_file[file:///home/user/run.log]"/>'
        '</testsuite>'
    )
    measured = parse_junit_xml(xml)
    assert (measured["passed"], measured["skipped"], measured["total"]) == (1, 2, 3)
    ids = [entry["id"] for entry in measured["skips"]]
    assert len(set(ids)) == 2
    assert all("[path]" in item for item in ids)
    assert all("/dev/" not in item and "file:" not in item for item in ids)


def test_tests_gate_accepts_path_parameter_ids_from_real_pytest_xml(tmp_path):
    source = tmp_path / "test_parameter_ids.py"
    source.write_text(
        'import pytest\n'
        '@pytest.mark.parametrize("device", ["/dev/fake0", "/dev/fake1"])\n'
        'def test_fake_device(device):\n'
        '    if device.endswith("1"):\n'
        '        pytest.skip("fake device unavailable")\n',
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence"
    receipt = run_gate(
        "tests",
        [sys.executable, "-m", "pytest", "-q", str(source),
         f"--junitxml={evidence / 'tests.xml'}"],
        root=ROOT, evidence_dir=evidence, build_id="local",
    )
    assert receipt["status"] == "pass"
    assert (receipt["measured"]["passed"], receipt["measured"]["skipped"]) == (1, 1)
    assert "/dev/" not in receipt["skips"][0]["id"]
    assert "[path]" in receipt["skips"][0]["id"]
