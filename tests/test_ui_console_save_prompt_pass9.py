"""Report-save confirmation must remain usable on a narrow terminal."""

from types import SimpleNamespace

from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


def test_report_save_input_stays_inside_twenty_column_terminal(monkeypatch):
    calls = []

    class Terminal:
        def getmaxyx(self):
            return 24, 20

        def refresh(self):
            pass

        def nodelay(self, _enabled):
            pass

        def getstr(self, row, col, limit):
            assert 0 <= row < 24
            assert 0 <= col < 20
            assert limit >= len("SAVE")
            return b"SAVE"

    wizard = SimpleNamespace(save_report_to_usb=lambda: calls.append("save"))
    monkeypatch.setattr(console, "_add", lambda *_args: None)
    console._confirm_report_save(Terminal(), wizard)
    assert calls == ["save"]


def test_idle_inventory_overlay_yields_between_paints(monkeypatch):
    """The nonblocking input loop must not spin while help is open."""
    wizard = SimpleNamespace(
        screen=Screen.PICK,
        wants_shutdown=False,
        wants_new_session=False,
        can_open_diagnostic=False,
        can_refresh=False,
        can_open_keyboard=False,
        can_open_report_help=False,
        selectable=[],
        listed_disks=[],
        other_devices=[object()],
        report_wanted=False,
        protected_boot=None,
        error="",
        inventory_count="",
        selected=None,
        tick=lambda: None,
    )

    class Terminal:
        def __init__(self):
            self.keys = iter([ord("o"), -1, -1, 27])

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

    sleeps = []
    monkeypatch.setattr(console, "_footer_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_chrome_lines", lambda *_args: [])
    monkeypatch.setattr(console, "_add", lambda *_args: None)
    monkeypatch.setattr(console, "_paint_footer", lambda *_args: None)
    monkeypatch.setattr(console, "_pick_blocks", lambda *_args: [])
    monkeypatch.setattr(console.inventory, "full_text", lambda *_args: "details")
    monkeypatch.setattr(console.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert console._loop(Terminal(), wizard) == 0
    assert len(sleeps) >= 2
