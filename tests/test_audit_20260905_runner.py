"""Fake-process regression proofs for the September 5 accountable audit."""
import threading

import pytest

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner, evaluate_nwipe_outcome


@pytest.mark.parametrize("suffix", [", pass nope of 3", ", pass 1 of", ", pass 3 of 3garbage"])
def test_malformed_progress_never_proves_completion(suffix):
    text = f"/dev/vda: 100.00%, round 1 of 1{suffix}\n"
    assert evaluate_nwipe_outcome(0, text, "/dev/vda")[0] is False


def test_cancel_snapshot_cannot_discard_a_later_run(tmp_path, monkeypatch):
    """Pause old cancel.wait while poll completes and the runner is retried."""
    entered = threading.Event()
    release = threading.Event()

    class FakeProc:
        returncode = 0

        def terminate(self):
            pass

        def poll(self):
            return 0

        def wait(self, timeout):
            entered.set()
            assert release.wait(3)
            return 0

    runner = NwipeRunner(binary=str(tmp_path / "fake_engine"))
    old = FakeProc()
    runner._proc = old
    request = WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(tmp_path / "nwipe.log"))
    monkeypatch.setattr(runner, "_read_log_tail", lambda *args: "vda | Erased |\n")
    cancellations = []

    def cancel():
        try:
            runner.cancel()
        except BaseException as exc:
            cancellations.append(exc)

    thread = threading.Thread(target=cancel)
    thread.start()
    assert entered.wait(3)
    try:
        assert runner.poll(request).ok
        # Exercise real start validation and file locking with a fake subprocess.
        new = FakeProc()
        new.returncode = None
        monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
        monkeypatch.setattr("beamo_wipe.nwipe_runner.subprocess.Popen", lambda *a, **kw: new)
        runner.start(request)
        assert runner._proc is new
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert not cancellations
    try:
        assert runner._proc is new, "stale cancellation lost the newer running engine"
        assert runner.result is None
    finally:
        runner._release_wipe_lock()


def test_poll_releases_only_its_own_run_lock(tmp_path, monkeypatch):
    """A new request in another approved log subdirectory keeps its lock."""
    import fcntl
    import os

    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    request = WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(old_dir / "nwipe.log"))
    retry = WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(new_dir / "nwipe.log"))

    class FakeProc:
        returncode = 0

        def poll(self):
            return self.returncode

    runner = NwipeRunner(binary=str(tmp_path / "fake_engine"))
    runner._proc = FakeProc()
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    runner._acquire_wipe_lock(request)
    old_fd = runner._lock_fd
    new = FakeProc()
    new.returncode = None
    monkeypatch.setattr("beamo_wipe.nwipe_runner.subprocess.Popen", lambda *a, **kw: new)
    monkeypatch.setattr(runner, "_read_log_tail", lambda *args: "vda | Erased |\n")
    release_entered, allow_release, started = threading.Event(), threading.Event(), threading.Event()
    release_lock = runner._release_wipe_lock
    errors = []

    def pause_release():
        release_entered.set()
        assert allow_release.wait(3)
        release_lock()

    def finish():
        try:
            runner.poll(request)
        except BaseException as exc:
            errors.append(exc)

    def start_retry():
        try:
            runner.start(retry)
        except BaseException as exc:
            errors.append(exc)
        finally:
            started.set()

    monkeypatch.setattr(runner, "_release_wipe_lock", pause_release)
    finishing = threading.Thread(target=finish)
    finishing.start()
    assert release_entered.wait(3)
    starting = threading.Thread(target=start_retry)
    starting.start()
    # Before the fix, retry enters while the old completion is releasing its lock.
    started.wait(0.2)
    allow_release.set()
    finishing.join(3)
    starting.join(3)
    try:
        assert not finishing.is_alive() and not starting.is_alive()
        assert not errors
        assert runner._proc is new
        fd = os.open(tmp_path / "wipe.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
    finally:
        release_lock()
        # The broken transition also leaks the old descriptor.
        try:
            os.close(old_fd)
        except OSError:
            pass
