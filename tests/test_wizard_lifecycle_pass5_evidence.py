"""Fake evidence interruptions must leave a usable terminal state."""

import threading

from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.demo import make_demo_wizard
from test_evidence_retry import complete, start
from test_refresh_disks import authorized
from test_usb_report_workflow import _done_wizard, _success_receipt


def test_interrupted_terminal_evidence_write_reports_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = authorized()
    wizard.confirm_erase()
    assert wizard.screen == Screen.WORKING

    def interrupted_build(**_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("beamo_wipe.evidence.build_evidence", interrupted_build)
    raised = None
    try:
        wizard._finish(
            WipeResult(False, 1, "fake failure", str(tmp_path / "nwipe.log"))
        )
    except BaseException as exc:
        raised = exc

    assert raised is None
    assert wizard.screen == Screen.DONE
    assert wizard.evidence_status == "failed"
    assert wizard.evidence_error
    assert not wizard._evidence_saving
    assert not wizard._finishing


def test_interrupted_retry_worker_start_releases_saving_state(tmp_path, monkeypatch):
    def failed_write(*_args, **_kwargs):
        raise OSError("fake evidence storage failure")

    monkeypatch.setattr("beamo_wipe.evidence.write_evidence_atomic", failed_write)
    wizard, clock = start(tmp_path, monkeypatch)
    complete(wizard, clock, "failed")
    assert wizard.can_retry_evidence

    def interrupted_start(_self):
        raise KeyboardInterrupt()

    monkeypatch.setattr("beamo_wipe.wizard.threading.Thread.start", interrupted_start)
    raised = None
    try:
        started = wizard.begin_evidence_retry()
    except BaseException as exc:
        raised = exc
        started = None

    assert raised is None
    assert started is False
    assert wizard.evidence_status == "failed"
    assert not wizard._evidence_saving
    assert wizard.evidence_error


def test_interrupted_report_worker_start_releases_export_claim(tmp_path, monkeypatch):
    wizard = _done_wizard(_success_receipt, tmp_path)
    assert wizard.can_save_report

    def interrupted_start(_self):
        raise KeyboardInterrupt()

    monkeypatch.setattr("beamo_wipe.wizard.threading.Thread.start", interrupted_start)
    raised = None
    try:
        started = wizard.begin_report_export()
    except BaseException as exc:
        raised = exc
        started = None

    assert raised is None
    assert started is False
    assert not wizard._report_exporting
    assert wizard._active_report_claim is None
    assert wizard.report_status == "error"


def test_spawned_report_worker_aborts_before_external_export(tmp_path, monkeypatch):
    exports = []

    def exporter(**_kwargs):
        exports.append(True)
        return _success_receipt(**_kwargs)

    wizard = _done_wizard(exporter, tmp_path)
    original_start = threading.Thread.start
    spawned = []

    def spawned_then_interrupted(worker):
        original_start(worker)
        spawned.append(worker)
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        "beamo_wipe.wizard.threading.Thread.start", spawned_then_interrupted
    )
    assert not wizard.begin_report_export()
    for worker in spawned:
        worker.join(timeout=1)
        assert not worker.is_alive()

    assert exports == []
    assert not wizard._report_exporting
    assert wizard._active_report_claim is None
    assert wizard.report_status == "error"


def test_interrupted_diagnostic_worker_start_releases_busy_state(monkeypatch):
    wizard = make_demo_wizard(scenario="blocked")
    wizard.preview = False
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    assert wizard.screen == Screen.PICK_BLOCKED
    wizard.open_diagnostic()
    assert wizard.screen == Screen.DIAGNOSTIC

    def interrupted_start(_self):
        raise KeyboardInterrupt()

    monkeypatch.setattr("beamo_wipe.wizard.threading.Thread.start", interrupted_start)
    raised = None
    try:
        started = wizard.diagnostic_action(background=True)
    except BaseException as exc:
        raised = exc
        started = None

    assert raised is None
    assert started is False
    assert not wizard._diagnostic_busy
    assert wizard.diagnostic_message
