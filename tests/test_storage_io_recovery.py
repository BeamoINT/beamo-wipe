"""Storage error recovery using ordinary temporary files and mocked syscalls."""

import errno
import fcntl
import os
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from beamo_wipe import evidence
from beamo_wipe import support_export
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
    write = Mock(side_effect=lambda fd, data: len(data))

    def close(fd):
        closed.append(fd)
        if fd == 91 and closed.count(91) == 1:
            raise OSError(errno.EIO, "close failed")

    link = Mock()
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", Mock(side_effect=[90, 91]))
        patch.setattr(
            os, "fstat", Mock(return_value=SimpleNamespace(st_dev=1, st_ino=2))
        )
        patch.setattr(os, "stat", Mock(side_effect=FileNotFoundError()))
        patch.setattr(os, "write", write)
        patch.setattr(os, "fsync", Mock())
        patch.setattr(os, "close", close)
        patch.setattr(os, "unlink", Mock())
        patch.setattr(os, "link", link)
        with pytest.raises(OSError):
            evidence._atomic_write_bytes(tmp_path / "result.json", b"{}")
    assert closed.count(91) == 1
    assert closed.count(90) == 1
    write.assert_called_once()
    link.assert_not_called()


@pytest.mark.parametrize("kind", ["evidence", "preference"])
def test_cleanup_failure_still_closes_directory(tmp_path, monkeypatch, kind):
    close = Mock()
    write = Mock(side_effect=OSError(errno.ENOSPC, "storage full"))
    unlink = Mock(side_effect=OSError(errno.EIO, "cleanup failed"))
    store = ReportIntentStore(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_directory_fd", lambda: 90)
        patch.setattr(
            os, "open", Mock(side_effect=[90, 91] if kind == "evidence" else [91])
        )
        if kind == "evidence":
            identity = SimpleNamespace(st_dev=1, st_ino=2)
            patch.setattr(os, "fstat", Mock(return_value=identity))
            patch.setattr(os, "stat", Mock(return_value=identity))
        patch.setattr(os, "write", write)
        patch.setattr(os, "close", close)
        patch.setattr(os, "unlink", unlink)
        with pytest.raises(OSError):
            if kind == "evidence":
                evidence._atomic_write_bytes(tmp_path / "result.json", b"{}")
            else:
                store.save(True)
    assert close.call_args_list == [call(91), call(90)]
    write.assert_called_once()
    unlink.assert_called_once()


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


def test_non_contention_wipe_lock_error_closes_descriptor(tmp_path, monkeypatch):
    store = SessionStore(
        tmp_path / "private",
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    opened = []
    real_file = store._file

    def track_file(name, *args):
        fd = real_file(name, *args)
        if name == "wipe.lock":
            opened.append(fd)
        return fd

    def fail_lock(fd, *_args):
        if fd in opened:
            raise OSError(errno.EIO, "fake lock I/O failure")
        return real_flock(fd, *_args)

    real_flock = fcntl.flock
    try:
        with monkeypatch.context() as patch:
            patch.setattr(store, "_file", track_file)
            patch.setattr(fcntl, "flock", fail_lock)
            for _ in range(3):
                with pytest.raises(OSError, match="fake lock"):
                    store.is_quiescent()
        assert store.quiescent == -1
        for fd in opened:
            with pytest.raises(OSError) as exc:
                os.fstat(fd)
            assert exc.value.errno == errno.EBADF
    finally:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass
        store.close()


@pytest.mark.parametrize("operation", ["write", "verify"])
def test_report_bundle_close_error_still_closes_all_directories(tmp_path, monkeypatch, operation):
    data = b"{}"
    name = "report-" + "a" * 24
    files = None
    if operation == "verify":
        _, files = support_export.write_report_bundle(
            tmp_path, data, b"", "unavailable", session_name=name
        )
    real_open, real_close = os.open, os.close
    directories = []
    failed = False

    def track_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if flags & os.O_DIRECTORY:
            directories.append(fd)
        return fd

    def fail_first_directory_close(fd):
        nonlocal failed
        if directories and fd == directories[-1] and not failed:
            failed = True
            real_close(fd)
            raise OSError(errno.EIO, "fake directory close failure")
        return real_close(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", track_open)
            patch.setattr(os, "close", fail_first_directory_close)
            with pytest.raises(OSError, match="fake directory close failure"):
                if operation == "write":
                    support_export.write_report_bundle(
                        tmp_path, data, b"", "unavailable", session_name=name
                    )
                else:
                    support_export.verify_report_bundle(tmp_path, name, files)
        assert failed and len(directories) == 3
        for fd in directories:
            with pytest.raises(OSError) as exc:
                os.fstat(fd)
            assert exc.value.errno == errno.EBADF
    finally:
        for fd in directories:
            try:
                real_close(fd)
            except OSError:
                pass


def test_ambiguous_session_close_clears_all_owned_descriptors(tmp_path, monkeypatch):
    store = SessionStore(
        tmp_path / "private",
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    assert store.is_quiescent()
    quiescent_fd = store.quiescent
    real_close = os.close
    failed = False
    unrelated_fd = -1

    def ambiguous_close(fd):
        nonlocal failed
        if fd == quiescent_fd and not failed:
            failed = True
            real_close(fd)
            raise OSError(errno.EIO, "fake ambiguous close")
        return real_close(fd)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "close", ambiguous_close)
            with pytest.raises(OSError, match="fake ambiguous close"):
                store.close()
        assert (store.quiescent, store.owner, store.fd) == (-1, -1, -1)
        source_fd = os.open(tmp_path / "unrelated", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            unrelated_fd = os.dup2(source_fd, quiescent_fd)
        finally:
            if source_fd != quiescent_fd:
                real_close(source_fd)
        store.close()
        os.fstat(unrelated_fd)
    finally:
        for fd in {unrelated_fd, store.quiescent, store.owner, store.fd}:
            if fd >= 0:
                try:
                    real_close(fd)
                except OSError:
                    pass
