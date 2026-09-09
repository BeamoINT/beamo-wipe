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
    wizard.skip_splash()
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
