"""Interrupted UI worker launch must resolve an already claimed fake scan."""

import threading
from tkinter import TclError

from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.models import Screen
from test_accessible_refresh_async_regression import (
    _headless_accessible_module,
    _headless_app,
)
from test_refresh_scan_flow import _stub_app


def _interrupt_start(_self):
    raise KeyboardInterrupt("fake worker launch interruption")


def test_tk_interrupted_worker_start_releases_refresh_claim(monkeypatch):
    app, calls, _main = _stub_app(lambda: discovery_for_scenario("happy"))
    try:
        app._click_refresh()
        assert app.w.screen == Screen.REFRESH_CONFIRM
        monkeypatch.setattr(threading.Thread, "start", _interrupt_start)
        try:
            app._click_refresh()
        except KeyboardInterrupt:
            pass
        assert app.w.screen == Screen.PICK_BLOCKED
        assert app.w.selectable == ()
        assert app.w.can_refresh
        assert not calls
        assert not app._refresh_threads
    finally:
        app._teardown()


def test_accessible_interrupted_worker_start_releases_refresh_claim(monkeypatch):
    module = _headless_accessible_module(monkeypatch)
    wizard = make_demo_wizard()
    wizard.skip_intro()
    assert wizard.open_refresh_confirm()
    calls = []
    wizard._rediscover = lambda: calls.append("scan") or discovery_for_scenario("happy")
    app = _headless_app(module, wizard, [])
    monkeypatch.setattr(threading.Thread, "start", _interrupt_start)
    try:
        app._begin_refresh_scan()
    except KeyboardInterrupt:
        pass
    assert wizard.screen == Screen.PICK_BLOCKED
    assert wizard.selectable == ()
    assert wizard.can_refresh
    assert not calls


def _spawn_then_interrupt(monkeypatch):
    actual_start = threading.Thread.start
    spawned = []

    def start(self):
        actual_start(self)
        spawned.append(self)
        raise KeyboardInterrupt("fake interruption after OS thread launch")

    monkeypatch.setattr(threading.Thread, "start", start)
    return spawned


def test_tk_interrupted_launch_never_runs_abandoned_scan(monkeypatch):
    app, calls, _main = _stub_app(lambda: discovery_for_scenario("happy"))
    try:
        app._click_refresh()
        spawned = _spawn_then_interrupt(monkeypatch)
        app._click_refresh()
        for thread in spawned:
            thread.join(2)
        assert app.w.screen == Screen.PICK_BLOCKED
        assert not calls
    finally:
        app._teardown()


def test_accessible_interrupted_launch_never_runs_abandoned_scan(monkeypatch):
    module = _headless_accessible_module(monkeypatch)
    wizard = make_demo_wizard()
    wizard.skip_intro()
    assert wizard.open_refresh_confirm()
    calls = []
    wizard._rediscover = lambda: calls.append("scan") or discovery_for_scenario("happy")
    app = _headless_app(module, wizard, [])
    spawned = _spawn_then_interrupt(monkeypatch)
    assert app._begin_refresh_scan()
    for thread in spawned:
        thread.join(2)
    assert wizard.screen == Screen.PICK_BLOCKED
    assert not calls


def test_tk_failed_poll_schedule_resolves_claim_before_scan(monkeypatch):
    app, calls, _main = _stub_app(lambda: discovery_for_scenario("happy"))
    try:
        app._click_refresh()

        def no_timer(_ms, _callback):
            raise TclError("fake destroyed event loop")

        monkeypatch.setattr(app.root, "after", no_timer)
        app._click_refresh()
        assert app.w.screen == Screen.PICK_BLOCKED
        assert app.w.selectable == ()
        assert not calls
    finally:
        app._teardown()


def test_tk_failed_poll_rearm_resolves_inflight_scan(monkeypatch):
    app, _calls, _main = _stub_app(lambda: discovery_for_scenario("happy"), delay=0.4)
    try:
        app._click_refresh()
        app._click_refresh()
        assert app.w.screen == Screen.REFRESHING

        def no_timer(_ms, _callback):
            raise TclError("fake timer lost while scan is running")

        monkeypatch.setattr(app.root, "after", no_timer)
        app.root.pump()
        assert app.w.screen == Screen.PICK_BLOCKED
        assert app.w.selectable == ()
        assert app.w.can_refresh
    finally:
        for worker in app._refresh_threads.values():
            worker.join(2)
        app._teardown()
