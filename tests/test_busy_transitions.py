"""Deterministic event barriers; fake disks and processes only."""

import copy
import subprocess
import threading
from dataclasses import replace

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.safety import SafetyError


@pytest.fixture
def ready(monkeypatch, tmp_path):
    w = make_demo_wizard()
    w.preview = False
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(w, "_write_evidence", lambda **kwargs: None)
    w.skip_splash()
    w.accept_what()
    w.set_owner(True)
    w.continue_owner()
    w.select_disk(w.selectable[0].path)
    w.continue_pick()
    w.set_confirm_input(w.confirm.token)
    w.continue_confirm()
    w.continue_method()
    w._erase_until = 0
    w.runner._clock = lambda: 0
    return w


class Barrier:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait(self):
        self.entered.set()
        assert self.release.wait(5), "test barrier timed out"

    def join(self, w):
        self.release.set()
        w._operation_thread.join(5)
        assert not w._operation_thread.is_alive()


def incompatible(w, screen):
    selected, owner, method, token = w.selected, w.owner_ok, w.method, w.confirm_input
    w.back()
    w.shutdown()
    w.open_advanced()
    w.open_limits()
    w.open_report_help()
    w.open_diagnostic()
    w.refresh_disks()
    w.reset_for_preview()
    w.set_owner(False)
    w.set_confirm_input("bad")
    w.select_disk("/dev/fake")
    assert not w.begin_erase()
    assert not w.begin_cancel()
    assert not w.begin_report_export()
    assert not w.begin_evidence_retry()
    w.tick()
    assert w.screen == screen and not w.wants_shutdown
    assert (w.selected, w.owner_ok, w.method, w.confirm_input) == (
        selected,
        owner,
        method,
        token,
    )


@pytest.mark.parametrize(
    "outcome",
    ["valid", "changed", "boot_missing", "timeout", "invalid", "interface_lost"],
)
def test_checking_claim_is_responsive_and_validates_before_start(ready, outcome):
    w = ready
    barrier = Barrier()
    fresh = copy.deepcopy(w.discovery)
    w.dry_run = False

    def discover():
        barrier.wait()
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("fake-discovery", 1)
        if outcome == "invalid":
            return None
        if outcome == "changed":
            fresh.disks = tuple(
                replace(d, serial="CHANGED") if d.path == w.selected.path else d
                for d in fresh.disks
            )
            fresh.selectable = tuple(
                replace(d, serial="CHANGED") for d in fresh.selectable
            )
        if outcome == "boot_missing":
            fresh.boot = None
            fresh.boot_identified = False
        return fresh

    w._rediscover = discover
    assert w.begin_erase()
    try:
        assert barrier.entered.wait(2)
        assert not w.runner.started
        incompatible(w, Screen.CHECKING)
        if outcome == "interface_lost":
            w.interface_failed()
    finally:
        barrier.join(w)
    assert w.runner.started is (outcome == "valid")
    assert w.screen == (Screen.WORKING if outcome == "valid" else Screen.LAST_CHANCE)
    if outcome != "valid":
        assert w.error


@pytest.mark.parametrize(
    "outcome", ["cancelled", "timeout", "permission", "no_result", "completed"]
)
def test_stop_claim_rejects_duplicates_and_waits_for_confirmation(
    ready, monkeypatch, outcome
):
    w = ready
    w.confirm_erase()
    barrier = Barrier()
    calls = []

    def cancel():
        calls.append("cancel")
        barrier.wait()
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("fake-process", 2)
        if outcome == "permission":
            raise PermissionError("private details")
        if outcome != "no_result":
            w.runner.result = WipeResult(
                outcome == "completed",
                0 if outcome == "completed" else 143,
                "finished" if outcome == "completed" else "cancelled",
                w._wipe_request.logfile,
            )

    monkeypatch.setattr(w.runner, "cancel", cancel)
    assert w.begin_cancel()
    try:
        assert barrier.entered.wait(2)
        incompatible(w, Screen.STOPPING)
        w.cancel_wipe()
        w.interface_failed()
        assert calls == ["cancel"] and w.wipe_result is None
        # A poll that finished before the stop claim must not commit afterward.
        w._finish(WipeResult(True, 0, "finished", w._wipe_request.logfile))
        assert w.screen == Screen.STOPPING
    finally:
        barrier.join(w)
    if outcome in {"cancelled", "completed"}:
        assert w.screen == Screen.DONE
        assert w.wipe_result.ok is (outcome == "completed")
    else:
        assert w.screen == Screen.WORKING and w.error and not w._cancel_requested
        assert w.wipe_result is None
        assert "private details" not in w.error


@pytest.mark.parametrize("operation", ["start", "stop"])
def test_thread_creation_failure_releases_only_its_claim(ready, monkeypatch, operation):
    w = ready
    if operation == "stop":
        w.confirm_erase()

    def fail(_self):
        raise RuntimeError("no threads")

    monkeypatch.setattr(threading.Thread, "start", fail)
    assert not (w.begin_erase() if operation == "start" else w.begin_cancel())
    assert w.screen == (Screen.LAST_CHANCE if operation == "start" else Screen.WORKING)
    assert w.error and not w._cancel_requested


def test_interface_failure_during_launch_stops_owned_process(ready, monkeypatch):
    w = ready
    barrier = Barrier()
    original = w.runner.start

    def start(request):
        barrier.wait()
        original(request)

    monkeypatch.setattr(w.runner, "start", start)
    assert w.begin_erase()
    try:
        assert barrier.entered.wait(2)
        w.interface_failed()
    finally:
        barrier.join(w)
    assert w.runner.cancelled and w.screen == Screen.DONE
    assert not w.wipe_result.ok


def test_already_exited_result_is_preserved(ready):
    w = ready
    w.confirm_erase()
    w.runner._clock = lambda: 100
    w.cancel_wipe()
    assert w.screen == Screen.DONE and w.wipe_result.ok


@pytest.mark.parametrize("operation", ["poll", "cancel"])
def test_runner_does_not_publish_termination_before_cleanup(
    ready, monkeypatch, operation
):
    w = ready
    w.confirm_erase()
    runner = NwipeRunner()

    class FakeProc:
        returncode = 0

        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self, timeout):
            return 0

    proc = FakeProc()
    runner._proc = proc
    monkeypatch.setattr(runner, "_read_log_tail", lambda *args: "")

    def fail_cleanup():
        raise SafetyError("cleanup failed")

    monkeypatch.setattr(runner, "_release_wipe_lock", fail_cleanup)
    with pytest.raises(SafetyError):
        runner.poll(w._wipe_request) if operation == "poll" else runner.cancel()
    assert runner.result is None and runner._proc is proc


def test_runner_duplicate_cancel_does_not_signal_twice(monkeypatch):
    barrier = Barrier()
    calls = []

    class FakeProc:
        returncode = 143

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            barrier.wait()
            return 143

    runner = NwipeRunner()
    runner._proc = FakeProc()
    thread = threading.Thread(target=runner.cancel)
    thread.start()
    try:
        assert barrier.entered.wait(2)
        runner.cancel()
        assert calls == ["terminate"] and runner.result is None
    finally:
        barrier.release.set()
        thread.join(3)
    assert not thread.is_alive() and runner.result is not None


@pytest.mark.parametrize("failure", ["unlock", "close"])
def test_cleanup_errors_are_fail_closed_without_unsafe_descriptor_retry(
    monkeypatch, failure
):
    runner = NwipeRunner()
    runner._lock_fd = 999999  # sentinel only; every OS operation below is mocked
    calls = []

    def unlock(fd, operation):
        assert fd == 999999
        calls.append("unlock")
        if failure == "unlock":
            raise PermissionError("injected")

    def close(fd):
        assert fd == 999999
        calls.append("close")
        raise OSError("injected")

    monkeypatch.setattr("beamo_wipe.nwipe_runner.fcntl.flock", unlock)
    monkeypatch.setattr("beamo_wipe.nwipe_runner.os.close", close)
    monkeypatch.setattr("beamo_wipe.nwipe_runner._try_log_diag", lambda *args: None)
    with pytest.raises(SafetyError):
        runner._release_wipe_lock()
    assert runner.result is None
    if failure == "unlock":
        assert runner._lock_fd == 999999
        assert calls == ["unlock"]
    else:
        assert runner._lock_fd is None
        with pytest.raises(SafetyError):
            runner._release_wipe_lock()
        assert calls == ["unlock", "close"]


def test_unexpected_discovery_metadata_failure_is_visible(ready, monkeypatch):
    w = ready
    w.dry_run = False
    w._rediscover = lambda: w.discovery
    monkeypatch.setattr(
        "beamo_wipe.wizard.assert_boot_excluded",
        lambda *_: (_ for _ in ()).throw(TypeError("private details")),
    )
    w.confirm_erase()
    assert w.screen == Screen.LAST_CHANCE and not w.runner.started
    assert w.error and "private details" not in w.error
    assert w.startup_error_code == "unexpected_startup_failure"


def test_poll_cleanup_error_refreshes_warning_without_publishing_result(
    ready, monkeypatch
):
    w = ready
    w.confirm_erase()
    before = w.report_view.revision

    def fail(request):
        raise SafetyError("private details")

    monkeypatch.setattr(w.runner, "poll", fail)
    w.tick()
    after = w.report_view.revision
    assert after > before and w.error and "private details" not in w.error
    assert w.screen == Screen.WORKING and w.wipe_result is None
    w.tick()
    assert w.report_view.revision == after


def test_uncertain_cleanup_blocks_even_a_previously_unstarted_runner(
    ready, monkeypatch
):
    w = ready
    w.confirm_erase()
    runner = NwipeRunner()
    runner._cleanup_failed = True

    def forbidden(*args, **kwargs):
        pytest.fail("attempted subprocess startup after uncertain cleanup")

    monkeypatch.setattr("beamo_wipe.nwipe_runner.subprocess.Popen", forbidden)
    with pytest.raises(SafetyError, match="cleanup"):
        runner.start(w._wipe_request)


def test_stale_tk_callback_cannot_reactivate_same_named_screen():
    from types import SimpleNamespace

    pytest.importorskip("tkinter")
    from beamo_wipe.ui.tk_wizard import TkWizard

    calls = []
    ui = SimpleNamespace(
        w=SimpleNamespace(screen=Screen.LAST_CHANCE, wants_shutdown=False),
        _draw_generation=1,
        _draw=lambda: None,
        _teardown=lambda: None,
        _arm_shutdown_enter_if_idle=lambda: None,
    )
    stale = TkWizard._nav(ui, lambda: calls.append("stale"))
    ui._draw_generation += 1
    stale()
    assert not calls
    TkWizard._nav(ui, lambda: calls.append("current"))()
    assert calls == ["current"]
