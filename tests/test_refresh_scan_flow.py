# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #52: threaded scan orchestration without a display.

A minimal event-loop stub drives the REAL ``TkWizard`` scan methods
(``_click_refresh`` / ``_click_accessible`` / worker / poll / teardown):
real threads, real timing, real ``begin/finish`` sequencing — only ``root``
and ``_draw`` are stand-ins. Rendering itself stays with the display-gated
runtime tests. ``_draw`` records the calling thread, so any Tk work leaking
onto a worker fails loudly here.
"""

import threading
import time
from tkinter import TclError

from beamo_wipe.copy import REDISCOVER_ERROR
from beamo_wipe.demo import DEMO_DURATION_S, discovery_for_scenario
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.ui.tk_wizard import TkWizard
from beamo_wipe.wizard import Wizard


class _FakeRoot:
    """after/update/destroy without a window server."""

    def __init__(self):
        self.scheduled = []
        self.destroyed = False

    def after(self, _ms, fn):
        if self.destroyed:
            raise TclError("application has been destroyed")
        self.scheduled.append(fn)
        return len(self.scheduled)

    def after_cancel(self, _callback):
        return None

    def pump(self):
        pending, self.scheduled = self.scheduled, []
        for fn in pending:
            fn()

    def destroy(self):
        self.destroyed = True


def _stub_app(rediscover, delay=0.0, fail=False):
    calls = []

    def slow():
        calls.append(threading.get_ident())
        if delay:
            time.sleep(delay)
        if fail:
            raise RuntimeError("scan blew up")
        return rediscover()

    wiz = Wizard(
        discovery_for_scenario("happy"),
        DryRunRunner(duration_s=DEMO_DURATION_S),
        dry_run=True,
        rediscover=slow,
    )
    wiz.preview = True
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    app = TkWizard.__new__(TkWizard)
    app.w = wiz
    app.root = _FakeRoot()
    app._show_more = False
    app._pick_scroll = 0.0
    app._refresh_lock = threading.Lock()
    app._refresh_results = {}
    app._refresh_threads = {}
    app._ui_dead = False
    app._pick_canvas = None
    app._pick_after_ids = []
    app._pick_restore_pending = False
    app._return_release_after = None
    app._space_release_after = None
    app._after_id = None
    app._accessible_requested = False
    app.draws = []
    main_ident = threading.get_ident()

    def fake_draw():
        app.draws.append((threading.get_ident(), wiz.screen))

    app._draw = fake_draw
    return app, calls, main_ident


def _settle(app, timeout=15.0):
    deadline = time.monotonic() + timeout
    while app.w.screen == Screen.REFRESHING and time.monotonic() < deadline:
        app.root.pump()
        time.sleep(0.02)
    return app.w.screen


def test_scan_returns_fast_and_loop_beats_during_io():
    app, calls, main_ident = _stub_app(
        lambda: discovery_for_scenario("happy"), delay=1.0
    )
    beats = []

    def beat():
        beats.append(time.monotonic())
        if app.w.screen == Screen.REFRESHING:
            app.root.after(100, beat)

    try:
        app.root.after(100, beat)
        start = time.monotonic()
        app._click_refresh()
        assert time.monotonic() - start < 0.5
        assert app.w.screen == Screen.REFRESHING
        assert _settle(app) == Screen.WHAT
        assert len(beats) >= 3, f"loop stalled ({len(beats)} beats)"
        assert calls and calls[0] != main_ident
        assert app.draws[0][1] == Screen.REFRESHING  # checking painted first
        assert app.draws[-1][1] == Screen.WHAT
        assert all(ident == main_ident for ident, _screen in app.draws)
    finally:
        app._teardown()


def test_scan_failure_blocks_closed_without_escape():
    app, _calls, _main = _stub_app(
        lambda: discovery_for_scenario("happy"), delay=0.2, fail=True
    )
    try:
        app._click_refresh()
        assert _settle(app) == Screen.PICK_BLOCKED
        assert app.w.error == REDISCOVER_ERROR
        assert app.w.selectable == ()
        assert app.draws[-1][1] == Screen.PICK_BLOCKED
    finally:
        app._teardown()


def test_duplicate_scan_refused_single_worker():
    app, _calls, _main = _stub_app(lambda: discovery_for_scenario("happy"), delay=0.5)
    try:
        app._click_refresh()
        time.sleep(0.1)
        app.root.pump()
        app._click_refresh()
        assert _settle(app) == Screen.WHAT
        for worker in app._refresh_threads.values():
            worker.join(timeout=10)
        # The refused repeat drew nothing and started no worker: one
        # checking paint, one applied paint, one thread total.
        assert [screen for _ident, screen in app.draws] == [
            Screen.REFRESHING,
            Screen.WHAT,
        ]
        assert len(app._refresh_threads) == 1
    finally:
        app._teardown()


def test_close_mid_scan_drops_worker_result():
    app, _calls, _main = _stub_app(lambda: discovery_for_scenario("happy"), delay=1.0)
    try:
        app._click_refresh()
        app.root.pump()
        app._teardown()
        assert app._ui_dead
        for worker in app._refresh_threads.values():
            worker.join(timeout=10)
            assert not worker.is_alive()
        app.root.pump()
        assert [screen for _ident, screen in app.draws] == [Screen.REFRESHING]
    finally:
        app._teardown()
