"""The accessible review screen activates the focused control with Enter."""

import ast
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen


def _key_handlers():
    source = Path(__file__).parents[1] / "src/beamo_wipe/ui/accessible_wizard.py"
    tree = ast.parse(source.read_text())
    wizard = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AccessibleWizard"
    )
    methods = [
        node for node in wizard.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_key_press", "_key_release"}
    ]
    gdk = SimpleNamespace(
        KEY_Return=1, KEY_KP_Enter=2, KEY_space=3, KEY_F5=4,
        KEY_l=5, KEY_L=6, KEY_Escape=7,
    )
    namespace = {"Gdk": gdk, "C": C, "Screen": Screen}
    exec(  # noqa: S102 - exact checked-in event handlers, without GTK on macOS
        compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace["_key_press"], namespace["_key_release"], gdk


@pytest.mark.parametrize("utility", [C.KEYBOARD_UTILITY, C.BTN_REFRESH_UTILITY, C.DIAGNOSTIC_TITLE])
def test_enter_activates_focused_last_chance_utility_once(utility):
    key_press, key_release, gdk = _key_handlers()
    clicks = []
    button = SimpleNamespace(
        get_sensitive=lambda: True,
        clicked=lambda: clicks.append(utility),
    )
    window = SimpleNamespace(get_focus=lambda: button)
    app = SimpleNamespace(
        w=SimpleNamespace(screen=Screen.LAST_CHANCE),
        held=set(), _release_times={}, window=window,
        actions={C.BTN_ERASE: None, C.BTN_BACK: None, utility: button},
    )
    app._key_press = MethodType(key_press, app)
    app._key_release = MethodType(key_release, app)

    assert app._key_press(window, SimpleNamespace(keyval=gdk.KEY_Return, time=1000))
    assert clicks == [utility]
    # The same held key cannot invoke a replacement screen's action.
    assert app._key_press(window, SimpleNamespace(keyval=gdk.KEY_Return, time=1010))
    app._key_release(window, SimpleNamespace(keyval=gdk.KEY_Return, time=1020))
    assert app._key_press(window, SimpleNamespace(keyval=gdk.KEY_Return, time=1020))
    assert clicks == [utility]


def test_last_chance_enter_on_warning_cannot_start_erase():
    key_press, _key_release, gdk = _key_handlers()
    clicks = []
    erase = SimpleNamespace(get_sensitive=lambda: True, clicked=lambda: clicks.append("erase"))
    warning = object()
    window = SimpleNamespace(get_focus=lambda: warning)
    app = SimpleNamespace(
        w=SimpleNamespace(screen=Screen.LAST_CHANCE),
        held=set(), _release_times={}, window=window,
        actions={C.BTN_ERASE: erase},
    )
    app._key_press = MethodType(key_press, app)

    assert app._key_press(window, SimpleNamespace(keyval=gdk.KEY_Return, time=1000))
    assert clicks == []


@pytest.mark.parametrize("focused", [None, "stale", "disabled"])
def test_last_chance_enter_needs_a_current_enabled_control(focused):
    key_press, _key_release, gdk = _key_handlers()
    clicks = []
    disabled = SimpleNamespace(
        get_sensitive=lambda: False,
        clicked=lambda: clicks.append("disabled"),
    )
    stale = SimpleNamespace(
        get_sensitive=lambda: True,
        clicked=lambda: clicks.append("stale"),
    )
    current_focus = {None: None, "stale": stale, "disabled": disabled}[focused]
    window = SimpleNamespace(get_focus=lambda: current_focus)
    app = SimpleNamespace(
        w=SimpleNamespace(screen=Screen.LAST_CHANCE),
        held=set(), _release_times={}, window=window,
        actions={C.BTN_ERASE: None, C.BTN_BACK: disabled},
    )
    app._key_press = MethodType(key_press, app)

    assert app._key_press(window, SimpleNamespace(keyval=gdk.KEY_Return, time=1000))
    assert clicks == []
