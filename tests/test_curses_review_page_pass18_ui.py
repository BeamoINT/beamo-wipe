"""A paged final review must show the warning before the erase wait runs."""

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import Wizard, make_demo_wizard


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def add(self, seconds):
        self.value += seconds


def _review_wizard():
    clock = Clock()
    wizard = Wizard(
        make_demo_wizard().discovery,
        DryRunRunner(clock=clock),
        clock=clock,
        dry_run=True,
    )
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    assert wizard.screen == Screen.LAST_CHANCE
    return wizard, clock


def test_curses_does_not_enable_erase_before_paged_warning_is_visible(monkeypatch):
    wizard, clock = _review_wizard()
    erase_attempts = []
    monkeypatch.setattr(wizard, "confirm_erase", lambda: erase_attempts.append(clock.value))
    monkeypatch.setattr(console, "_curses_opt", lambda *_args: None)
    monkeypatch.setattr(console.time, "sleep", lambda _seconds: clock.add(6))

    class Terminal:
        def __init__(self):
            self.frames = []
            self.lines = []
            self.presses = 0

        def getmaxyx(self):
            return (16, 80)

        def keypad(self, *_args):
            pass

        def nodelay(self, *_args):
            pass

        def erase(self):
            self.lines = []

        def addstr(self, y, _x, text, *_args):
            self.lines.append((y, text))

        def refresh(self):
            self.frames.append(tuple(self.lines))

        def getch(self):
            self.presses += 1
            if self.presses == 1:
                return -1  # Let the first-page countdown elapse.
            if self.presses == 2:
                return 10  # Press Enter without scrolling to the warning.
            wizard.wants_shutdown = True
            return -1

    terminal = Terminal()
    assert console._loop(terminal, wizard) == 0
    warning = C.SEVERITY_WARNING
    assert all(warning not in text for _y, text in terminal.frames[0])
    assert erase_attempts == []


def test_curses_paged_review_can_be_completed_then_waited(monkeypatch):
    wizard, clock = _review_wizard()
    erase_attempts = []
    monkeypatch.setattr(wizard, "confirm_erase", lambda: erase_attempts.append(clock.value))
    monkeypatch.setattr(console, "_curses_opt", lambda *_args: None)
    monkeypatch.setattr(console.time, "sleep", lambda _seconds: clock.add(6))

    class Terminal:
        def __init__(self):
            self.presses = 0
            self.lines = []
            self.frames = []

        def getmaxyx(self):
            return (16, 80)

        def keypad(self, *_args):
            pass

        def nodelay(self, *_args):
            pass

        def erase(self):
            self.lines = []

        def addstr(self, y, _x, text, *_args):
            self.lines.append((y, text))

        def refresh(self):
            self.frames.append(tuple(self.lines))

        def getch(self):
            self.presses += 1
            if self.presses <= 15:
                return console.curses.KEY_DOWN
            if self.presses == 16:
                assert wizard.countdown_left == 5
                return -1
            if self.presses == 17:
                return 10
            wizard.wants_shutdown = True
            return -1

    terminal = Terminal()
    assert console._loop(terminal, wizard) == 0
    assert any(C.SEVERITY_WARNING in text for frame in terminal.frames for _y, text in frame)
    assert erase_attempts == [6.0]


def test_curses_render_failure_releases_review_hold_for_tty_fallback(monkeypatch):
    wizard, _clock = _review_wizard()
    monkeypatch.setattr(console, "_curses_opt", lambda *_args: None)

    class BrokenTerminal:
        def getmaxyx(self):
            return (16, 80)

        def __getattr__(self, name):
            if name == "refresh":
                raise RuntimeError("display failed")
            return lambda *_args, **_kwargs: None

    with pytest.raises(RuntimeError, match="display failed"):
        console._run_loop_guarded(BrokenTerminal(), wizard)
    assert wizard._review_overlay_depth == 0
