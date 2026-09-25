"""A held Escape leaves Confirm for Pick exactly once in the curses UI."""

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


class Terminal:
    def __init__(self, wizard, keys):
        self.wizard = wizard
        self.keys = iter(keys)

    def getmaxyx(self):
        return 24, 80

    def getch(self):
        try:
            return next(self.keys)
        except StopIteration:
            self.wizard.wants_shutdown = True
            return -1

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


@pytest.mark.parametrize(
    ("keys", "clock_values", "expected"),
    [
        ([27, 27], [], Screen.PICK),
        ([27, -1, -1, 27], [0.0, 2.0], Screen.OWNER),
    ],
)
def test_escape_on_confirm_needs_a_new_press_for_second_navigation(
    monkeypatch, keys, clock_values, expected
):
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    assert wizard.screen == Screen.CONFIRM

    monkeypatch.setattr(console, "_footer_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_chrome_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_add", lambda *_args: None)
    monkeypatch.setattr(console, "_paint_paged", lambda *_args: 0)
    monkeypatch.setattr(console, "_paint_footer", lambda *_args: 0)
    times = iter(clock_values)
    monkeypatch.setattr(console.time, "monotonic", lambda: next(times, 3.0))
    monkeypatch.setattr(console.time, "sleep", lambda _seconds: None)
    assert console._loop(Terminal(wizard, keys), wizard) == 0
    assert wizard.screen == expected
    if expected == Screen.PICK:
        assert wizard.selected is not None


@pytest.mark.parametrize(
    ("keys", "clock_values", "expected"),
    [
        ([27, 27], [], Screen.CONFIRM),
        ([27, -1, -1, 27], [0.0, 2.0], Screen.PICK),
    ],
)
def test_escape_from_method_does_not_skip_confirm_on_a_hold(
    monkeypatch, keys, clock_values, expected
):
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    assert wizard.screen == Screen.METHOD

    monkeypatch.setattr(console, "_footer_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_chrome_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_add", lambda *_args: None)
    monkeypatch.setattr(console, "_paint_paged", lambda *_args: 0)
    monkeypatch.setattr(console, "_paint_footer", lambda *_args: 0)
    times = iter(clock_values)
    monkeypatch.setattr(console.time, "monotonic", lambda: next(times, 3.0))
    monkeypatch.setattr(console.time, "sleep", lambda _seconds: None)
    assert console._loop(Terminal(wizard, keys), wizard) == 0
    assert wizard.screen == expected
