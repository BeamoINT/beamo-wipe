"""Fake scan failures must always release the refreshing screen."""

import threading

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.wizard import REREAD_FAILED, STARTUP_UNCONFIRMED
from test_refresh_disks import authorized


def test_failed_scan_with_unwritable_diagnostic_log_finishes_refresh(monkeypatch):
    wizard = make_demo_wizard()
    wizard.skip_intro()
    assert wizard.screen == Screen.OWNER

    def failed_scan():
        raise OSError("simulated fake scan error")

    def failed_log(*_args):
        raise OSError("simulated full temporary storage")

    wizard._rediscover = failed_scan
    monkeypatch.setattr("beamo_wipe.diagnostics.log_diag", failed_log)

    assert wizard.refresh_disks()
    assert wizard.screen == Screen.PICK_BLOCKED
    assert wizard.discovery.error
    assert not wizard.discovery.boot_identified


def test_interrupted_preflight_rediscovery_revokes_expired_erase_countdown():
    wizard = authorized()
    wizard.preview = False
    wizard.dry_run = False

    def interrupted_scan():
        raise KeyboardInterrupt()

    wizard._rediscover = interrupted_scan
    wizard.confirm_erase()

    assert wizard.screen == Screen.LAST_CHANCE
    assert wizard.error == REREAD_FAILED
    assert wizard.startup_error_code == "rediscovery_failed"
    assert not wizard.erase_enabled
    assert not wizard.runner.started


def test_interrupted_preflight_validation_revokes_expired_erase_countdown(monkeypatch):
    wizard = authorized()

    def interrupted_validation(**_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        "beamo_wipe.wizard.assert_ready_to_wipe", interrupted_validation
    )
    raised = None
    try:
        wizard.confirm_erase()
    except BaseException as exc:
        raised = exc

    assert raised is None
    assert wizard.screen == Screen.LAST_CHANCE
    assert wizard.error == STARTUP_UNCONFIRMED
    assert wizard.startup_error_code == "unexpected_startup_failure"
    assert not wizard.erase_enabled
    assert not wizard.runner.started


def test_interrupted_start_worker_creation_rearms_countdown(monkeypatch):
    wizard = authorized()

    def interrupted_start(_self):
        raise KeyboardInterrupt()

    monkeypatch.setattr("beamo_wipe.wizard.threading.Thread.start", interrupted_start)
    assert not wizard.begin_erase()
    assert wizard.screen == Screen.LAST_CHANCE
    assert not wizard.erase_enabled
    assert not wizard.runner.started


def test_spawned_erase_worker_aborts_when_start_reports_interruption(monkeypatch):
    wizard = authorized()
    original_start = threading.Thread.start
    spawned = []

    def spawned_then_interrupted(worker):
        original_start(worker)
        spawned.append(worker)
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        "beamo_wipe.wizard.threading.Thread.start", spawned_then_interrupted
    )
    assert not wizard.begin_erase()
    for worker in spawned:
        worker.join(timeout=1)
        assert not worker.is_alive()

    assert wizard.screen == Screen.LAST_CHANCE
    assert not wizard.erase_enabled
    assert not wizard.runner.started
