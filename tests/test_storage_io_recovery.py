"""Storage error recovery using ordinary temporary files and mocked syscalls."""

import errno
import os
from unittest.mock import Mock, call

import pytest

from beamo_wipe import evidence
from beamo_wipe.report_intent import ReportIntentStore
from beamo_wipe.session_recovery import SessionStore
from beamo_wipe.safety import SafetyError


@pytest.mark.parametrize("kind", ["journal", "preference"])
def test_failed_metadata_check_closes_opened_descriptor(tmp_path, monkeypatch, kind):
    close = Mock()
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", Mock(return_value=91))
        patch.setattr(os, "fstat", Mock(side_effect=OSError(errno.EIO, "metadata unavailable")))
        patch.setattr(os, "close", close)
        with pytest.raises(OSError):
            if kind == "journal":
                SessionStore(tmp_path)._file("journal")
            else:
                ReportIntentStore(tmp_path)._directory_fd()
    close.assert_called_once_with(91)


def test_atomic_writer_does_not_retry_failed_close(tmp_path, monkeypatch):
    closed = []

    def close(fd):
        closed.append(fd)
        if fd == 91 and closed.count(91) == 1:
            raise OSError(errno.EIO, "close failed")

    link = Mock()
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", Mock(side_effect=[90, 91]))
        patch.setattr(os, "write", lambda fd, data: len(data))
        patch.setattr(os, "fsync", Mock())
        patch.setattr(os, "close", close)
        patch.setattr(os, "unlink", Mock())
        patch.setattr(os, "link", link)
        with pytest.raises(OSError):
            evidence._atomic_write_bytes(tmp_path / "result.json", b"{}")
    assert closed.count(91) == 1
    assert closed.count(90) == 1
    link.assert_not_called()


@pytest.mark.parametrize("kind", ["evidence", "preference"])
def test_cleanup_failure_still_closes_directory(tmp_path, monkeypatch, kind):
    close = Mock()
    store = ReportIntentStore(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_directory_fd", lambda: 90)
        patch.setattr(os, "open", Mock(side_effect=[90, 91] if kind == "evidence" else [91]))
        patch.setattr(os, "write", Mock(side_effect=OSError(errno.ENOSPC, "storage full")))
        patch.setattr(os, "close", close)
        patch.setattr(os, "unlink", Mock(side_effect=OSError(errno.EIO, "cleanup failed")))
        with pytest.raises(OSError):
            if kind == "evidence":
                evidence._atomic_write_bytes(tmp_path / "result.json", b"{}")
            else:
                store.save(True)
    assert close.call_args_list == [call(91), call(90)]


@pytest.mark.parametrize("chunk_size", [1, 7])
def test_short_journal_reads_preserve_valid_recovery(tmp_path, monkeypatch, chunk_size):
    directory = tmp_path / "private"
    kwargs = dict(boot="00000000-0000-0000-0000-000000000001", build="a" * 64)
    first = SessionStore(directory, **kwargs).open()
    expected = first.record
    first.close()
    original = os.read
    second = SessionStore(directory, **kwargs)
    try:
        monkeypatch.setattr(os, "read", lambda fd, size: original(fd, min(size, chunk_size)))
        second.open()
        assert second.previous and not second.invalid
        assert second.record == expected
    finally:
        second.close()


@pytest.mark.parametrize("wanted", [False, True])
def test_short_preference_reads_preserve_saved_intent(tmp_path, monkeypatch, wanted):
    tmp_path.chmod(0o700)
    store = ReportIntentStore(tmp_path)
    store.save(wanted)
    original = os.read
    monkeypatch.setattr(os, "read", lambda fd, size: original(fd, min(size, 2)))
    assert store.load() is wanted


@pytest.mark.parametrize("size", [16, 17])
def test_chunked_journal_read_keeps_exact_size_limit(tmp_path, monkeypatch, size):
    path = tmp_path / "sample"
    path.write_bytes(b"x" * size)
    path.chmod(0o600)
    store = SessionStore(tmp_path)
    store.fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original = os.read
    monkeypatch.setattr("beamo_wipe.session_recovery.LIMIT", 16)
    monkeypatch.setattr(os, "read", lambda fd, amount: original(fd, min(amount, 3)))
    try:
        if size == 16:
            assert store.read("sample") == b"x" * size
        else:
            with pytest.raises(SafetyError, match="too large"):
                store.read("sample")
    finally:
        store.close()


def test_chunked_preference_rejects_trailing_data_with_bounded_reads(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    store = ReportIntentStore(tmp_path)
    store.save(True)
    (tmp_path / store.NAME).write_bytes(b"wanted\n" + b"x" * 100)
    original = os.read
    received = []

    def read(fd, amount):
        chunk = original(fd, min(amount, 2))
        received.append(chunk)
        return chunk

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(SafetyError, match="Invalid report preference"):
        store.load()
    assert sum(map(len, received)) == 32
