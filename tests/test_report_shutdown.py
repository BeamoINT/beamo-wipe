# SPDX-License-Identifier: GPL-3.0-or-later
"""Requested-report shutdown protection: fake devices and inert power actions."""

import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.report_intent import ReportIntentStore
from beamo_wipe.support_export import ExportReceipt
from beamo_wipe.ui import console_wizard as console
from test_report_intent import Terminal
from test_usb_report_workflow import _done_wizard, _success_receipt


@pytest.mark.parametrize("wanted", [False, True])
@pytest.mark.parametrize("status", ["idle", "error", "saving", "saved"])
def test_button_history_never_counts_as_an_export(tmp_path, wanted, status):
    w = _done_wizard(_success_receipt, tmp_path)
    w.report_wanted, w.report_status = wanted, status
    w.report_session = "report-0123456789abcdef01234567"
    w.shutdown()
    assert w.wants_shutdown is (not wanted)
    assert (w.screen == Screen.SHUTDOWN_CONFIRM) is wanted


@pytest.mark.parametrize(
    "screen",
    [
        s
        for s in Screen
        if s not in {Screen.WORKING, Screen.REFRESHING, Screen.SHUTDOWN_CONFIRM}
    ],
)
def test_request_cancel_and_explicit_discard_from_every_idle_screen(screen):
    w = make_demo_wizard()
    w.screen, w.report_wanted = screen, True
    w.shutdown()
    generation = w.shutdown_generation
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not w.wants_shutdown
    for _ in range(3):
        w.shutdown()
        w.accept_done_keyboard()
        w.confirm_erase()
    assert not w.wants_shutdown and not w.runner.started
    assert w.shutdown_generation == generation
    w.back()
    assert w.screen == screen and w.report_wanted
    w.confirm_shutdown_without_saving(generation)
    assert not w.wants_shutdown
    w.shutdown()
    w.confirm_shutdown_without_saving(generation)
    assert not w.wants_shutdown  # stale decision from cancelled screen
    w.confirm_shutdown_without_saving(w.shutdown_generation)
    assert w.wants_shutdown
    w.keep_report_session()
    w.shutdown()
    assert w.wants_shutdown  # power decision is idempotent


@pytest.mark.parametrize("screen", [Screen.WORKING, Screen.REFRESHING])
@pytest.mark.parametrize("wanted", [False, True])
def test_no_shutdown_during_operations(screen, wanted):
    w = make_demo_wizard()
    w.screen, w.report_wanted = screen, wanted
    w.shutdown()
    w.confirm_shutdown_without_saving(w.shutdown_generation)
    assert not w.wants_shutdown and w.screen == screen


@pytest.mark.parametrize(
    "receipt",
    [
        ExportReceipt(False, False, "export_failed"),
        ExportReceipt(True, False, "saved_verified_unmounted"),
        ExportReceipt(True, True, "partial"),
        ExportReceipt(True, True, "saved_verified_unmounted", evidence_sha256="0" * 64),
        SimpleNamespace(
            ok="true", safe_to_remove=True, code="saved_verified_unmounted"
        ),
    ],
)
def test_failed_partial_or_untrusted_receipt_stays_guarded(tmp_path, receipt):
    w = _done_wizard(lambda **kw: receipt, tmp_path)
    w.report_wanted = True
    w.save_report_to_usb()
    assert w.report_status == "error"
    w.shutdown()
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not w.wants_shutdown


def test_retry_success_and_safe_removal_allow_shutdown_without_discovery(tmp_path):
    attempts = iter([False, True])

    def exporter(**kw):
        return (
            _success_receipt(**kw)
            if next(attempts)
            else ExportReceipt(False, False, "export_failed")
        )

    w = _done_wizard(exporter, tmp_path)
    w.report_wanted = True
    w.save_report_to_usb()
    w.shutdown()
    w.keep_report_session()
    assert w.can_save_report
    w.save_report_to_usb()
    # Safe removal after the receipt does not undo the already durable export.
    w._rediscover = lambda: pytest.fail("shutdown must not inspect removed USB")
    w.shutdown()
    assert w.wants_shutdown


@pytest.mark.parametrize("changed", ["sequence", "result", "path", "discovery"])
def test_old_verified_export_does_not_cover_new_report(tmp_path, changed):
    w = _done_wizard(_success_receipt, tmp_path)
    w.report_wanted = True
    w.save_report_to_usb()
    if changed == "sequence":
        w._evidence_write_seq += 1
    elif changed == "result":
        w.wipe_result = replace(w.wipe_result, summary="new result")
    elif changed == "path":
        w.evidence_path = str(tmp_path / "new.json")
    else:
        w.discovery = replace(w.discovery, error="inventory changed")
    w.shutdown()
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not w.wants_shutdown


@pytest.mark.parametrize("success", [False, True])
def test_export_shutdown_race_requires_fresh_decision_after_completion(
    tmp_path, success
):
    entered, release = threading.Event(), threading.Event()

    def exporter(**kw):
        entered.set()
        assert release.wait(5)
        return (
            _success_receipt(**kw)
            if success
            else ExportReceipt(False, False, "export_failed")
        )

    w = _done_wizard(exporter, tmp_path)
    w.report_wanted = True
    worker = threading.Thread(target=w.save_report_to_usb)
    worker.start()
    assert entered.wait(5)
    for _ in range(20):
        w.shutdown()
        w.confirm_shutdown_without_saving(w.shutdown_generation)
        assert not w.wants_shutdown and w.screen == Screen.DONE
    release.set()
    worker.join(5)
    assert not worker.is_alive() and not w.wants_shutdown
    w.shutdown()
    assert w.wants_shutdown is success
    assert (w.screen == Screen.SHUTDOWN_CONFIRM) is (not success)


def test_pending_or_accepted_shutdown_refuses_new_export(tmp_path):
    w = _done_wizard(
        lambda **kw: pytest.fail("export after shutdown request"), tmp_path
    )
    w.report_wanted = True
    w.shutdown()
    assert not w.begin_report_export()
    w.confirm_shutdown_without_saving(w.shutdown_generation)
    assert not w.begin_report_export()


def test_local_and_privacy_reduced_copies_are_not_verified_usb_receipts(
    tmp_path, monkeypatch
):
    w = _done_wizard(_success_receipt, tmp_path)
    w.report_wanted = True
    monkeypatch.setattr(
        "beamo_wipe.evidence.export_evidence",
        lambda *a, **kw: tmp_path / "sharing-copy.json",
    )
    w.export_evidence(str(tmp_path))
    w.shutdown()
    assert w.screen == Screen.SHUTDOWN_CONFIRM


@pytest.mark.parametrize("action", ["", "SHUTDOWN", "yes", "SHUT DOWN WITHOUT SAVING"])
def test_plain_decision_requires_exact_phrase_and_can_resume(
    tmp_path, monkeypatch, capsys, action
):
    w = _done_wizard(_success_receipt, tmp_path)
    w.report_wanted = True
    answers = iter(["SHUTDOWN", action, "SAVE", "SHUTDOWN"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert console._plain_loop(w) == 0
    text = " ".join(capsys.readouterr().out.split())
    assert C.SHUTDOWN_TITLE in text and C.SHUTDOWN_LOSS in text
    assert w.wants_shutdown and w.report_wanted
    assert (w.report_status == "saved") is (action != "SHUT DOWN WITHOUT SAVING")


def test_eof_is_not_discard_confirmation_and_same_wizard_can_recover(
    tmp_path, monkeypatch, capsys
):
    w = _done_wizard(_success_receipt, tmp_path)
    w.report_wanted = True

    def eof(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert console._plain_loop(w) == 3
    assert not w.wants_shutdown and w.screen == Screen.SHUTDOWN_CONFIRM
    assert "Shutdown was not authorized" in capsys.readouterr().out
    answers = iter(["", "SAVE", "SHUTDOWN"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert console._plain_loop(w) == 0 and w.wants_shutdown


def test_ctrl_c_opens_then_cancels_decision_without_discard(tmp_path, monkeypatch):
    w = _done_wizard(_success_receipt, tmp_path)
    w.report_wanted = True
    answers = iter([KeyboardInterrupt, KeyboardInterrupt, "SAVE", "SHUTDOWN"])

    def answer(_):
        value = next(answers)
        if value is KeyboardInterrupt:
            raise KeyboardInterrupt
        return value

    monkeypatch.setattr("builtins.input", answer)
    assert console._plain_loop(w) == 0 and w.report_status == "saved"


@pytest.mark.parametrize("size", [(24, 80), (20, 60)])
def test_curses_decision_renders_loss_and_safe_default(monkeypatch, size):
    w = make_demo_wizard()
    w.screen, w.report_wanted = Screen.DONE, True
    w.shutdown()
    terminal = Terminal(w, [10], size)
    monkeypatch.setattr(console.curses, "curs_set", lambda *a: None)
    monkeypatch.setattr(console.curses, "use_default_colors", lambda *a: None)
    console._loop(terminal, w)
    page = terminal.pages[0]
    assert C.SHUTDOWN_TITLE in page
    assert C.SHUTDOWN_LOSS in page
    assert "Enter/Esc: keep session open" in page
    assert w.screen == Screen.DONE


@pytest.mark.parametrize("phrase", [b"", b"SHUTDOWN", b"SHUT DOWN WITHOUT SAVING"])
def test_curses_discard_uses_literal_confirmation(monkeypatch, phrase):
    w = make_demo_wizard()
    w.screen, w.report_wanted = Screen.DONE, True
    w.shutdown()
    terminal = Terminal(w, [], (20, 60))
    terminal.getstr = lambda *a: phrase
    for name in ["echo", "noecho", "curs_set"]:
        monkeypatch.setattr(console.curses, name, lambda *a: None)
    console._confirm_report_discard(terminal, w)
    assert w.wants_shutdown is (phrase == b"SHUT DOWN WITHOUT SAVING")


@pytest.fixture
def store(tmp_path):
    tmp_path.chmod(0o700)
    return ReportIntentStore(tmp_path)


@pytest.mark.parametrize("wanted", [False, True])
def test_process_recovery_restores_only_preference(store, wanted):
    original = make_demo_wizard()
    original.enable_report_intent_recovery(store)
    original.screen = Screen.REPORT_HELP
    original.set_report_wanted(wanted)
    recovered = make_demo_wizard()
    recovered.enable_report_intent_recovery(store)
    assert recovered.report_wanted is wanted
    assert recovered.evidence is None and not recovered.can_save_report
    assert recovered.selected is None and not recovered.owner_ok
    recovered.shutdown()
    assert recovered.wants_shutdown is (not wanted)


def test_recovery_never_restores_an_unverifiable_export_receipt(store, tmp_path):
    w = _done_wizard(_success_receipt, tmp_path)
    store.save(True)
    w.enable_report_intent_recovery(store)
    w.save_report_to_usb()
    w.shutdown()
    assert w.wants_shutdown
    recovered = make_demo_wizard()
    recovered.enable_report_intent_recovery(store)
    recovered.shutdown()
    assert not recovered.wants_shutdown
    assert (
        "Previous export success could not be confirmed"
        in recovered.report_recovery_warning
    )
    # Stored content contains no report, disk identity, or export assertion.
    assert (tmp_path / store.NAME).read_bytes() == b"wanted\n"


@pytest.mark.parametrize("content", [b"", b"true", b"wanted\nSECRET", b"x" * 100000])
def test_invalid_recovery_is_bounded_and_fails_guarded(store, tmp_path, content):
    path = tmp_path / store.NAME
    path.write_bytes(content)
    path.chmod(0o600)
    w = make_demo_wizard()
    w.enable_report_intent_recovery(store)
    w.shutdown()
    assert not w.wants_shutdown and w.report_wanted


@pytest.mark.parametrize("failure", ["write", "sync", "rename"])
def test_partial_preference_write_preserves_previous_intent(
    store, monkeypatch, tmp_path, failure
):
    import beamo_wipe.report_intent as module

    store.save(True)

    def fail(*a, **kw):
        raise OSError("injected")

    monkeypatch.setattr(
        module.os,
        {"write": "write", "sync": "fsync", "rename": "replace"}[failure],
        fail,
    )
    with pytest.raises(OSError):
        store.save(False)
    assert store.load() is True
    assert sorted(p.name for p in tmp_path.iterdir()) == [store.NAME]


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "directory", "permissions"])
def test_recovery_rejects_unsafe_paths(store, tmp_path, attack):
    path = tmp_path / store.NAME
    other = tmp_path / "private"
    other.write_bytes(b"not-wanted\n")
    other.chmod(0o600)
    if attack == "symlink":
        path.symlink_to(other)
    elif attack == "hardlink":
        path.hardlink_to(other)
    elif attack == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"not-wanted\n")
        path.chmod(0o644)
    w = make_demo_wizard()
    w.enable_report_intent_recovery(store)
    assert w.report_wanted
    assert other.read_bytes() == b"not-wanted\n"


@pytest.mark.parametrize("change", [False, True])
def test_diagnostic_receipt_only_covers_current_startup(tmp_path, monkeypatch, change):
    import hashlib
    from beamo_wipe import support_export

    w = make_demo_wizard()
    w.preview = False
    w.dry_run = False
    w.screen, w.report_wanted = Screen.PICK_BLOCKED, True
    w.open_diagnostic()
    w._diagnostic_baseline = ("fake",)

    def exporter(**kw):
        return ExportReceipt(
            True,
            True,
            "saved_verified_unmounted",
            evidence_sha256=hashlib.sha256(kw["data"]).hexdigest(),
            session_name="report-" + "a" * 24,
        )

    monkeypatch.setattr(support_export, "export_diagnostic_to_new_usb", exporter)
    w.diagnostic_action()
    assert "saved and verified" in w.diagnostic_message
    assert w.evidence is None and not w.can_save_report
    if change:
        w.startup_error_code = "identity_rejected"
    w.shutdown()
    assert w.wants_shutdown is (not change)


def test_diagnostic_failure_and_busy_state_preserve_guard(monkeypatch):
    from beamo_wipe import support_export

    w = make_demo_wizard()
    w.preview = False
    w.dry_run = False
    w.screen, w.report_wanted = Screen.PICK_BLOCKED, True
    w.open_diagnostic()
    w._diagnostic_baseline = ("fake",)

    def exporter(**kw):
        w.shutdown()
        assert not w.wants_shutdown and w.screen == Screen.DIAGNOSTIC
        return ExportReceipt(False, False, "export_failed")

    monkeypatch.setattr(support_export, "export_diagnostic_to_new_usb", exporter)
    w.diagnostic_action()
    w.shutdown()
    assert not w.wants_shutdown and w.screen == Screen.SHUTDOWN_CONFIRM


def test_intent_write_failure_visible_and_current_process_guarded(store, monkeypatch):
    w = make_demo_wizard()
    w.enable_report_intent_recovery(store)

    def fail(wanted):
        raise OSError("private detail")

    monkeypatch.setattr(store, "save", fail)
    w.screen = Screen.REPORT_HELP
    w.set_report_wanted(True)
    assert w.report_wanted and "unavailable" in w.report_recovery_warning
    assert "private detail" not in w.report_recovery_warning
    w.shutdown()
    assert not w.wants_shutdown


def test_live_graphical_failure_recovers_intent_and_power_action_is_once(
    store, monkeypatch
):
    from beamo_wipe import app, report_intent

    w = make_demo_wizard()
    w.dry_run, w.preview = False, False
    monkeypatch.setattr(app, "running_on_live_usb", lambda: True)
    monkeypatch.setattr(app, "apply_live_session_overrides", lambda args: None)
    monkeypatch.setattr(app.signal, "signal", lambda *a: None)
    monkeypatch.setattr(report_intent, "ReportIntentStore", lambda: store)
    monkeypatch.setattr(app, "_build_wizard", lambda args: w)
    power = []
    monkeypatch.setattr(app, "_shutdown", lambda: power.append(True) or True)

    def fail_gui(wizard, **kw):
        wizard.screen = Screen.REPORT_HELP
        wizard.set_report_wanted(True)
        raise RuntimeError("display lost")

    monkeypatch.setattr("beamo_wipe.ui.tk_wizard.run_tk", fail_gui)
    assert app.main([]) == 3 and not power
    recovered = make_demo_wizard()
    recovered.dry_run, recovered.preview = False, False
    monkeypatch.setattr(app, "_build_wizard", lambda args: recovered)

    def console_ui(wizard):
        assert wizard.report_wanted
        wizard.shutdown()
        wizard.shutdown()
        assert not wizard.wants_shutdown
        wizard.confirm_shutdown_without_saving(wizard.shutdown_generation)
        wizard.confirm_shutdown_without_saving(wizard.shutdown_generation)
        return 0

    monkeypatch.setattr(console, "run_console", console_ui)
    assert app.main(["--console"]) == 0
    assert power == [True]


def test_shutdown_wins_race_against_export_preparation(tmp_path, monkeypatch):
    from beamo_wipe import support_export

    w = _done_wizard(
        lambda **kw: pytest.fail("export cannot start after decision"), tmp_path
    )
    w.report_wanted = True
    prepare = support_export.prepare_terminal_evidence

    def interrupted_prepare(*a, **kw):
        result = prepare(*a, **kw)
        w.shutdown()
        return result

    monkeypatch.setattr(
        support_export, "prepare_terminal_evidence", interrupted_prepare
    )
    assert not w.begin_report_export()
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not w.wants_shutdown


def test_curses_failure_falls_back_with_pending_decision(monkeypatch):
    w = make_demo_wizard()
    w.report_wanted = True
    w.shutdown()

    def fail(*a):
        raise console.curses.error("lost terminal")

    monkeypatch.setattr(console.curses, "wrapper", fail)
    monkeypatch.setattr("builtins.input", lambda _: "SHUT DOWN WITHOUT SAVING")
    assert console.run_console(w) == 0 and w.wants_shutdown


def test_invalid_log_receipt_does_not_acknowledge_export(tmp_path):
    def bad(**kw):
        return replace(_success_receipt(**kw), log_status="unverified")

    w = _done_wizard(bad, tmp_path)
    w.report_wanted = True
    w.save_report_to_usb()
    w.shutdown()
    assert not w.wants_shutdown and w.report_status == "error"
