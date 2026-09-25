"""Report export must reject an unsafe pre-existing mount coordination lock."""

import os
from types import SimpleNamespace

import pytest

from beamo_wipe import support_export as export
from beamo_wipe.safety import SafetyError


def test_export_rejects_fifo_mount_lock_before_mount(tmp_path, monkeypatch):
    root = tmp_path / "run"
    root.mkdir(mode=0o700)
    os.mkfifo(root / ".lock", 0o600)
    monkeypatch.setattr(export, "MOUNT_ROOT", root)

    def should_not_mount(*_args, **_kwargs):
        pytest.fail("report worker reached mount with an unsafe lock")

    monkeypatch.setattr(export, "_run_command", should_not_mount)

    with pytest.raises(SafetyError, match="Could not verify the report USB mount"):
        export._persist_and_verify_report(
            SimpleNamespace(fstype="vfat"), None, b"", "unavailable", 0
        )


def test_export_rejects_public_regular_mount_lock_before_mount(tmp_path, monkeypatch):
    root = tmp_path / "run"
    root.mkdir(mode=0o700)
    lock = root / ".lock"
    lock.write_bytes(b"unrelated work")
    lock.chmod(0o644)
    monkeypatch.setattr(export, "MOUNT_ROOT", root)

    def should_not_mount(*_args, **_kwargs):
        pytest.fail("report worker reached mount with an unsafe lock")

    monkeypatch.setattr(export, "_run_command", should_not_mount)

    with pytest.raises(SafetyError, match="Could not verify the report USB mount"):
        export._persist_and_verify_report(
            SimpleNamespace(fstype="vfat"), None, b"", "unavailable", 0
        )

    assert lock.read_bytes() == b"unrelated work"


def test_export_rejects_lock_name_replaced_during_acquisition(tmp_path, monkeypatch):
    root = tmp_path / "run"
    root.mkdir(mode=0o700)
    lock = root / ".lock"
    lock.touch(mode=0o600)
    monkeypatch.setattr(export, "MOUNT_ROOT", root)
    real_flock = export.fcntl.flock

    def swap_after_lock(fd, operation):
        real_flock(fd, operation)
        lock.rename(root / "old-lock")
        lock.touch(mode=0o600)

    monkeypatch.setattr(export.fcntl, "flock", swap_after_lock)
    monkeypatch.setattr(
        export,
        "_run_command",
        lambda *_args, **_kwargs: pytest.fail("report worker reached mount after lock swap"),
    )

    with pytest.raises(SafetyError, match="Could not verify the report USB mount"):
        export._persist_and_verify_report(
            SimpleNamespace(fstype="vfat"), None, b"", "unavailable", 0
        )
