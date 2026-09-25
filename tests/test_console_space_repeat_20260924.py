"""Held toggle keys must not repeatedly change console report preferences."""

from types import SimpleNamespace

import pytest

from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


@pytest.mark.parametrize(
    ("field", "keys", "clock_values", "expected"),
    [
        ("report_wanted", [ord(" "), ord(" ")], [], [False]),
        ("report_wanted", [ord(" "), -1, -1, ord(" ")],
         [0, 0, 0, 0, 2, 2, 2, 2], [False, True]),
        ("report_share_redacted", [ord("s"), ord("s")], [], [True]),
        ("report_share_redacted", [ord("s"), -1, -1, ord("s")],
         [0, 0, 0, 0, 2, 2, 2, 2], [True, False]),
    ],
)
def test_console_report_preference_changes_once_per_physical_press(
    monkeypatch, field, keys, clock_values, expected
):
    calls = []
    wizard = SimpleNamespace(
        screen=Screen.REPORT_HELP,
        wants_shutdown=False,
        wants_new_session=False,
        can_open_keyboard=False,
        can_open_report_help=False,
        can_open_diagnostic=False,
        can_refresh=False,
        report_wanted=True,
        report_share_redacted=False,
        report_recovery_warning="",
        tick=lambda: None,
    )

    def set_report_wanted(value):
        if field == "report_wanted":
            calls.append(value)
        wizard.report_wanted = value

    wizard.set_report_wanted = set_report_wanted

    def set_report_share_redacted(value):
        if field == "report_share_redacted":
            calls.append(value)
        wizard.report_share_redacted = value

    wizard.set_report_share_redacted = set_report_share_redacted

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
    monkeypatch.setattr(console, "_paint_footer", lambda *_args: None)
    times = iter(clock_values)
    monkeypatch.setattr(console.time, "monotonic", lambda: next(times, 3))
    monkeypatch.setattr(console.time, "sleep", lambda _seconds: None)

    assert console._loop(Terminal(), wizard) == 0
    assert calls == expected
    assert getattr(wizard, field) is expected[-1]
