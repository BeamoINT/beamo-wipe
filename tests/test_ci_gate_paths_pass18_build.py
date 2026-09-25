"""CI receipts must describe the gate's own files, not replaced paths."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from beamo_wipe import ci_evidence


def _commit(monkeypatch: pytest.MonkeyPatch) -> None:
    original = subprocess.check_output

    def fake_check_output(command, **kwargs):
        if command == ["git", "rev-parse", "HEAD"]:
            return "a" * 40
        return original(command, **kwargs)

    monkeypatch.setattr(ci_evidence.subprocess, "check_output", fake_check_output)


def test_gate_rejects_junit_link_created_by_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _commit(monkeypatch)
    outside = tmp_path / "outside.xml"
    outside.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="a"/></testsuite>')
    command = [
        sys.executable,
        "-c",
        "import os,pathlib,sys; pathlib.Path(os.environ['BEAMO_GATE_JUNIT']).symlink_to(sys.argv[1])",
        str(outside),
    ]
    with pytest.raises(RuntimeError, match="unsafe.*JUnit|JUnit.*unsafe"):
        ci_evidence.run_gate(
            "tests", command, root=tmp_path, evidence_dir=tmp_path / "evidence", build_id="local"
        )


def test_gate_rejects_replaced_execution_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _commit(monkeypatch)
    log = tmp_path / "evidence" / "preview.log"
    command = [
        sys.executable,
        "-c",
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.unlink(); p.write_bytes(b'FAKE'); print('ACTUAL')",
        str(log),
    ]
    with pytest.raises(RuntimeError, match="execution log changed"):
        ci_evidence.run_gate(
            "preview", command, root=tmp_path, evidence_dir=log.parent, build_id="local"
        )


def test_gate_accepts_regular_junit_and_hashes_written_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit(monkeypatch)
    command = [
        sys.executable,
        "-c",
        "import os,pathlib; pathlib.Path(os.environ['BEAMO_GATE_JUNIT']).write_text('<testsuite tests=\"1\" failures=\"0\" errors=\"0\" skipped=\"0\"><testcase name=\"a\"/></testsuite>'); print('ACTUAL')",
    ]
    evidence = tmp_path / "evidence"
    receipt = ci_evidence.run_gate(
        "tests", command, root=tmp_path, evidence_dir=evidence, build_id="local"
    )
    assert receipt["status"] == "pass"
    assert receipt["log_sha256"] == hashlib.sha256((evidence / "tests.log").read_bytes()).hexdigest()
