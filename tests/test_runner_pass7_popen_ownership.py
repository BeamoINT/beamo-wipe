"""A parent-side Popen error after fork cannot relinquish the wipe lock."""

import errno
import subprocess

import pytest

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.safety import SafetyError


def _request(tmp_path):
    return WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )


def test_parent_side_popen_oserror_retains_possible_child_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    runner = NwipeRunner(binary="/bin/true")
    contender = NwipeRunner(binary="/bin/true")
    real_popen = subprocess.Popen
    child = None

    def parent_read_failed_after_fork(_argv, **kwargs):
        nonlocal child
        child = real_popen(
            ["/bin/sleep", "10"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=kwargs["pass_fds"],
            start_new_session=True,
        )
        raise OSError(errno.EIO, "parent-side exec pipe read failed")

    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.subprocess.Popen", parent_read_failed_after_fork
    )
    try:
        with pytest.raises(OSError, match="pipe read failed"):
            runner.start(_request(tmp_path))
        assert child is not None and child.poll() is None
        assert runner._lock_fd is not None
        assert not runner.start_not_spawned()
        with pytest.raises(SafetyError, match="already running"):
            contender._acquire_wipe_lock(_request(tmp_path))
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=2)
        if runner._lock_fd is not None:
            runner._release_wipe_lock()
        if contender._lock_fd is not None:
            contender._release_wipe_lock()


def test_real_failed_exec_remains_retryable(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    runner = NwipeRunner(binary=str(tmp_path / "missing-engine"))
    with pytest.raises(FileNotFoundError):
        runner.start(_request(tmp_path))
    assert runner.start_not_spawned()
