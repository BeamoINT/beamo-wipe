"""Global runner exclusion using fake engines; never opens a device."""

from unittest.mock import Mock

import pytest

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.safety import SafetyError


def test_active_wipe_excludes_other_approved_log_directories(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    requests = []
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        log = directory / "nwipe.log"
        log.write_text("preserve existing evidence\n")
        requests.append(WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(log)))
    processes = [Mock(returncode=-15), Mock(returncode=-15)]
    popen = Mock(side_effect=processes)
    monkeypatch.setattr("beamo_wipe.nwipe_runner.subprocess.Popen", popen)
    runners = [NwipeRunner(binary=str(tmp_path / "fake_engine")) for _ in requests]
    try:
        runners[0].start(requests[0])
        with pytest.raises(SafetyError, match="already running"):
            runners[1].start(requests[1])
        assert popen.call_count == 1
        assert (tmp_path / "second" / "nwipe.log").read_text() == "preserve existing evidence\n"
        assert runners[1]._proc is None
        assert runners[1]._lock_fd is None
        runners[0].cancel()
        runners[1].start(requests[1])
        assert popen.call_count == 2
        assert runners[1]._proc is processes[1]
    finally:
        for runner in runners:
            runner.cancel()


def test_other_log_directory_is_excluded_before_engine_exec(tmp_path, monkeypatch):
    """Hold the first start inside fake Popen while a second runner starts."""
    import threading

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    requests = []
    for name, target in (("first", "/dev/vda"), ("second", "/dev/vdb")):
        directory = tmp_path / name
        directory.mkdir()
        requests.append(WipeRequest(target, MethodId.EVERYDAY, "/dev/sr0", str(directory / "nwipe.log")))
    entered, release = threading.Event(), threading.Event()
    proc = Mock(returncode=-15)
    errors = []

    def popen(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return proc

    monkeypatch.setattr("beamo_wipe.nwipe_runner.subprocess.Popen", popen)
    first, second = [NwipeRunner(binary=str(tmp_path / "fake_engine")) for _ in requests]

    def start_first():
        try:
            first.start(requests[0])
        except BaseException as exc:
            errors.append(exc)

    starting = threading.Thread(target=start_first)
    starting.start()
    try:
        assert entered.wait(3)
        assert first._proc is None  # no engine is yet visible to process scanning
        with pytest.raises(SafetyError, match="already running"):
            second.start(requests[1])
        assert not (tmp_path / "second" / "nwipe.log").exists()
    finally:
        release.set()
        starting.join(3)
        first.cancel()
        second.cancel()
    assert not starting.is_alive()
    assert not errors
