"""Fake stop interruptions must retain a usable stop path."""

import threading

from beamo_wipe.models import Screen
from test_refresh_disks import authorized


def test_interrupted_cancel_returns_to_working_for_explicit_retry(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    assert wizard.screen == Screen.WORKING

    def interrupted_cancel():
        raise KeyboardInterrupt()

    monkeypatch.setattr(wizard.runner, "cancel", interrupted_cancel)
    raised = None
    try:
        wizard.cancel_wipe()
    except BaseException as exc:
        raised = exc

    assert raised is None
    assert wizard.screen == Screen.WORKING
    assert wizard.error
    assert not wizard._cancel_requested
    assert wizard.wipe_result is None


def test_interrupted_stop_worker_start_restores_retry_path(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    assert wizard.screen == Screen.WORKING

    def interrupted_start(_self):
        raise KeyboardInterrupt()

    monkeypatch.setattr("beamo_wipe.wizard.threading.Thread.start", interrupted_start)
    raised = None
    try:
        started = wizard.begin_cancel()
    except BaseException as exc:
        raised = exc
        started = None

    assert raised is None
    assert started is False
    assert wizard.screen == Screen.WORKING
    assert not wizard._cancel_requested
    assert wizard.error


def test_spawned_stop_worker_aborts_when_start_reports_interruption(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    assert wizard.screen == Screen.WORKING
    cancellations = []
    monkeypatch.setattr(wizard.runner, "cancel", lambda: cancellations.append(True))
    original_start = threading.Thread.start
    spawned = []

    def spawned_then_interrupted(worker):
        original_start(worker)
        spawned.append(worker)
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        "beamo_wipe.wizard.threading.Thread.start", spawned_then_interrupted
    )
    assert not wizard.begin_cancel()
    for worker in spawned:
        worker.join(timeout=1)
        assert not worker.is_alive()

    assert cancellations == []
    assert wizard.screen == Screen.WORKING
    assert not wizard._cancel_requested
