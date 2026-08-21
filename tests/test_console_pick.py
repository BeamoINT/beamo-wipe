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


def test_plain_console_garbage_method_stays_on_method(monkeypatch):
    """Invalid method input must re-prompt, not start the last-chance countdown."""
    from beamo_wipe.models import MethodId

    wiz = make_demo_wizard()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD
    screens = []

    def fake_input(_prompt=""):
        screens.append(wiz.screen)
        if len(screens) == 1:
            return "nope"
        wiz.shutdown()
        return "x"

    monkeypatch.setattr("builtins.input", fake_input)
    _plain_loop(wiz)
    assert screens
    assert all(s == Screen.METHOD for s in screens)
    assert wiz.screen == Screen.METHOD
    assert wiz.method == MethodId.EVERYDAY


def test_plain_console_eof_does_not_crash(monkeypatch):
    """Ctrl-D on the last-resort TTY must shut down, not raise EOFError."""
    wiz = make_demo_wizard()
    wiz.skip_splash()
    wiz.accept_what()

    def fake_input(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    code = _plain_loop(wiz)
    assert code == 0
    assert wiz.wants_shutdown
    assert not getattr(wiz.runner, "started", False)


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
    assert "BOOT_DISC_BANNER" in text
    assert "listed_disks" in text
    assert "wizard.progress is None" in text
    assert "no serial" in text


def test_curses_done_enter_ignored_until_idle():
    from beamo_wipe.models import WipeResult
    from beamo_wipe.ui.console_wizard import _handle

    wiz = make_demo_wizard(fail=True)
    wiz.preview = False
    wiz._finish(
        WipeResult(ok=False, exit_code=1, summary="The wipe did not finish.", logfile="")
    )
    _handle(wiz, 10)
    assert not wiz.wants_shutdown
    wiz.arm_done_keyboard()
    _handle(wiz, 10)
    assert wiz.wants_shutdown

