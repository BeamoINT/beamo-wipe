# SPDX-License-Identifier: GPL-3.0-or-later
"""Fake-device regressions for refresh completion ownership."""

from dataclasses import replace
import threading

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen


@pytest.mark.parametrize("late_failure", [False, True])
@pytest.mark.parametrize("newer_completed", [False, True])
def test_late_duplicate_refresh_completion_cannot_overwrite_newer_scan(
    monkeypatch, late_failure, newer_completed
):
    import beamo_wipe.wizard as module

    wizard = make_demo_wizard()
    wizard.skip_intro()
    original_inventory = wizard.discovery
    newer_inventory = replace(original_inventory, excluded=())
    old_seq = wizard.begin_refresh()
    entered, release = threading.Event(), threading.Event()
    original_check = module.assert_boot_excluded
    results = []

    def check(inventory):
        if threading.current_thread().name == "late-refresh":
            entered.set()
            assert release.wait(5)
            if late_failure:
                raise module.SafetyError("fake late validation failure")
        return original_check(inventory)

    monkeypatch.setattr(module, "assert_boot_excluded", check)
    delayed = threading.Thread(
        name="late-refresh",
        target=lambda: results.append(wizard.finish_refresh(old_seq, original_inventory)),
    )
    delayed.start()
    try:
        assert entered.wait(5)
        assert wizard.finish_refresh(old_seq, original_inventory)
        new_seq = wizard.begin_refresh()
        assert new_seq != old_seq
        if newer_completed:
            assert wizard.finish_refresh(new_seq, newer_inventory)
            wizard.accept_what()
            assert wizard.screen == Screen.OWNER
        expected_inventory = wizard.discovery
    finally:
        release.set()
        delayed.join(5)
    assert not delayed.is_alive()
    assert results == [False]
    assert wizard.discovery is expected_inventory
    assert wizard.screen == (Screen.OWNER if newer_completed else Screen.REFRESHING)
    if not newer_completed:
        assert not wizard.selectable
        assert wizard.finish_refresh(new_seq, newer_inventory)
        assert wizard.discovery is newer_inventory
        assert wizard.screen == Screen.WHAT


@pytest.mark.parametrize("screen", [Screen.CHECKING, Screen.WORKING, Screen.STOPPING, Screen.WHAT])
@pytest.mark.parametrize("error_kind", [ValueError, "tcl"])
@pytest.mark.parametrize("stop_fails", [False, True])
def test_tk_unexpected_timer_failure_stops_engine_instead_of_losing_poll_loop(
    screen, error_kind, stop_fails
):
    """Tk swallows callback exceptions; the timer must retire itself safely."""
    import tkinter as tk
    from types import SimpleNamespace
    from beamo_wipe.ui.tk_wizard import TkWizard

    calls = []
    def stop():
        calls.append("stop")
        if stop_fails:
            raise RuntimeError("fake cancellation failure")

    wizard = SimpleNamespace(
        screen=screen,
        wants_shutdown=False,
        wants_new_session=False,
        tick=lambda: None,
        report_view=SimpleNamespace(revision=0),
        interface_failed=stop,
    )
    app = TkWizard.__new__(TkWizard)
    app.w = wizard
    app._shown = None
    app._shown_report_revision = 0
    app._fatal_ui = False
    app._after_id = "existing-timer"
    app.root = SimpleNamespace(
        after=lambda *args: calls.append("scheduled"),
        _report_exception=lambda: calls.append("tk-swallowed-error"),
    )
    app._teardown = lambda: calls.append("closed")

    def broken_refresh():
        error = tk.TclError if error_kind == "tcl" else error_kind
        raise error("fake render failure")

    app._arm_shutdown_enter_if_idle = lambda: None
    app._draw = broken_refresh
    # This is the same exception boundary used by real Tk callbacks; no window
    # or display is created, and no engine or device is touched.
    tk.CallWrapper(app._tick, None, app.root)()
    running = screen in {Screen.CHECKING, Screen.WORKING, Screen.STOPPING}
    assert calls == (["stop", "closed"] if running else ["closed"])
    assert app._fatal_ui
    assert app._after_id is None


def test_tk_normal_tick_keeps_status_monitor_scheduled():
    from types import SimpleNamespace
    from beamo_wipe.ui.tk_wizard import TkWizard

    calls = []
    app = TkWizard.__new__(TkWizard)
    app.w = SimpleNamespace(
        screen=Screen.WORKING,
        wants_shutdown=False,
        wants_new_session=False,
        tick=lambda: calls.append("poll"),
        report_view=SimpleNamespace(revision=0),
    )
    app._shown = Screen.WORKING
    app._shown_report_revision = 0
    app._fatal_ui = False
    app._pick_canvas = None
    app._refresh_working = lambda: calls.append("render")
    app.root = SimpleNamespace(after=lambda delay, callback: (delay, callback))
    app._tick()
    assert calls == ["poll", "render"]
    assert app._after_id == (100, app._tick)
    assert not app._fatal_ui
