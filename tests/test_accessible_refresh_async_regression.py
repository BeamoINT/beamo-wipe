# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessible refresh must leave the screen reader event loop responsive."""

import importlib.util
from pathlib import Path
import sys
import threading
import time
import types

from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.models import Screen


def _headless_accessible_module(monkeypatch):
    # Import the exact production class with only GI bindings stubbed. No GTK
    # rendering runs in this test and the canonical module stays untouched.
    gi = types.ModuleType("gi")
    gi.require_version = lambda *_args: None
    repository = types.ModuleType("gi.repository")
    for name in ("Atk", "Gdk", "GLib", "Gtk", "Pango"):
        setattr(repository, name, types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)
    source = (
        Path(__file__).resolve().parents[1] / "src/beamo_wipe/ui/accessible_wizard.py"
    )
    spec = importlib.util.spec_from_file_location(
        "beamo_wipe.ui.accessible_refresh_fixture", source
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _headless_app(module, wizard, draws):
    app = module.AccessibleWizard.__new__(module.AccessibleWizard)
    app.w = wizard
    app.closed = False
    app.shown = wizard.screen
    app.report_revision = -1
    app._refresh_lock = threading.Lock()
    app._refresh_result = None
    app.render = lambda: draws.append((threading.get_ident(), wizard.screen))
    return app


def test_accessible_scan_returns_to_event_loop_before_fake_discovery_finishes(
    monkeypatch,
):
    module = _headless_accessible_module(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    calls = []
    main_ident = threading.get_ident()

    def slow_discovery():
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return discovery_for_scenario("happy")

    wizard = make_demo_wizard()
    wizard._rediscover = slow_discovery
    wizard.skip_intro()
    assert wizard.open_refresh_confirm()
    app = _headless_app(module, wizard, calls)

    try:
        start = time.monotonic()
        assert app._begin_refresh_scan()
        assert time.monotonic() - start < 0.5
        assert wizard.screen == Screen.REFRESHING
        assert entered.wait(2)
        assert wizard.screen == Screen.REFRESHING
    finally:
        release.set()

    deadline = time.monotonic() + 5
    while wizard.screen == Screen.REFRESHING and time.monotonic() < deadline:
        app.tick()
        time.sleep(0.01)
    assert wizard.screen == Screen.OWNER
    assert calls[0] != main_ident
    assert all(item[0] == main_ident for item in calls[1:])


def test_accessible_scan_failure_blocks_and_allows_retry(monkeypatch):
    module = _headless_accessible_module(monkeypatch)
    wizard = make_demo_wizard()
    wizard.skip_intro()
    assert wizard.open_refresh_confirm()

    def failed_discovery():
        raise OSError("fake lsblk failure")

    wizard._rediscover = failed_discovery
    app = _headless_app(module, wizard, [])
    assert app._begin_refresh_scan()
    deadline = time.monotonic() + 5
    while wizard.screen == Screen.REFRESHING and time.monotonic() < deadline:
        app.tick()
        time.sleep(0.01)
    assert wizard.screen == Screen.PICK_BLOCKED
    assert wizard.selectable == ()
    assert wizard.can_refresh


def test_accessible_scan_refuses_duplicate_while_worker_runs(monkeypatch):
    module = _headless_accessible_module(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow_discovery():
        calls.append("scan")
        entered.set()
        assert release.wait(5)
        return discovery_for_scenario("happy")

    wizard = make_demo_wizard()
    wizard._rediscover = slow_discovery
    wizard.skip_intro()
    assert wizard.open_refresh_confirm()
    app = _headless_app(module, wizard, [])
    try:
        assert app._begin_refresh_scan()
        assert entered.wait(2)
        assert not app._begin_refresh_scan()
    finally:
        release.set()

    deadline = time.monotonic() + 5
    while wizard.screen == Screen.REFRESHING and time.monotonic() < deadline:
        app.tick()
        time.sleep(0.01)
    assert wizard.screen == Screen.OWNER
    assert calls == ["scan"]


def test_accessible_scan_worker_start_failure_resolves_claim(monkeypatch):
    module = _headless_accessible_module(monkeypatch)
    wizard = make_demo_wizard()
    wizard.skip_intro()
    assert wizard.open_refresh_confirm()
    calls = []
    wizard._rediscover = lambda: calls.append("scan") or discovery_for_scenario("happy")
    app = _headless_app(module, wizard, [])

    def no_thread(_self):
        raise RuntimeError("fake worker start failure")

    monkeypatch.setattr(threading.Thread, "start", no_thread)
    assert app._begin_refresh_scan()
    assert wizard.screen == Screen.PICK_BLOCKED
    assert wizard.selectable == ()
    assert not calls
