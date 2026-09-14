"""User stop consent leaves polling alive. DryRunRunner / fake disks only."""
import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.ui import console_wizard
from test_busy_transitions import ready


def test_stop_requires_fresh_consent_and_keep_does_not_cancel(ready):
    w = ready
    w.confirm_erase()
    w.request_stop()
    consent = w.stop_confirmation
    assert consent is not None and w.screen == Screen.WORKING
    w.request_stop()
    assert w.stop_confirmation is consent and not w.runner.cancelled
    w.tick()
    assert w.screen == Screen.WORKING
    w.keep_erasing()
    assert not w.confirm_stop(consent) and not w.runner.cancelled
    w.request_stop()
    assert not w.confirm_stop(consent)
    assert w.confirm_stop(w.stop_confirmation, asynchronous=False)
    assert w.screen == Screen.DONE and w.runner.cancelled
    assert w.stop_confirmation is None


def test_completion_while_confirmation_open_wins(ready, monkeypatch):
    w = ready
    w.confirm_erase()
    w.request_stop()
    consent = w.stop_confirmation
    result = WipeResult(True, 0, "finished", None)
    monkeypatch.setattr(w.runner, "poll", lambda _request: result)
    w.tick()
    assert w.screen == Screen.DONE and w.wipe_result is result
    assert w.stop_confirmation is None
    assert not w.confirm_stop(consent) and not w.runner.cancelled


def test_failed_stop_never_claims_stopped(ready, monkeypatch):
    w = ready
    w.confirm_erase()
    w.request_stop()
    def failed():
        raise PermissionError("fake kill failure")
    monkeypatch.setattr(w.runner, "cancel", failed)
    w.confirm_stop(w.stop_confirmation, asynchronous=False)
    assert w.screen == Screen.WORKING and w.wipe_result is None
    assert "Stop could not be confirmed" in w.error
    assert "may still be running" in w.error
    w.request_stop()
    assert w.stop_confirmation is not None


def test_curses_repeat_escape_and_enter_never_confirm(ready):
    w = ready
    w.confirm_erase()
    for key in (27, 27, 27, 10):
        console_wizard._handle(w, key)
        assert not w.runner.cancelled
    console_wizard._handle(w, 27)
    console_wizard._handle(w, ord("s"))
    w._operation_thread.join(3)
    assert w.runner.cancelled and w.screen == Screen.DONE


@pytest.mark.parametrize("code", ["cancelled", "interrupted"])
def test_interruption_warning_is_shared(code):
    assert C.STOP_WARNING in C.VIEWS[code].announcement
    assert not C.VIEWS[code].success


def test_plain_confirmation_polls_and_repeated_cancel_does_not_stop(ready, monkeypatch, capsys):
    w = ready
    w.confirm_erase()
    commands = iter(["CANCEL\n", "CANCEL\n", "KEEP\n", "CANCEL\n", "STOP\n"])
    polls = []
    original_tick = w.tick
    def tick():
        polls.append(w.stop_confirmation)
        original_tick()
    class Input:
        def readline(self):
            return next(commands)
    monkeypatch.setattr(w, "tick", tick)
    monkeypatch.setattr("builtins.input", lambda *_: "SHUTDOWN")
    monkeypatch.setattr(console_wizard.sys, "stdin", Input())
    monkeypatch.setattr(console_wizard.select, "select", lambda *_: ([1], [], []))
    # Exercise consent through the actual controller; deterministic worker.
    original_confirm = w.confirm_stop
    monkeypatch.setattr(w, "confirm_stop", lambda consent: original_confirm(consent, asynchronous=False))
    assert console_wizard._plain_loop_body(w) == 0
    assert w.runner.cancelled and len(polls) >= 6
    output = capsys.readouterr().out
    assert C.STOP_WARNING in output
    assert "KEEP then Enter to keep erasing" in output


def test_ctrl_c_opens_confirmation_without_stopping(ready, monkeypatch):
    w = ready
    w.confirm_erase()
    calls = []
    def body(wizard):
        calls.append(True)
        if len(calls) == 1:
            raise KeyboardInterrupt
        assert wizard.stop_confirmation is not None
        assert not wizard.runner.cancelled and wizard.screen == Screen.WORKING
        return 0
    monkeypatch.setattr(console_wizard, "_plain_loop_body", body)
    assert console_wizard._plain_loop(w) == 0
