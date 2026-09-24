# SPDX-License-Identifier: GPL-3.0-or-later
"""A late Stop request must not rewrite a completed engine outcome."""

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner


class _AlreadyExited:
    returncode = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        raise ProcessLookupError("already exited")

    def wait(self, timeout=None):
        return self.returncode


class _ExitsDuringStop(_AlreadyExited):
    def __init__(self):
        self.returncode = None

    def terminate(self):
        self.returncode = 0
        raise ProcessLookupError("exited before signal")


class _StoppedBySignal(_ExitsDuringStop):
    def terminate(self):
        self.signalled = True

    def wait(self, timeout=None):
        assert self.signalled
        self.returncode = -15
        return self.returncode


class _UnobservedFailure(_ExitsDuringStop):
    def poll(self):
        self.returncode = 1
        return self.returncode

    def terminate(self):
        raise AssertionError("a finished process must not be signalled")


class _FailureAtSignalBoundary(_ExitsDuringStop):
    def terminate(self):
        # A changed returncode alone cannot prove whether a signal was sent.
        self.returncode = 1


class _DisappearedFailure(_ExitsDuringStop):
    def terminate(self):
        self.returncode = 5
        raise ProcessLookupError("child exited before SIGTERM")


def _runner(tmp_path, log_text):
    logfile = tmp_path / "nwipe-vda.log"
    logfile.write_text(log_text, encoding="utf-8")
    request = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(logfile),
    )
    runner = NwipeRunner(binary=str(tmp_path / "fake-nwipe"))
    runner._proc = _AlreadyExited()
    runner._active_request = request
    runner._last_logfile = str(logfile)
    return runner


def test_cancel_after_proven_completion_keeps_completed_result(tmp_path):
    runner = _runner(tmp_path, "vda | Erased |\n")
    runner.cancel()
    assert runner.result is not None
    assert runner.result.ok is True
    assert runner.result.reason == "completed"
    assert runner.result.exit_code == 0


def test_cancel_after_exit_without_completion_keeps_missing_evidence(tmp_path):
    runner = _runner(tmp_path, "Nwipe successfully completed.\n")
    runner.cancel()
    assert runner.result is not None
    assert runner.result.ok is False
    assert runner.result.reason == "completion_missing"
    assert runner.result.exit_code == 0


def test_natural_exit_racing_stop_keeps_proven_completion(tmp_path):
    runner = _runner(tmp_path, "vda | Erased |\n")
    runner._proc = _ExitsDuringStop()
    runner.cancel()
    assert runner.result is not None
    assert runner.result.ok is True
    assert runner.result.reason == "completed"


def test_running_process_stopped_by_signal_is_cancelled(tmp_path):
    runner = _runner(tmp_path, "")
    runner._proc = _StoppedBySignal()
    runner.cancel()
    assert runner.result is not None
    assert runner.result.ok is False
    assert runner.result.reason == "cancelled"


def test_unobserved_preexisting_failure_is_not_relabelled_cancelled(tmp_path):
    runner = _runner(tmp_path, "vda |-FAILED-|\n")
    runner._proc = _UnobservedFailure()
    runner.cancel()
    assert runner.result is not None
    assert runner.result.ok is False
    assert runner.result.reason == "engine_failed"
    assert runner.result.exit_code == 1


def test_ambiguous_signal_delivery_stays_cancelled(tmp_path):
    runner = _runner(tmp_path, "vda |-FAILED-|\n")
    runner._proc = _FailureAtSignalBoundary()
    runner.cancel()
    assert runner.result is not None
    assert runner.result.reason == "cancelled"
    assert runner.result.exit_code == 1


def test_process_lookup_failure_uses_terminal_engine_result(tmp_path):
    runner = _runner(tmp_path, "vda |-FAILED-|\n")
    runner._proc = _DisappearedFailure()
    runner.cancel()
    assert runner.result is not None
    assert runner.result.reason == "engine_failed"
    assert runner.result.exit_code == 5
