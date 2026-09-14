# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless keyboard regressions: only fake disks and fake Tk controls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen

pytest.importorskip("tkinter")
from beamo_wipe.ui.tk_wizard import TkWizard, _Button


def _last_chance():
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    wizard._erase_until = 0.0
    assert wizard.erase_enabled
    return wizard


def _button(command, *, enabled=True):
    button = _Button.__new__(_Button)
    button._command = command
    button._enabled = enabled
    button._variant = "secondary"
    return button


def _app(wizard, focus):
    app = TkWizard.__new__(TkWizard)
    app.w = wizard
    app.root = SimpleNamespace(focus_get=lambda: focus, after_cancel=lambda *_: None)
    app._return_release_after = None
    app._return_release_time = None
    app._return_held = False
    app._draw = Mock()
    app._teardown = Mock()
    app._click_erase = Mock()
    app._primary = _button(app._click_erase)
    return app


def _live_button(command, *, enabled=True):
    """A real _Button with only its canvas surface stubbed.

    Exercises the production _press/_release/_key methods headlessly: focus
    assignment, enabled gating, and inside/outside release geometry.
    """
    button = _Button.__new__(_Button)
    button._command = command
    button._enabled = enabled
    button._variant = "secondary"
    button._pressed = False
    button._held = False
    button._hovering = False
    button._focused = False
    button._bw = 160
    button._bh = 40
    button._draw = lambda: None
    button.focus_set = Mock()
    return button


def _click(button, x=10, y=10):
    button._press()
    button._release(SimpleNamespace(x=x, y=y))


@pytest.mark.parametrize("key", ["Return", "KP_Enter"])
def test_enter_on_focused_back_never_erases(key):
    wizard = _last_chance()
    app = _app(wizard, _button(wizard.back))
    app._on_return(SimpleNamespace(keysym=key, time=100))
    assert wizard.screen == Screen.METHOD
    app._click_erase.assert_not_called()


@pytest.mark.parametrize("focus", [None, object()])
def test_last_chance_enter_without_erase_focus_never_erases(focus):
    wizard = _last_chance()
    app = _app(wizard, focus)
    app._on_return(SimpleNamespace(time=100))
    assert wizard.screen == Screen.LAST_CHANCE
    app._click_erase.assert_not_called()


def test_enter_on_focused_details_does_not_redraw_after_command():
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    assert wizard.screen == Screen.PICK
    toggle = Mock()
    focused = _button(toggle)
    focused._variant = "ghost"
    app = _app(wizard, focused)
    app._on_return(SimpleNamespace(time=100))
    toggle.assert_called_once_with()
    app._draw.assert_not_called()
    assert wizard.screen == Screen.PICK


def test_enter_on_focused_save_does_not_shutdown():
    wizard = make_demo_wizard()
    wizard.preview = False
    wizard.screen = Screen.DONE
    wizard._done_keyboard_armed = True
    save = Mock()
    app = _app(wizard, _button(save))
    app._on_return(SimpleNamespace(time=100))
    save.assert_called_once_with()
    assert not wizard.wants_shutdown


def test_enter_on_focused_back_does_not_advance_method():
    wizard = _last_chance()
    wizard.back()
    assert wizard.screen == Screen.METHOD
    app = _app(wizard, _button(wizard.back))
    app._on_return(SimpleNamespace(time=100))
    assert wizard.screen == Screen.CONFIRM
    assert wizard._erase_until is None


def test_click_disabled_erase_takes_no_focus_and_erases_nothing():
    erase = Mock()
    button = _live_button(erase, enabled=False)
    _click(button)
    button.focus_set.assert_not_called()
    erase.assert_not_called()


def test_release_outside_erase_cancels_the_click():
    erase = Mock()
    button = _live_button(erase, enabled=True)
    button._press()
    button._release(SimpleNamespace(x=500, y=500))
    erase.assert_not_called()


def test_click_back_goes_back_without_erasing():
    wizard = _last_chance()
    erase = Mock()
    back = _live_button(wizard.back, enabled=True)
    _click(back)
    assert wizard.screen == Screen.METHOD
    erase.assert_not_called()


def test_space_on_focused_erase_activates_presses_not_repeats():
    erase = Mock()
    button = _live_button(erase, enabled=True)
    app = Mock()
    app._claim_space_press.return_value = True
    button.winfo_toplevel = lambda: SimpleNamespace(_tk_wizard=app)
    button._key()
    button._key()
    assert erase.call_count == 2
    app._claim_space_press.return_value = False
    button._key()
    assert erase.call_count == 2


def test_space_on_disabled_erase_does_nothing():
    erase = Mock()
    button = _live_button(erase, enabled=False)
    button.winfo_toplevel = lambda: SimpleNamespace(_tk_wizard=None)
    button._key()
    erase.assert_not_called()


def test_focused_erase_requires_countdown_and_new_keypress():
    wizard = _last_chance()
    app = _app(wizard, None)
    app.root.focus_get = lambda: app._primary
    wizard._erase_until = wizard.now + 5
    app._primary._enabled = False
    app._on_return(SimpleNamespace(time=100))
    app._click_erase.assert_not_called()
    wizard._erase_until = 0
    app._primary._enabled = True
    app._on_return(SimpleNamespace(time=200))
    app._click_erase.assert_not_called()
    app._release_return()
    app._on_return(SimpleNamespace(time=300))
    app._click_erase.assert_called_once_with()
