"""Tk review cannot spend its first five seconds inside a slow redraw."""

from types import SimpleNamespace

from beamo_wipe.models import Screen
from beamo_wipe.ui import tk_wizard as tkui
from test_plain_review_visible_pass16_ui import _last_chance


def test_tk_first_review_draw_restarts_countdown_after_slow_layout(monkeypatch):
    wizard, clock = _last_chance()
    ui = object.__new__(tkui.TkWizard)
    ui.w = wizard
    ui._shown = Screen.METHOD
    ui._body = SimpleNamespace(configure=lambda **_kw: None)
    ui._footer = object()
    ui._pick_canvas = None
    ui._clear = lambda _frame: None
    ui._sync_layout = lambda: None
    ui._sync_chrome = lambda _splash: None
    ui._prepare_body_host = lambda: None
    ui._draw_header = lambda: None
    ui._draw_strip = lambda: None
    ui._last = lambda: clock.add(6)
    ui._refresh_last_chance = lambda: None
    monkeypatch.setattr(tkui, "emit_serial_marker", lambda _marker: None)

    ui._draw()
    assert wizard.screen == Screen.LAST_CHANCE
    assert not wizard.erase_enabled
    assert wizard.countdown_display == 5
