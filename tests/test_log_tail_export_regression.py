"""The exported log must match the exact bytes authenticated at completion."""

import hashlib

from beamo_wipe.nwipe_runner import (
    NWIPE_COMPLETION_LOG_BYTES, NWIPE_PROGRESS_LOG_BYTES, NwipeRunner,
)
from beamo_wipe.support_export import read_export_log


def test_utf8_split_at_completion_tail_boundary_remains_exportable(tmp_path):
    path = tmp_path / "nwipe.log"
    path.write_bytes("é".encode() * (NWIPE_COMPLETION_LOG_BYTES // 2) + b"x")
    tail = NwipeRunner()._read_log_tail(str(path), NWIPE_COMPLETION_LOG_BYTES)
    authenticated = tail.encode("utf-8")
    assert tail.startswith("�")  # The runner decoded a split UTF-8 character.

    exported, status = read_export_log(
        str(path),
        expected_sha256=hashlib.sha256(authenticated).hexdigest(),
        expected_size_bytes=len(authenticated),
    )
    assert exported == authenticated
    assert status == "tail"


def test_utf8_split_at_interrupted_progress_tail_remains_exportable(tmp_path):
    path = tmp_path / "nwipe.log"
    path.write_bytes("é".encode() * (NWIPE_PROGRESS_LOG_BYTES // 2) + b"x")
    tail = NwipeRunner()._read_log_tail(str(path), NWIPE_PROGRESS_LOG_BYTES)
    authenticated = tail.encode("utf-8")
    assert tail.startswith("�")

    exported, status = read_export_log(
        str(path),
        expected_sha256=hashlib.sha256(authenticated).hexdigest(),
        expected_size_bytes=len(authenticated),
    )
    assert exported == authenticated
    assert status == "tail"
