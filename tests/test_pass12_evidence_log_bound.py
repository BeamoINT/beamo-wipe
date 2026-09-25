"""The running engine's mutable log must be read with a fixed upper bound."""

import os
import hashlib
from pathlib import Path

import pytest

from beamo_wipe.evidence import (
    _atomic_write_json,
    _read_regular_nofollow,
    recover_result,
)
from beamo_wipe.nwipe_runner import NWIPE_COMPLETION_LOG_BYTES
from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import EVIDENCE_MALFORMED, prepare_terminal_evidence
from test_evidence_retry import start


def test_started_evidence_limits_mutable_log_read(tmp_path, monkeypatch):
    wizard, _clock = start(tmp_path, monkeypatch)
    logfile = Path(wizard._wipe_request.logfile)
    logfile.write_bytes(b"incomplete fake engine log\n")
    wizard.runner._log_tail = ""
    wizard._evidence_written_for = None
    original_fdopen = os.fdopen
    requested_sizes = []

    class RecordedFile:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def seek(self, *args):
            return self.stream.seek(*args)

        def tell(self):
            return self.stream.tell()

        def read(self, size=-1):
            requested_sizes.append(size)
            return self.stream.read(size)

    def record_fdopen(*args, **kwargs):
        return RecordedFile(original_fdopen(*args, **kwargs))

    monkeypatch.setattr(os, "fdopen", record_fdopen)
    wizard._write_evidence(result=None, cancelled=False, interrupted=False)
    assert requested_sizes == [NWIPE_COMPLETION_LOG_BYTES]


def test_deeply_nested_evidence_fails_closed_for_recovery_and_export(tmp_path):
    path = tmp_path / "result-deep.json"
    data = b"[" * 1500 + b"0" + b"]" * 1500
    path.write_bytes(data)
    path.with_name(path.name + ".sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  {path.name}\n"
    )
    assert recover_result(path).code == "indeterminate"
    with pytest.raises(SafetyError, match=EVIDENCE_MALFORMED):
        prepare_terminal_evidence(path, "/dev/sdz")


def test_oversized_evidence_file_is_rejected_before_loading(tmp_path):
    path = tmp_path / "oversized.json"
    with path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(SafetyError):
        _read_regular_nofollow(path)


def test_oversized_evidence_is_rejected_before_publication(tmp_path):
    path = tmp_path / "oversized.json"
    with pytest.raises(SafetyError):
        _atomic_write_json(path, {"blob": "x" * (16 * 1024 * 1024)})
    assert not path.exists()
