# SPDX-License-Identifier: GPL-3.0-or-later
"""Interleaved terminal input cannot turn a held Enter into Erase."""

from unittest.mock import Mock

from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


def test_interleaved_key_does_not_rearm_enter_on_final_review(monkeypatch):
    wizard = Mock()
    wizard.screen = Screen.LAST_CHANCE
    wizard.wants_shutdown = False
    wizard.wants_new_session = False
    wizard.selected = None
    wizard.error = None
    wizard.power_text = ""
    wizard.operation_summary = ""
    wizard.method_summary = ""
    wizard.preview = False
    wizard.can_open_diagnostic = False
    wizard.can_refresh = False
    wizard.can_open_report_help = False
    wizard.begin_review_overlay.return_value = False
    wizard.prepare_text.return_value = ""
    wizard.erase_label.return_value = "fake target"
    wizard.erase_enabled = False

    turns = 0

    def tick():
        nonlocal turns
        turns += 1
        wizard.erase_enabled = turns >= 2

    wizard.tick.side_effect = tick
    events = iter((10, ord("x"), 10, -1))

    class Terminal:
        def keypad(self, *_):
            pass

        def nodelay(self, *_):
            pass

        def erase(self):
            pass

        def getmaxyx(self):
            return (24, 80)

        def refresh(self):
            pass

        def getch(self):
            ch = next(events)
            if ch == -1:
                wizard.wants_shutdown = True
            return ch

    monkeypatch.setattr(console, "_curses_opt", lambda *_: None)
    monkeypatch.setattr(console, "_footer_lines", lambda *_: [])
    monkeypatch.setattr(console, "_chrome_lines", lambda *_: [])
    monkeypatch.setattr(console, "_paint_footer", lambda *_: None)
    monkeypatch.setattr(console, "_add", lambda *_: None)
    monkeypatch.setattr(console, "_support_identity_text", lambda *_: "")
    monkeypatch.setattr(console, "_paint_paged", lambda *args: 0)
    monkeypatch.setattr(console, "_wrap", lambda *args: 0)
    console._loop(Terminal(), wizard)
    wizard.confirm_erase.assert_not_called()
