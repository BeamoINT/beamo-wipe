"""Failure paths use fake disks and private temporary files only."""

import hashlib
import os
import threading
from types import SimpleNamespace

import tkinter as tk
import pytest

from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.session_recovery import SessionStore
from beamo_wipe.support_export import read_export_log
from test_refresh_disks import authorized


def test_invalid_terminal_journal_does_not_offer_evidence_retry(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.enable_session_recovery(store)
        wizard.confirm_erase()
        assert wizard.screen == Screen.WORKING
        original_fsync = os.fsync

        def fail_journal_sync(fd):
            if fd == store.fd:
                raise OSError(5, "simulated terminal journal sync failure")
            return original_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_journal_sync)
            wizard._finish(WipeResult(True, 0, "finished", wizard._wipe_request.logfile))
        assert store.invalid
        assert wizard.screen == Screen.DONE and wizard.evidence_error
        assert not wizard.can_retry_evidence
        assert not wizard.retry_evidence_save()
    finally:
        store.close()


def test_optional_export_log_close_failure_omits_log(tmp_path, monkeypatch):
    path = tmp_path / "nwipe.log"
    data = b"fake nwipe log\n"
    path.write_bytes(data)
    target_fd = None
    real_open, real_close = os.open, os.close

    def track_open(*args, **kwargs):
        nonlocal target_fd
        target_fd = real_open(*args, **kwargs)
        return target_fd

    def fail_close(fd):
        if fd == target_fd:
            real_close(fd)
            raise OSError(5, "simulated close failure")
        return real_close(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", track_open)
        patch.setattr(os, "close", fail_close)
        result = read_export_log(
            str(path),
            expected_sha256=hashlib.sha256(data).hexdigest(),
            expected_size_bytes=len(data),
        )
    assert result == (b"", "unavailable")


def test_tk_runtime_failure_confirms_stop_when_stop_worker_cannot_start(tmp_path, monkeypatch):
    from beamo_wipe.ui.tk_wizard import TkWizard

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    assert wizard.screen == Screen.WORKING
    app = TkWizard.__new__(TkWizard)
    app.w = wizard
    app._shown = None
    app._shown_report_revision = 0
    app._fatal_ui = False
    app._after_id = "existing-timer"
    app.root = SimpleNamespace(after=lambda *_args: None)
    app._arm_shutdown_enter_if_idle = lambda: None
    app._draw = lambda: (_ for _ in ()).throw(tk.TclError("fake display failure"))
    app._teardown = lambda: None

    def fail_start(_self):
        raise RuntimeError("no threads")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", fail_start)
        app._tick()
    assert app._fatal_ui
    assert wizard.screen == Screen.DONE
    assert wizard.wipe_result is not None and not wizard.wipe_result.ok


def test_plain_console_eof_retries_failed_stop_before_exit(tmp_path, monkeypatch):
    from beamo_wipe.ui import console_wizard

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    real_cancel = wizard.runner.cancel
    calls = []

    def transient_cancel_failure():
        calls.append(1)
        if len(calls) == 1:
            raise OSError(5, "fake stop failure")
        return real_cancel()

    monkeypatch.setattr(wizard.runner, "cancel", transient_cancel_failure)
    monkeypatch.setattr(console_wizard.select, "select", lambda *_args: ([None], [], []))
    monkeypatch.setattr(console_wizard.sys, "stdin", SimpleNamespace(readline=lambda: ""))
    assert console_wizard._plain_loop(wizard) == 0
    assert len(calls) >= 2
    assert wizard.screen == Screen.DONE and wizard.wipe_result is not None


def test_failed_interface_observes_natural_completion_after_cancel_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    real_cancel = wizard.runner.cancel
    allow_cleanup = threading.Event()
    polls = []

    def completed_poll(_request):
        polls.append(1)
        if len(polls) >= 3:
            return WipeResult(True, 0, "finished", wizard._wipe_request.logfile)
        return None

    def failed_cancel():
        if not allow_cleanup.is_set():
            raise OSError(5, "fake repeated stop failure")
        return real_cancel()

    monkeypatch.setattr(wizard.runner, "poll", completed_poll)
    monkeypatch.setattr(wizard.runner, "cancel", failed_cancel)
    worker = threading.Thread(target=wizard.settle_failed_interface, daemon=True)
    worker.start()
    worker.join(2)
    settled_before_cleanup = not worker.is_alive()
    allow_cleanup.set()
    worker.join(2)
    assert not worker.is_alive()
    assert settled_before_cleanup
    assert wizard.screen == Screen.DONE and wizard.wipe_result is not None


def test_failed_tick_does_not_prevent_retrying_system_stop(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    real_cancel = wizard.runner.cancel
    real_tick = wizard.tick
    allow_tick = threading.Event()
    stops = []

    def transient_stop_failure():
        stops.append(1)
        if len(stops) == 1:
            raise OSError(5, "fake stop failure")
        return real_cancel()

    def failed_tick():
        if not allow_tick.is_set():
            raise RuntimeError("fake UI tick failure")
        return real_tick()

    monkeypatch.setattr(wizard.runner, "cancel", transient_stop_failure)
    monkeypatch.setattr(wizard, "tick", failed_tick)
    worker = threading.Thread(target=wizard.settle_failed_interface, daemon=True)
    worker.start()
    worker.join(1)
    settled_before_tick_recovery = not worker.is_alive()
    allow_tick.set()
    worker.join(2)
    assert not worker.is_alive()
    assert settled_before_tick_recovery
    assert len(stops) >= 2 and wizard.screen == Screen.DONE


def test_first_fatal_stop_exception_keeps_monitoring(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    real_cancel = wizard.cancel_wipe
    calls = []

    def first_call_fails(*, origin="user"):
        calls.append(origin)
        if len(calls) == 1:
            raise OSError(5, "fake stop setup failure")
        return real_cancel(origin=origin)

    monkeypatch.setattr(wizard, "cancel_wipe", first_call_fails)
    wizard.settle_failed_interface()
    assert calls == ["system", "system"]
    assert wizard.screen == Screen.DONE and wizard.wipe_result is not None


def _failing_tk_on_done(wizard, closed):
    from beamo_wipe.ui.tk_wizard import TkWizard

    app = TkWizard.__new__(TkWizard)
    app.w = wizard
    app._shown = None
    app._shown_report_revision = 0
    app._fatal_ui = False
    app._after_id = "existing-timer"
    app.root = SimpleNamespace(after=lambda *_args: None)
    app._arm_shutdown_enter_if_idle = lambda: None
    app._draw = lambda: (_ for _ in ()).throw(tk.TclError("fake display failure"))
    app._teardown = lambda: closed.append(True)
    return app


def test_tk_failure_waits_for_terminal_evidence_write(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    entered, release = threading.Event(), threading.Event()
    closed = []

    def delayed_evidence(**_kwargs):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(wizard, "_write_evidence", delayed_evidence)
    finish_worker = threading.Thread(
        target=lambda: wizard._finish(
            WipeResult(True, 0, "finished", wizard._wipe_request.logfile)
        )
    )
    finish_worker.start()
    assert entered.wait(2)
    assert wizard.screen == Screen.DONE and wizard._finishing
    app = _failing_tk_on_done(wizard, closed)
    ui_worker = threading.Thread(target=app._tick)
    ui_worker.start()
    try:
        ui_worker.join(0.3)
        assert ui_worker.is_alive() and not closed
    finally:
        release.set()
        finish_worker.join(3)
        ui_worker.join(3)
    assert not finish_worker.is_alive() and not ui_worker.is_alive()
    assert closed == [True] and not wizard._finishing


def test_tk_failure_waits_for_report_export_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    wizard._finish(WipeResult(True, 0, "finished", wizard._wipe_request.logfile))
    assert wizard.screen == Screen.DONE
    wizard._report_exporting = True
    closed = []
    app = _failing_tk_on_done(wizard, closed)
    ui_worker = threading.Thread(target=app._tick)
    ui_worker.start()
    try:
        ui_worker.join(0.3)
        assert ui_worker.is_alive() and not closed
    finally:
        wizard._report_exporting = False
        ui_worker.join(3)
    assert not ui_worker.is_alive() and closed == [True]


@pytest.mark.parametrize("pending", ["evidence", "report"])
def test_plain_console_eof_waits_for_done_work(tmp_path, monkeypatch, pending):
    from beamo_wipe.ui import console_wizard

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    entered, release = threading.Event(), threading.Event()
    finish_worker = None
    if pending == "evidence":
        def delayed_evidence(**_kwargs):
            entered.set()
            assert release.wait(3)

        monkeypatch.setattr(wizard, "_write_evidence", delayed_evidence)
        finish_worker = threading.Thread(
            target=lambda: wizard._finish(
                WipeResult(True, 0, "finished", wizard._wipe_request.logfile)
            )
        )
        finish_worker.start()
        assert entered.wait(2)
        assert wizard._finishing
    else:
        wizard._finish(WipeResult(True, 0, "finished", wizard._wipe_request.logfile))
        wizard._report_exporting = True
    assert wizard.screen == Screen.DONE
    monkeypatch.setattr(console_wizard, "_plain_loop_body", lambda _w: (_ for _ in ()).throw(EOFError()))
    result = []
    console_worker = threading.Thread(target=lambda: result.append(console_wizard._plain_loop(wizard)))
    console_worker.start()
    try:
        console_worker.join(0.3)
        assert console_worker.is_alive() and not result
    finally:
        release.set()
        wizard._report_exporting = False
        if finish_worker is not None:
            finish_worker.join(3)
        console_worker.join(3)
    assert not console_worker.is_alive() and result == [0]
