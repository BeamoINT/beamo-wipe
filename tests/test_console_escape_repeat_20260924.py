"""A held Escape in curses must not dismiss its own Stop confirmation."""

from types import SimpleNamespace

import pytest

from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


@pytest.mark.parametrize(
    ("keys", "clock_values", "confirmation_open"),
    [
        ([27, 27], [], True),
        ([27, -1, -1, 27], [0, 0, 2, 2], False),
    ],
)
def test_curses_escape_requires_quiet_before_second_action(
    monkeypatch, keys, clock_values, confirmation_open
):
    wizard = SimpleNamespace(
        screen=Screen.WORKING,
        stop_confirmation=None,
        wants_shutdown=False,
        wants_new_session=False,
        can_open_diagnostic=False,
        can_open_keyboard=False,
        can_open_report_help=False,
        can_refresh=False,
        error="",
        progress_view=SimpleNamespace(status_text="Working"),
        operation_disk=None,
        operation_identity_text="",
        operation_method_text="",
        evidence_warning="",
        power_text="",
        tick=lambda: None,
    )
    wizard.request_stop = lambda: setattr(wizard, "stop_confirmation", object())
    wizard.keep_erasing = lambda: setattr(wizard, "stop_confirmation", None)

    class Terminal:
        def __init__(self):
            self.keys = iter(keys)

        def getmaxyx(self):
            return 24, 80

        def getch(self):
            try:
                return next(self.keys)
            except StopIteration:
                wizard.wants_shutdown = True
                return -1

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    monkeypatch.setattr(console, "_footer_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_chrome_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_add", lambda *_args: None)
    monkeypatch.setattr(console, "_paint_paged", lambda *_args: 0)
    monkeypatch.setattr(console, "_paint_footer", lambda *_args: 0)
    times = iter(clock_values)
    monkeypatch.setattr(console.time, "monotonic", lambda: next(times, 4))
    monkeypatch.setattr(console.time, "sleep", lambda _seconds: None)
    assert console._loop(Terminal(), wizard) == 0
    assert (wizard.stop_confirmation is not None) is confirmation_open
