"""The TTY fallback must show its full final review after slow output."""

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


def _last_chance():
    clock = Clock()
    w = Wizard(make_demo_wizard().discovery, DryRunRunner(clock=clock),
               clock=clock, dry_run=True)
    w.skip_intro()
    w.set_owner(True)
    w.continue_owner()
    w.select_disk(w.selectable[0].path)
    w.continue_pick()
    w.set_confirm_input(w.confirm.token)
    w.continue_confirm()
    w.continue_method()
    assert w.screen == Screen.LAST_CHANCE
    return w, clock


def test_plain_tty_review_countdown_starts_after_slow_warning_output(monkeypatch, capsys):
    wizard, clock = _last_chance()

    class PromptReached(Exception):
        pass

    monkeypatch.setattr(console, "_print_view", lambda *_args, **_kwargs: clock.add(6))
    monkeypatch.setattr(console.time, "sleep", clock.add)

    def answer(_wizard, prompt):
        assert prompt == C.CON_ERASE_PROMPT
        raise PromptReached

    monkeypatch.setattr(console, "_answer", answer)
    with pytest.raises(PromptReached):
        console._plain_loop_body(wizard)
    shown = capsys.readouterr().out
    assert C.CON_COUNTDOWN.split("{")[0] in shown
    assert clock.value >= 11.0


def test_curses_first_visible_review_frame_cannot_erase_after_slow_draw(monkeypatch):
    wizard, clock = _last_chance()
    erase_attempts = []
    monkeypatch.setattr(wizard, "confirm_erase", lambda: erase_attempts.append(clock.value))

    class Terminal:
        def __init__(self):
            self.presses = 0

        def getmaxyx(self):
            return 24, 80

        def refresh(self):
            if self.presses == 0:
                clock.add(6)

        def getch(self):
            self.presses += 1
            if self.presses == 1:
                return 10  # the first Enter on the newly visible review
            wizard.wants_shutdown = True
            return -1

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    monkeypatch.setattr(console, "_footer_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_chrome_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_add", lambda *_args: None)
    monkeypatch.setattr(console, "_paint_paged", lambda *_args: 0)
    monkeypatch.setattr(console, "_paint_footer", lambda *_args: 0)
    monkeypatch.setattr(console.time, "sleep", lambda _seconds: None)
    assert console._loop(Terminal(), wizard) == 0
    assert erase_attempts == []
