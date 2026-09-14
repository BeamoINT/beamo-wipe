# SPDX-License-Identifier: GPL-3.0-or-later
"""Render power changes without losing disk warnings, controls or focus."""
import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.power import PowerStatus
from test_tk_runtime import ui, _clipping_problems  # noqa: F401
from test_adaptive_layout import _assert_actions_on_window
from test_console_parity import _draw


@pytest.mark.parametrize('screen', [Screen.WHAT, Screen.LAST_CHANCE, Screen.WORKING, Screen.CHECKING, Screen.STOPPING])
@pytest.mark.parametrize('size', [(800, 600), (1024, 600), (1024, 740), (1280, 820), (1600, 1000)])
def test_native_power_remains_readable_and_updates_without_redraw(ui, screen, size):  # noqa: F811
    wizard, app = ui(size=size)
    wizard.screen = screen
    wizard.selected = wizard.selectable[0]
    wizard.power.status = PowerStatus(ac=True, batteries=(80,), complete=True)
    app._draw()
    app.root.update()
    focus = app.root.focus_get()
    generation = app._draw_generation
    for state in (PowerStatus(ac=False, batteries=(12,), complete=True), PowerStatus(), PowerStatus(complete=True)):
        wizard.power.status = state
        app._tick()
        app.root.update()
        assert state.text in str(app._power_label.cget('text'))
        assert app.root.focus_get() is focus
        assert app._draw_generation == generation
        assert _clipping_problems(app) == []
        if screen not in {Screen.CHECKING, Screen.STOPPING}:
            _assert_actions_on_window(app)
        else:
            assert app._primary is None  # busy states deliberately have no action
    assert wizard.screen == screen


@pytest.mark.parametrize('screen', [Screen.WHAT, Screen.LAST_CHANCE, Screen.WORKING, Screen.CHECKING, Screen.STOPPING])
def test_console_pages_power_without_dropping_disk_identity(monkeypatch, screen):
    import curses
    wizard = make_demo_wizard()
    wizard.screen = screen
    wizard.selected = wizard.selectable[0]
    wizard.power.status = PowerStatus(ac=False, batteries=(12,), complete=True)
    _, _, terminal = _draw(monkeypatch, wizard, keys=[curses.KEY_NPAGE] * 8)
    shown = ' '.join(' '.join(frame.values()) for frame in terminal.frames)
    assert '12%' in shown
    assert 'Low battery' in shown
    assert 'lid open' in shown
    if screen != Screen.WHAT:
        assert wizard.selected.serial in shown


def test_preview_and_helper_guidance_match():
    from beamo_wipe.gallery import gallery_html, project_root
    html = gallery_html()
    assert C.POWER_KEEP in html
    assert C.POWER_EVENTS in html
    assert 'Fake power' in html and 'aria-live="polite"' in html
    helper = (project_root() / 'helper/index.html').read_text()
    assert 'Keep the lid open' in helper
    assert 'cannot read battery or wall-power status' in helper
