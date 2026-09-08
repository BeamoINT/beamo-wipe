"""Runner error handling with fake processes and no disk writes."""

import stat
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import MethodId, Screen, WipeRequest, WipeResult
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.safety import SafetyError


def request(tmp_path):
    return WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(tmp_path / "nwipe.log"))


def test_invalid_lock_file_is_closed_once(tmp_path, monkeypatch):
    runner = NwipeRunner()
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    close = Mock()
    with monkeypatch.context() as patch:
        patch.setattr("beamo_wipe.nwipe_runner.os.open", lambda *a, **kw: 91)
        patch.setattr("beamo_wipe.nwipe_runner.os.fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFIFO))
        patch.setattr("beamo_wipe.nwipe_runner.os.close", close)
        with pytest.raises(SafetyError, match="regular file"):
            runner._acquire_wipe_lock(request(tmp_path))
    close.assert_called_once_with(91)
    assert runner._lock_fd is None


@pytest.mark.parametrize("error", [OSError("status unavailable"), AttributeError("status unavailable")])
def test_process_status_failure_reaches_wizard(tmp_path, monkeypatch, error):
    w = make_demo_wizard()
    runner = NwipeRunner()
    proc = Mock()
    proc.poll.side_effect = error
    runner._proc = proc
    w.runner = runner
    w.screen = Screen.WORKING
    w._wipe_request = request(tmp_path)
    monkeypatch.setattr("beamo_wipe.nwipe_runner._try_log_diag", Mock())
    w.tick()
    assert w.error and "status" in w.error.lower()
    assert "may still be erasing" in w.error
    assert w.screen == Screen.WORKING
    assert w.wipe_result is None
    assert runner._proc is proc
    w.shutdown()
    assert not w.wants_shutdown
    proc.terminate.assert_not_called()


@pytest.mark.parametrize("terminal", [False, True])
def test_recovered_poll_clears_obsolete_status_warning(tmp_path, monkeypatch, terminal):
    w = make_demo_wizard()
    w.screen = Screen.WORKING
    w._wipe_request = request(tmp_path)
    result = WipeResult(False, 1, "Process failed", w._wipe_request.logfile) if terminal else None
    w.runner.poll = Mock(side_effect=[SafetyError("status unavailable"), result])
    monkeypatch.setattr(w, "_write_evidence", Mock())
    w.tick()
    assert w.error and "may still be erasing" in w.error
    revision = w.report_view.revision
    w.tick()
    assert w.error is None
    assert w.report_view.revision > revision
    assert w.screen == (Screen.DONE if terminal else Screen.WORKING)


def test_healthy_poll_preserves_unrelated_warning(tmp_path):
    w = make_demo_wizard()
    w.screen = Screen.WORKING
    w._wipe_request = request(tmp_path)
    w.runner.poll = Mock(return_value=None)
    w.error = "A wipe is already running."
    w.tick()
    assert w.error == "A wipe is already running."


def test_failed_old_poll_preserves_concurrent_terminal_result(tmp_path, monkeypatch):
    runner = NwipeRunner()
    result = WipeResult(False, 143, "cancelled", str(tmp_path / "nwipe.log"))

    def cancelled_during_poll():
        runner._proc = None
        runner.result = result
        raise OSError("old process unavailable")

    proc = Mock()
    proc.poll.side_effect = cancelled_during_poll
    runner._proc = proc
    monkeypatch.setattr("beamo_wipe.nwipe_runner._try_log_diag", Mock())
    assert runner.poll(request(tmp_path)) is result


def test_unavailable_poll_still_allows_confirmed_cancellation(tmp_path, monkeypatch):
    w = make_demo_wizard()
    runner = NwipeRunner()
    proc = Mock(returncode=-15)
    proc.poll.side_effect = OSError("status unavailable")
    proc.wait.return_value = -15
    runner._proc = proc
    w.runner = runner
    w.screen = Screen.WORKING
    w._wipe_request = request(tmp_path)
    monkeypatch.setattr("beamo_wipe.nwipe_runner._try_log_diag", Mock())
    monkeypatch.setattr(w, "_write_evidence", Mock())
    w.tick()
    w.cancel_wipe()
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=8)
    assert w.screen == Screen.DONE
    assert not w.wipe_result.ok
    assert runner._proc is None


def test_confirmed_completion_clears_failed_stop_warning(tmp_path, monkeypatch):
    from beamo_wipe.outcomes import VIEWS

    w = make_demo_wizard()
    w.screen = Screen.WORKING
    w._wipe_request = request(tmp_path)
    w.error = VIEWS["stop_unconfirmed"].announcement
    w.runner.poll = Mock(return_value=WipeResult(False, 1, "Process failed", w._wipe_request.logfile))
    monkeypatch.setattr(w, "_write_evidence", Mock())
    w.tick()
    assert w.screen == Screen.DONE
    assert w.error is None
