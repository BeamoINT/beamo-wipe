# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from beamo_wipe.models import Screen
from beamo_wipe.ui.console_wizard import _plain_loop
from beamo_wipe.wizard import make_demo_wizard


def test_plain_console_zero_does_not_select_last_disk(monkeypatch):
    wiz = make_demo_wizard()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    assert wiz.selected is None
    calls = []

    def fake_input(_prompt=""):
        calls.append(1)
        if len(calls) == 1:
            return "0"
        wiz.shutdown()
        return "x"

    monkeypatch.setattr("builtins.input", fake_input)
    _plain_loop(wiz)
    assert wiz.screen == Screen.PICK
    assert wiz.selected is None


def test_curses_pick_shows_serial_and_same_size_hint():
    text = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("src/beamo_wipe/ui/console_wizard.py")
        .read_text(encoding="utf-8")
    )
    assert "disk.serial" in text
    assert "SAME_SIZE_HINT" in text
    assert "disk.path" in text
