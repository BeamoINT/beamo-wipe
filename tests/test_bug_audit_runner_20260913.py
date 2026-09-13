# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression proofs using synthetic reports and fake engine state only."""

from pathlib import Path
import sys

import pytest

from beamo_wipe.ci_evidence import run_gate
from beamo_wipe.verification_evidence import parse_junit_xml


@pytest.mark.parametrize(
    "xml",
    [
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="failed"><failure message="regression"/></testcase></testsuite>',
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="broken"><error message="setup failed"/></testcase></testsuite>',
        '<testsuite tests="1" failures="0" errors="0" skipped="0"/>',
        '<testsuite tests="1.9" failures="0" errors="0" skipped="0">'
        '<testcase name="only_one"/></testsuite>',
    ],
    ids=["hidden-failure", "hidden-error", "missing-testcase", "fractional-count"],
)
def test_junit_rejects_inconsistent_execution_report(xml):
    with pytest.raises(RuntimeError):
        parse_junit_xml(xml)


def test_tests_gate_does_not_publish_pass_for_hidden_failure(tmp_path):
    xml = (
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="failed"><failure message="regression"/></testcase></testsuite>'
    )
    command = [
        sys.executable,
        "-c",
        "import os; from pathlib import Path; "
        f"Path(os.environ['BEAMO_GATE_JUNIT']).write_text({xml!r})",
    ]
    with pytest.raises(RuntimeError):
        run_gate("tests", command, root=Path(__file__).resolve().parents[1],
                 evidence_dir=tmp_path / "evidence", build_id="local")
    assert not (tmp_path / "evidence/tests.receipt.json").exists()


def test_junit_accepts_authentic_pytest_lifecycle_outcomes(tmp_path):
    """Pytest emits both split IDs and multiple outcomes in one testcase."""
    import os
    import subprocess

    source = tmp_path / "test_lifecycle.py"
    source.write_text('''import pytest
@pytest.fixture
def setup_bad():
    raise RuntimeError("setup fixture failed")
@pytest.fixture
def teardown_bad():
    yield
    raise RuntimeError("teardown fixture failed")
def test_pass(): pass
def test_fail(): assert False
def test_setup(setup_bad): pass
def test_teardown(teardown_bad): pass
def test_both(teardown_bad): assert False
@pytest.mark.skip(reason="fixture skip")
def test_skip(): pass
@pytest.mark.xfail(reason="fixture xfail")
def test_xfail(): assert False
def test_skip_teardown(teardown_bad): pytest.skip("fixture skip teardown")
@pytest.mark.xfail(reason="fixture xfail teardown")
def test_xfail_teardown(teardown_bad): assert False
''')
    report = tmp_path / "junit.xml"
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-c", "/dev/null",
         f"--junitxml={report}", str(source)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    measured = parse_junit_xml(report.read_text())
    assert {key: measured[key] for key in ("passed", "failed", "errors", "skipped", "xfailed", "total")} == {
        "passed": 1, "failed": 2, "errors": 4, "skipped": 2, "xfailed": 3, "total": 12,
    }
    assert len(measured["skips"]) == 5
    assert str(tmp_path) not in str(measured)


@pytest.mark.parametrize("count", ["-1", "-0.5", "1.0", "1e0", "nan", "inf", "", "+1", " 1", "١"])
@pytest.mark.parametrize("field", ["tests", "failures", "errors", "skipped"])
def test_junit_rejects_non_integer_counts(field, count):
    import xml.etree.ElementTree as ET

    suite = ET.fromstring(
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="normal"/></testsuite>'
    )
    suite.set(field, count)
    with pytest.raises(RuntimeError, match="bad .* count"):
        parse_junit_xml(ET.tostring(suite, encoding="unicode"))


def test_junit_validates_each_suite_before_aggregation():
    # The two incorrect declarations cancel out if only totals are checked.
    xml = (
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="failed"><failure/></testcase></testsuite>'
        '<testsuite tests="1" failures="1" errors="0" skipped="0">'
        '<testcase name="passed"/></testsuite></testsuites>'
    )
    with pytest.raises(RuntimeError, match="inconsistent"):
        parse_junit_xml(xml)


def test_junit_combines_valid_suites_and_preserves_duplicate_ids():
    xml = (
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="same"/></testsuite>'
        '<testsuite tests="1" failures="1" errors="0" skipped="0">'
        '<testcase name="same"><failure/></testcase></testsuite>'
        '<testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>'
    )
    measured = parse_junit_xml(xml)
    assert (measured["total"], measured["passed"], measured["failed"]) == (2, 1, 1)
