"""Exercise GTK key handling without requiring PyGObject on developer Macs."""

import ast
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from beamo_wipe.models import Screen


def _key_handlers():
    source = Path(__file__).parents[1] / "src/beamo_wipe/ui/accessible_wizard.py"
    tree = ast.parse(source.read_text())
    wizard = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AccessibleWizard"
    )
    methods = [
        node
        for node in wizard.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_key_press", "_key_release"}
    ]
    gdk = SimpleNamespace(
        KEY_Return=1,
        KEY_KP_Enter=2,
        KEY_space=3,
        KEY_F5=4,
        KEY_l=5,
        KEY_L=6,
        KEY_Escape=7,
    )
    copy = SimpleNamespace(BTN_ERASE="Erase now", BTN_BACK="Back")
    namespace = {"Gdk": gdk, "C": copy, "Screen": Screen}
    # Run only the two checked-in handlers so this test works without GTK on macOS.
    exec(  # noqa: S102
        compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace["_key_press"], namespace["_key_release"], gdk, copy


@pytest.mark.parametrize("enter_key", ["KEY_Return", "KEY_KP_Enter"])
def test_gtk_x11_repeat_cannot_erase_when_countdown_expires(enter_key):
    key_press, key_release, gdk, copy = _key_handlers()
    clicks = []
    button = SimpleNamespace(
        get_sensitive=lambda: button.enabled,
        clicked=lambda: clicks.append("erase"),
        enabled=False,
    )
    window = SimpleNamespace(get_focus=lambda: button)
    app = SimpleNamespace(
        w=SimpleNamespace(screen=Screen.LAST_CHANCE),
        held=set(),
        _release_times={},
        window=window,
        actions={copy.BTN_ERASE: button},
    )
    app._key_press = MethodType(key_press, app)
    app._key_release = MethodType(key_release, app)

    key = getattr(gdk, enter_key)
    assert app._key_press(window, SimpleNamespace(keyval=key, time=1000))
    app._key_release(window, SimpleNamespace(keyval=key, time=1010))
    button.enabled = True  # the review countdown reached zero while Enter stayed held
    assert app._key_press(window, SimpleNamespace(keyval=key, time=1010))
    assert clicks == []

    app._key_release(window, SimpleNamespace(keyval=key, time=1100))
    assert app._key_press(window, SimpleNamespace(keyval=key, time=1200))
    assert clicks == ["erase"]


def test_gtk_x11_repeat_cannot_skip_refresh_confirmation():
    key_press, key_release, gdk, _ = _key_handlers()
    scans = []
    wizard = SimpleNamespace(screen=Screen.OWNER, can_refresh=True)
    wizard.open_refresh_confirm = lambda: setattr(
        wizard, "screen", Screen.REFRESH_CONFIRM
    )
    app = SimpleNamespace(
        w=wizard,
        held=set(),
        _release_times={},
        render=lambda: None,
        _begin_refresh_scan=lambda: scans.append(1),
    )
    app._key_press = MethodType(key_press, app)
    app._key_release = MethodType(key_release, app)
    event = SimpleNamespace(keyval=gdk.KEY_F5, time=1000)

    assert app._key_press(None, event)
    assert wizard.screen == Screen.REFRESH_CONFIRM
    app._key_release(None, SimpleNamespace(keyval=gdk.KEY_F5, time=1010))
    assert app._key_press(None, SimpleNamespace(keyval=gdk.KEY_F5, time=1010))
    assert scans == []

    app._key_release(None, SimpleNamespace(keyval=gdk.KEY_F5, time=1100))
    assert app._key_press(None, SimpleNamespace(keyval=gdk.KEY_F5, time=1200))
    assert scans == [1]


def test_gtk_held_escape_keeps_stop_confirmation_open():
    key_press, key_release, gdk, _ = _key_handlers()
    wizard = SimpleNamespace(screen=Screen.WORKING, stop_confirmation=None)
    wizard.request_stop = lambda: setattr(wizard, "stop_confirmation", object())
    wizard.keep_erasing = lambda: setattr(wizard, "stop_confirmation", None)
    app = SimpleNamespace(
        w=wizard,
        held=set(),
        _release_times={},
        render=lambda: None,
    )
    app._key_press = MethodType(key_press, app)
    app._key_release = MethodType(key_release, app)

    assert app._key_press(None, SimpleNamespace(keyval=gdk.KEY_Escape, time=1000))
    pending = wizard.stop_confirmation
    assert pending is not None
    # Both direct repeat and split X11 release/press belong to the same hold.
    assert app._key_press(None, SimpleNamespace(keyval=gdk.KEY_Escape, time=1010))
    assert wizard.stop_confirmation is pending
    app._key_release(None, SimpleNamespace(keyval=gdk.KEY_Escape, time=1020))
    assert app._key_press(None, SimpleNamespace(keyval=gdk.KEY_Escape, time=1020))
    assert wizard.stop_confirmation is pending

    app._key_release(None, SimpleNamespace(keyval=gdk.KEY_Escape, time=1100))
    assert app._key_press(None, SimpleNamespace(keyval=gdk.KEY_Escape, time=1200))
    assert wizard.stop_confirmation is None
