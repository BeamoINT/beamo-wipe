# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
pytest.importorskip('gi')
from beamo_wipe.models import Screen
from beamo_wipe.power import PowerStatus
from test_accessible_runtime import ui, text, drain  # noqa: F401, E402


@pytest.mark.parametrize('screen', [Screen.WHAT, Screen.LAST_CHANCE, Screen.CHECKING, Screen.WORKING, Screen.STOPPING])
def test_power_status_has_accessible_text_and_keeps_focus(ui, screen):  # noqa: F811
    app = ui()
    app.w.screen = screen
    app.w.selected = app.w.selectable[0]
    app.render()
    focused = app.window.get_focus()
    for state in (PowerStatus(ac=False, batteries=(12,), complete=True), PowerStatus()):
        app.w.power.status = state
        app.update_status()
        drain()
        assert state.text in text(app)
        assert app.power_label.get_can_focus()
        assert state.text in app.power_label.get_accessible().get_name()
        assert app.window.get_focus() is focused
