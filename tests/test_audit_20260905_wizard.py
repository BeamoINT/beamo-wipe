# SPDX-License-Identifier: GPL-3.0-or-later
"""Fake-device regressions for wizard and console failure recovery."""

import io

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


def _working_wizard(monkeypatch):
    wizard = make_demo_wizard()
    wizard.preview = False
    wizard.runner._clock = lambda: 0.0
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
@pytest.mark.parametrize("before_eof", ["", "\n", "unknown command\n"])
def test_working_plain_console_eof_cancels_before_leaving(
    monkeypatch, report_wanted, before_eof
):
    """readline EOF must reach the same interrupted recovery as input EOF."""
    wizard = _working_wizard(monkeypatch)
    wizard.report_wanted = report_wanted
    stdin = io.StringIO(before_eof)
    monkeypatch.setattr(console.sys, "stdin", stdin)
    monkeypatch.setattr(console.select, "select", lambda *args: ([stdin], [], []))
    ticks = 0
    tick = wizard.tick

    def bounded_tick():
        nonlocal ticks
        ticks += 1
        assert ticks <= 2, "EOF was ignored: console repeatedly polls an active wipe"
        tick()

    monkeypatch.setattr(wizard, "tick", bounded_tick)
    assert console._plain_loop(wizard) == (3 if report_wanted else 0)
    assert ticks == (2 if before_eof else 1)
    assert wizard.runner.cancelled
    assert wizard.wipe_result is not None
    assert wizard.wipe_result.summary == "interrupted"
    assert wizard.wants_shutdown is not report_wanted
    assert wizard.screen == (Screen.SHUTDOWN_CONFIRM if report_wanted else Screen.DONE)
