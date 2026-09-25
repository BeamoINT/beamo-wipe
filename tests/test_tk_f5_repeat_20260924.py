"""Tk shortcut auto-repeat must not advance two UI actions."""

import ast
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Optional

from beamo_wipe.models import Screen


def _handlers():
    source = Path(__file__).parents[1] / "src/beamo_wipe/ui/tk_wizard.py"
    tree = ast.parse(source.read_text())
    wizard = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TkWizard"
    )
    methods = [
        node for node in wizard.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_on_key", "_on_f5_release", "_on_escape", "_on_escape_release"}
    ]
    namespace = {"Optional": Optional, "Screen": Screen}
    exec(  # noqa: S102 - only checked-in handlers, without requiring a Tk display
        compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace


def test_x11_f5_repeat_cannot_confirm_its_own_refresh():
    handlers = _handlers()
    scans = []
    wizard = SimpleNamespace(screen=Screen.OWNER, can_refresh=True)
    app = SimpleNamespace(
        w=wizard,
        _f5_held=False,
        _f5_release_time=None,
        _key_event_time=lambda event: getattr(event, "time", None),
    )

    def click_refresh():
        if wizard.screen == Screen.REFRESH_CONFIRM:
            scans.append("scan")
        else:
            wizard.screen = Screen.REFRESH_CONFIRM

    app._click_refresh = click_refresh
    for name in ("_on_key", "_on_f5_release"):
        setattr(app, name, MethodType(handlers[name], app))

    assert app._on_key(SimpleNamespace(keysym="F5", time=100)) == "break"
    assert wizard.screen == Screen.REFRESH_CONFIRM
    app._on_f5_release(SimpleNamespace(keysym="F5", time=200))
    assert app._on_key(SimpleNamespace(keysym="F5", time=200)) == "break"
    assert scans == []

    app._on_f5_release(SimpleNamespace(keysym="F5", time=250))
    assert app._on_key(SimpleNamespace(keysym="F5", time=300)) == "break"
    assert scans == ["scan"]


def test_x11_held_escape_keeps_stop_confirmation_open():
    handlers = _handlers()
    wizard = SimpleNamespace(screen=Screen.WORKING, stop_confirmation=None)
    wizard.request_stop = lambda: setattr(wizard, "stop_confirmation", object())
    wizard.keep_erasing = lambda: setattr(wizard, "stop_confirmation", None)
    app = SimpleNamespace(
        w=wizard,
        _escape_held=False,
        _escape_release_time=None,
        _key_event_time=lambda event: getattr(event, "time", None),
        _draw=lambda: None,
    )
    app._on_escape = MethodType(handlers["_on_escape"], app)

    assert app._on_escape(SimpleNamespace(keysym="Escape", time=1000)) == "break"
    pending = wizard.stop_confirmation
    assert pending is not None
    assert app._on_escape(SimpleNamespace(keysym="Escape", time=1010)) == "break"
    assert wizard.stop_confirmation is pending

    app._on_escape_release = MethodType(handlers["_on_escape_release"], app)
    app._on_escape_release(SimpleNamespace(keysym="Escape", time=1020))
    assert app._on_escape(SimpleNamespace(keysym="Escape", time=1020)) == "break"
    assert wizard.stop_confirmation is pending

    app._on_escape_release(SimpleNamespace(keysym="Escape", time=1100))
    assert app._on_escape(SimpleNamespace(keysym="Escape", time=1200)) == "break"
    assert wizard.stop_confirmation is None
