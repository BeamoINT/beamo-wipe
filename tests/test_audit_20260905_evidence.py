"""Safety audit regression: malformed local evidence files must not stall UI."""
from __future__ import annotations

import os
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("reader", ["evidence", "export_log", "diagnostics", "runner", "wizard"])
def test_nonregular_evidence_readers_reject_fifo_without_waiting(tmp_path, reader):
    fifo = tmp_path / "diagnostics.log"
    os.mkfifo(fifo, 0o600)
    script = r'''
import pathlib
import sys
from beamo_wipe.safety import SafetyError
path = pathlib.Path(sys.argv[2])
reader = sys.argv[1]
if reader == "evidence":
    from beamo_wipe.evidence import _read_regular_nofollow
    try:
        _read_regular_nofollow(path)
    except SafetyError:
        pass
    else:
        raise AssertionError("nonregular evidence accepted")
elif reader == "export_log":
    from beamo_wipe.support_export import read_export_log
    assert read_export_log(str(path), expected_sha256="a" * 64, expected_size_bytes=1) == (b"", "unavailable")
elif reader == "runner":
    from beamo_wipe.nwipe_runner import NwipeRunner
    assert NwipeRunner()._read_log_tail(str(path), 128) == ""
elif reader == "wizard":
    import beamo_wipe.evidence as evidence
    import beamo_wipe.diagnostics as diagnostics
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import WipeRequest, WipeResult
    wizard = make_demo_wizard()
    diagnostics.log_diag = lambda *a, **kw: False
    reached_write = []
    def failed_write(*a, **kw):
        reached_write.append(True)
        raise OSError("inert write stub")
    evidence.write_evidence_atomic = failed_write
    wizard._wipe_request = WipeRequest("/dev/fake-target", wizard.method, "/dev/fake-boot", str(path))
    wizard._evidence_argv = []
    wizard._write_evidence(result=WipeResult(False, 1, "failed", str(path)), cancelled=False, interrupted=False)
    assert reached_write and wizard.evidence_error
else:
    from beamo_wipe.diagnostics import read_diagnostics
    assert read_diagnostics(path.parent) == []
'''
    try:
        process = subprocess.run(
            [sys.executable, "-c", script, reader, str(fifo)],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{reader} blocked opening a FIFO instead of rejecting its nonregular file type")
    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize("exists", [False, True])
def test_evidence_readers_preserve_regular_and_missing_file_behavior(tmp_path, exists):
    from beamo_wipe.diagnostics import read_diagnostics
    from beamo_wipe.evidence import _read_regular_nofollow
    from beamo_wipe.safety import SafetyError
    from beamo_wipe.support_export import read_export_log

    path = tmp_path / "diagnostics.log"
    data = b'{"code":"test_event"}\n'
    if exists:
        path.write_bytes(data)
        assert _read_regular_nofollow(path) == data
    else:
        with pytest.raises(SafetyError):
            _read_regular_nofollow(path)
    assert read_diagnostics(tmp_path) == ([{"code": "test_event"}] if exists else [])
    assert read_export_log(
        str(path),
        expected_sha256=hashlib.sha256(data).hexdigest(),
        expected_size_bytes=len(data),
    ) == ((data, "complete") if exists else (b"", "unavailable"))
