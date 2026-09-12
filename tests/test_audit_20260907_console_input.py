# SPDX-License-Identifier: GPL-3.0-or-later
"""Terminal loss during fake erasure must reach interruption recovery."""

import io

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


def _working(monkeypatch, tmp_path):
    wizard = make_demo_wizard()
    wizard.preview = False
    wizard.runner._clock = lambda: 0.0
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(wizard, "_write_evidence", lambda **kwargs: None)
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    wizard._erase_until = 0.0
    wizard.confirm_erase()
    assert wizard.screen == Screen.WORKING
    return wizard


@pytest.mark.parametrize("report_wanted", [False, True])
@pytest.mark.parametrize("failure", [OSError(9, "bad descriptor"), ValueError("closed input"), PermissionError("denied")])
@pytest.mark.parametrize("stage", ["select", "readline"])
def test_unusable_working_terminal_stops_before_leaving(
    monkeypatch, tmp_path, report_wanted, failure, stage
):
    wizard = _working(monkeypatch, tmp_path)
    wizard.report_wanted = report_wanted

    class Input:
        def readline(self):
            raise failure

    terminal = Input()
    monkeypatch.setattr(console.sys, "stdin", terminal)

    def select(*args):
        if stage == "select":
            raise failure
        return [terminal], [], []

    monkeypatch.setattr(console.select, "select", select)
    monkeypatch.setattr(console.time, "sleep", lambda *_: None)
    tick = wizard.tick
    ticks = 0

    def bounded_tick():
        nonlocal ticks
        ticks += 1
        assert ticks <= 2, "Unusable terminal was swallowed while the fake erase remained active"
        tick()

    monkeypatch.setattr(wizard, "tick", bounded_tick)
    assert console._plain_loop(wizard) == (3 if report_wanted else 0)
    assert ticks == 1
    assert wizard.runner.cancelled
    assert wizard.wipe_result.summary == "interrupted"
    assert wizard.wants_shutdown is not report_wanted
    assert wizard.screen == (Screen.SHUTDOWN_CONFIRM if report_wanted else Screen.DONE)


def test_interrupted_select_retries_without_cancelling(monkeypatch, tmp_path):
    wizard = _working(monkeypatch, tmp_path)
    terminal = io.StringIO("")
    monkeypatch.setattr(console.sys, "stdin", terminal)
    calls = 0

    def select(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise InterruptedError("transient signal")
        assert not wizard.runner.cancelled
        return [terminal], [], []

    monkeypatch.setattr(console.select, "select", select)
    monkeypatch.setattr(console.time, "sleep", lambda *_: None)
    assert console._plain_loop(wizard) == 0
    assert calls == 2
    assert wizard.runner.cancelled


def test_terminal_loss_does_not_claim_unconfirmed_stop(monkeypatch, tmp_path):
    wizard = _working(monkeypatch, tmp_path)
    calls = 0

    def failed_select(*args):
        nonlocal calls
        calls += 1
        assert calls <= 2, "Unusable terminal was repeatedly polled without attempting recovery"
        raise OSError(9, "bad descriptor")

    def failed_cancel():
        raise PermissionError("cannot stop fake process")

    monkeypatch.setattr(console.select, "select", failed_select)
    monkeypatch.setattr(wizard.runner, "cancel", failed_cancel)
    assert console._plain_loop(wizard) == 3
    assert wizard.screen == Screen.WORKING
    assert wizard.wipe_result is None
    assert wizard.error
    assert not wizard.wants_shutdown
