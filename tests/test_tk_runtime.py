# SPDX-License-Identifier: GPL-3.0-or-later
"""Runtime tests for the real Tk wizard on fake disks.

Nothing is erased: every test uses the demo wizard (DryRunRunner). These
tests need a display; on a headless host they skip. They exist to catch
layout regressions (clipped text, buttons pushed off the window at the
minimum size) and broken keyboard flows that source inspection cannot see.
"""

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_result_presentations import CASES as RESULT_CASES, case_evidence

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.methods import METHODS
try:
    import tkinter as tk
    from beamo_wipe.ui.tk_wizard import TkWizard, _Button, _CheckRow
except ImportError:
    pytest.skip("tkinter not available", allow_module_level=True)

try:
    import tkinter as _tk_probe  # noqa: F401
    _HAS_TK_DISPLAY = True
except Exception:  # pragma: no cover
    _HAS_TK_DISPLAY = False


def _needs_display():
    import os as _os
    import sys as _sys
    if not _HAS_TK_DISPLAY:
        pytest.skip("tkinter not available")
    # macOS without DISPLAY aborts the process on Tk() — skip without calling it
    if _sys.platform == "darwin" and not _os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY on macOS — Tk would abort")
    try:
        import tkinter as _tk
        root = _tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no display: {exc}")

WINDOW = (1280, 820)
MIN_WINDOW = (1024, 740)  # Comfortable tall layout; minsize is 800x600
SHORT_WINDOW = (1280, 720)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@pytest.fixture
def ui():
    created = []

    def build(scenario="happy", fail=False, size=WINDOW):
        _needs_display()
        wiz = make_demo_wizard(fail=fail, scenario=scenario)
        app = TkWizard(wiz)
        app.root.geometry(f"{size[0]}x{size[1]}+40+40")
        app.root.update_idletasks()
        # The live USB kiosk runs the wizard as the only window; it always
        # holds the focus. Simulate that so key events dispatch.
        app.root.focus_force()
        created.append(app)
        return wiz, app

    yield build
    for app in created:
        app._teardown()


def _in_canvas(widget) -> bool:
    node = widget.master
    while node is not None:
        if isinstance(node, tk.Canvas):
            return True
        node = node.master
    return False


def test_fullscreen_kiosk_has_fixed_display_geometry_without_window_manager():
    """The live startx session has no window manager to honor fullscreen hints."""
    import os
    import sys

    if sys.platform != "linux" or os.environ.get("BEAMO_ISOLATED_X11_TEST") != "1":
        pytest.skip("bare X11 fullscreen check requires an isolated X server")
    _needs_display()
    wiz = make_demo_wizard()
    wiz.preview = False
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    app = TkWizard(wiz, fullscreen=True)
    try:
        generation = []
        app.root.after(1000, lambda: generation.append(app._draw_generation))
        app.root.after(1500, app.root.quit)
        app.root.mainloop()
        assert (app.root.winfo_width(), app.root.winfo_height()) == (
            app.root.winfo_screenwidth(), app.root.winfo_screenheight(),
        )
        assert generation and app._draw_generation == generation[0], "idle picker keeps rebuilding"
        app.root.focus_force()
        app._return_held = True
        app._on_return_release(SimpleNamespace(time=100))
        app.root.update()
        assert not app._return_held
    finally:
        app._teardown()


def _layout_snippet(text) -> str:
    return str(text).replace("\n", "\\n")[:56]


def _clipping_problems(app) -> list:
    """Labels/entries asking for more space than the layout gave them.

    Device cards, warning panels, and progress live in Canvas windows.
    Skipping those hosts used to hide the 1,485 px serial clip
    (``docs/evidence/ux-review-20260908-native.jsonl`` ``long_identifiers``).
    Diagnostics keep requested vs allocated pixels so a failure names the
    overflow instead of only the widget class.
    """
    app.root.update_idletasks()
    problems = []

    def visit(w):
        try:
            if not w.winfo_ismapped():
                return
        except tk.TclError:
            return
        cls = w.winfo_class()
        if cls in ("Label", "Entry"):
            try:
                text = w.get() if cls == "Entry" else w.cget("text")
            except tk.TclError:
                text = ""
            req_w, act_w = w.winfo_reqwidth(), w.winfo_width()
            req_h, act_h = w.winfo_reqheight(), w.winfo_height()
            if req_w > act_w + 2:
                problems.append(
                    f"h-clip {cls} req={req_w} actual={act_w} {_layout_snippet(text)!r}"
                )
            if req_h > act_h + 2:
                problems.append(
                    f"v-clip {cls} req={req_h} actual={act_h} {_layout_snippet(text)!r}"
                )
        if isinstance(w, tk.Canvas):
            try:
                cw, ch = w.winfo_width(), w.winfo_height()
                for item in w.find_all():
                    if w.type(item) != "text":
                        continue
                    bbox = w.bbox(item)
                    if not bbox:
                        continue
                    x0, y0, x1, y1 = bbox
                    if x0 < -2 or y0 < -2 or x1 > cw + 2 or y1 > ch + 2:
                        text = w.itemcget(item, "text")
                        problems.append(
                            "canvas-text overflow "
                            f"bbox=({x0},{y0},{x1},{y1}) canvas={cw}x{ch} "
                            f"{_layout_snippet(text)!r}"
                        )
            except tk.TclError:
                pass
        for child in w.winfo_children():
            visit(child)

    visit(app.root)
    return problems


def _off_window_problems(app) -> list:
    """Any mapped widget (outside the scrolling pick list) off the window."""
    app.root.update_idletasks()
    ww = app.root.winfo_width()
    wh = app.root.winfo_height()
    problems = []

    def visit(w):
        try:
            if not w.winfo_ismapped():
                return
            x = w.winfo_rootx() - app.root.winfo_rootx()
            y = w.winfo_rooty() - app.root.winfo_rooty()
        except tk.TclError:
            return
        if not _in_canvas(w):
            if x < -2 or y < -2 or x + w.winfo_width() > ww + 2 or y + w.winfo_height() > wh + 2:
                problems.append(f"off-window {w.winfo_class()} at ({x},{y})")
        for child in w.winfo_children():
            visit(child)

    visit(app.root)
    return problems


def _button_named(app, text):
    found = []

    def visit(widget):
        if isinstance(widget, _Button) and widget.itemcget(widget._label, "text") == text:
            found.append(widget)
        for child in widget.winfo_children():
            visit(child)

    visit(app.root)
    assert len(found) == 1
    return found[0]


def _drive_to(wiz, app, screen, size=WINDOW):
    """Walk the real wizard state machine to a screen, then redraw."""
    if wiz.screen == Screen.SPLASH and screen != Screen.SPLASH:
        if screen == Screen.KEYBOARD:
            wiz.skip_splash()
        else:
            wiz.skip_intro()
    if screen in (
        Screen.OWNER, Screen.PICK, Screen.CONFIRM, Screen.METHOD,
        Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE, Screen.ADVANCED,
    ):
        wiz.accept_what()
    if screen != Screen.OWNER:
        wiz.set_owner(True)
        wiz.continue_owner()
    if screen in (Screen.PICK, Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE,
                  Screen.WORKING, Screen.DONE, Screen.ADVANCED):
        if wiz.screen == Screen.PICK:
            disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
            wiz.select_disk(disk.path)
    if screen in (Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE,
                  Screen.WORKING, Screen.DONE, Screen.ADVANCED):
        wiz.continue_pick()
        spec = wiz.confirm
        wiz.set_confirm_input(spec.token)
        app._confirm_var.set(spec.token)
    if screen in (Screen.METHOD, Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE,
                  Screen.ADVANCED):
        wiz.continue_confirm()
    if screen == Screen.ADVANCED:
        wiz.open_advanced()
    if screen in (Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE):
        wiz.continue_method()
    app._draw()
    app.root.update_idletasks()
    app.root.update()


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW, SHORT_WINDOW, (800, 600)])
@pytest.mark.parametrize(
    "screen",
    [Screen.KEYBOARD, Screen.WHAT, Screen.OWNER, Screen.PICK, Screen.CONFIRM, Screen.METHOD,
     Screen.ADVANCED, Screen.LAST_CHANCE],
)
def test_screen_fits_without_clipping(ui, screen, size):
    wiz, app = ui(size=size)
    _drive_to(wiz, app, screen, size=size)
    assert app.w.screen == screen
    assert _clipping_problems(app) == []
    assert _off_window_problems(app) == []


def _long_identity_app(size):
    """Real wizard whose disks carry maximum-shape identity (backlog #51)."""
    from beamo_wipe.demo import DEMO_DURATION_S
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard
    from test_identity_soft_break import long_identity_discovery

    _needs_display()
    discovery = long_identity_discovery()
    wiz = Wizard(
        discovery,
        DryRunRunner(duration_s=DEMO_DURATION_S),
        dry_run=True,
        rediscover=lambda: discovery,
    )
    wiz.preview = True
    app = TkWizard(wiz)
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app.root.update_idletasks()
    app.root.focus_force()
    return wiz, app


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize(
    "screen", [Screen.PICK, Screen.CONFIRM, Screen.LAST_CHANCE]
)
def _slow_scan_app(size, delay=2.0, fail=False, mark=None):
    """Tk app whose rediscovery sleeps, proving the loop stays live. (Backlog #52.)"""
    from beamo_wipe.demo import DEMO_DURATION_S, discovery_for_scenario
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard

    _needs_display()
    calls = []

    def slow():
        calls.append((threading.get_ident(), time.monotonic()))
        time.sleep(delay)
        if fail:
            raise RuntimeError("scan blew up")
        if mark is not None:
            mark.append(len(calls))
            base = discovery_for_scenario("happy")
            first = base.selectable[0]
            altered = replace(first, serial=f"SLOWSCAN{len(calls):02d}")
            disks = tuple(altered if d.path == first.path else d for d in base.disks)
            selectable = tuple(
                altered if d.path == first.path else d for d in base.selectable
            )
            return replace(base, disks=disks, selectable=selectable)
        return discovery_for_scenario("happy")

    discovery = discovery_for_scenario("happy")
    wiz = Wizard(
        discovery,
        DryRunRunner(duration_s=DEMO_DURATION_S),
        dry_run=True,
        rediscover=slow,
    )
    wiz.preview = True
    app = TkWizard(wiz)
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app.root.update_idletasks()
    app.root.focus_force()
    return wiz, app, calls


def _await_scan_done(app, timeout=15.0):
    deadline = time.monotonic() + timeout
    while app.w.screen == Screen.REFRESHING and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    return app.w.screen


def _join_scan_workers(app, timeout=15.0):
    for worker in list(app._refresh_threads.values()):
        worker.join(timeout=max(0.1, timeout / max(1, len(app._refresh_threads))))


def test_refresh_returns_while_scan_runs():
    """Slow scan: F5 returns fast, checking paints, heartbeats keep firing."""
    wiz, app, calls = _slow_scan_app(WINDOW)
    try:
        _drive_to(wiz, app, Screen.PICK)
        beats = []

        def beat():
            beats.append(time.monotonic())
            if wiz.screen == Screen.REFRESHING:
                app.root.after(100, beat)

        app.root.after(100, beat)
        main_ident = threading.get_ident()
        app._click_refresh()
        assert wiz.screen == Screen.REFRESH_CONFIRM
        start = time.monotonic()
        app._click_refresh()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"UI thread blocked {elapsed:.2f}s by discovery I/O"
        assert wiz.screen == Screen.REFRESHING
        assert _await_scan_done(app) == Screen.WHAT
        assert len(beats) >= 5, f"event loop stalled during scan ({len(beats)} beats)"
        assert calls and all(ident != main_ident for ident, _ in calls)
    finally:
        app._teardown()


def test_refresh_failure_blocks_closed():
    """Exploding scan: fail-closed blocked screen, app stays alive."""
    from beamo_wipe.copy import REDISCOVER_ERROR

    wiz, app, calls = _slow_scan_app(WINDOW, delay=0.5, fail=True)
    try:
        _drive_to(wiz, app, Screen.PICK)
        app._click_refresh()
        app._click_refresh()
        assert _await_scan_done(app) == Screen.PICK_BLOCKED
        assert wiz.error == REDISCOVER_ERROR
        assert wiz.selectable == ()
        assert app.root.winfo_exists()
    finally:
        app._teardown()


def test_duplicate_refresh_runs_single_scan():
    """Double F5: the repeat is refused; one scan applies, nothing piles up."""
    marks = []
    wiz, app, calls = _slow_scan_app(WINDOW, delay=1.0, mark=marks)
    applied = []
    real_finish = wiz.finish_refresh

    def counting_finish(seq, outcome):
        result = real_finish(seq, outcome)
        applied.append(result)
        return result

    try:
        _drive_to(wiz, app, Screen.PICK)
        wiz.finish_refresh = counting_finish
        app._click_refresh()
        app._click_refresh()
        time.sleep(0.3)
        app.root.update()
        app._click_refresh()
        assert _await_scan_done(app) == Screen.WHAT
        _join_scan_workers(app)
        assert marks == [1], marks  # second attempt never started I/O
        assert applied == [True], applied
        serials = [d.serial for d in wiz.selectable]
        assert "SLOWSCAN01" in serials, serials
        assert wiz.selected is None
    finally:
        app._teardown()


def test_close_during_scan_drops_silently():
    """Window close mid-scan: clean teardown, joinable workers, no late draw."""
    wiz, app, calls = _slow_scan_app(WINDOW, delay=2.0)
    try:
        _drive_to(wiz, app, Screen.PICK)
        app._click_refresh()
        app._click_refresh()
        assert wiz.screen == Screen.REFRESHING
        app.root.update()
        app._teardown()
        assert app._ui_dead
        _join_scan_workers(app)
        for worker in app._refresh_threads.values():
            assert not worker.is_alive()
    finally:
        try:
            app._teardown()
        except Exception:
            pass


def test_accessible_refresh_opens_reader(monkeypatch):
    """F8: async scan, then the screen-reader handoff (Linux gate behavior)."""
    # Real-platform display check first: patching sys.platform below would
    # defeat _needs_display and abort a headless macOS process in Tk().
    _needs_display()
    monkeypatch.setattr("beamo_wipe.ui.tk_wizard.sys.platform", "linux")
    wiz, app, calls = _slow_scan_app(WINDOW, delay=0.5)
    try:
        _drive_to(wiz, app, Screen.PICK)
        start = time.monotonic()
        app._click_accessible()
        assert time.monotonic() - start < 0.5
        deadline = time.monotonic() + 15.0
        while not app._accessible_requested and time.monotonic() < deadline:
            app.root.update()
            time.sleep(0.02)
        assert app._accessible_requested
    finally:
        try:
            app._teardown()
        except Exception:
            pass


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize(
    "screen", [Screen.PICK, Screen.CONFIRM, Screen.LAST_CHANCE]
)
def test_long_identity_never_clips(size, screen):
    """139-char model + 64-char spaceless serial: no clip, no hidden tail."""
    wiz, app = _long_identity_app(size)
    try:
        _drive_to(wiz, app, screen, size=size)
        app._show_more = True  # also expose the device-path line on PICK
        app._draw()
        app.root.update_idletasks()
        app.root.update()
        assert app.w.screen == screen
        assert _clipping_problems(app) == []
        assert _off_window_problems(app) == []
    finally:
        app._teardown()


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_status_screens_fit(ui, size):
    for scenario, screen in (("empty", Screen.PICK_EMPTY), ("blocked", Screen.PICK_BLOCKED)):
        wiz, app = ui(scenario=scenario, size=size)
        wiz.skip_intro()
        wiz.accept_what()
        wiz.set_owner(True)
        wiz.continue_owner()
        app._draw()
        app.root.update_idletasks()
        app.root.update()
        assert app.w.screen == screen
        assert _clipping_problems(app) == []
        assert _off_window_problems(app) == []


def test_blocked_and_empty_use_recovery_section_labels(ui):
    from beamo_wipe import copy as C
    from beamo_wipe import recovery as Rec

    wiz, app = ui(scenario="blocked")
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    app._draw()
    app.root.update()
    labels = [w.cget("text") for w in descendants(app.root) if isinstance(w, tk.Label)]
    assert Rec.RECOVERY_HAPPENED in labels
    assert Rec.RECOVERY_MEANING in labels
    assert Rec.RECOVERY_NEXT in labels
    assert Rec.MEANING_BLOCKED in labels
    assert C.IDENTIFY_ERROR in labels
    empty, empty_app = ui(scenario="empty")
    empty.skip_intro()
    empty.accept_what()
    empty.set_owner(True)
    empty.continue_owner()
    empty_app._draw()
    empty_app.root.update()
    empty_labels = [
        w.cget("text") for w in descendants(empty_app.root) if isinstance(w, tk.Label)
    ]
    assert Rec.RECOVERY_HAPPENED in empty_labels
    assert Rec.MEANING_EMPTY in empty_labels
    assert C.EMPTY_DISKS in empty_labels
    assert Rec.RECOVERY_TECHNICAL not in empty_labels


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_done_screen_fits(ui, size):
    wiz, app = ui(size=size)
    # Exercise the shipped live Done controls, including Save report to USB,
    # rather than the shorter preview-only footer.
    wiz.preview = False
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz._erase_until = 0.0  # countdown already covered elsewhere; skip the 5s
    wiz.tick()
    wiz.runner.duration_s = 0.2
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    deadline = time.monotonic() + 5
    while wiz.screen != Screen.DONE and time.monotonic() < deadline:
        wiz.tick()
        app.root.update()
        time.sleep(0.02)
    app._draw()
    app.root.update_idletasks()
    assert wiz.screen == Screen.DONE
    assert wiz.can_save_report
    assert _clipping_problems(app) == []
    assert _off_window_problems(app) == []


def test_keyboard_only_flow_reaches_working(ui):
    """No mouse: any-key, Enter, Space, Up/Down, digits, Enter all the way."""
    wiz, app = ui()
    root = app.root

    def key(keysym):
        (root.focus_get() or root).event_generate("<KeyPress>", keysym=keysym)
        root.update()
        # Release on the root: KeyPress may have rebuilt the focused widget.
        root.event_generate("<KeyRelease>", keysym=keysym)
        root.update()

    key("a")
    assert wiz.screen == Screen.KEYBOARD
    key("Return")
    assert wiz.screen == Screen.WHAT
    key("Return")
    assert wiz.screen == Screen.OWNER
    key("space")
    assert wiz.owner_ok
    key("Return")
    assert wiz.screen == Screen.PICK
    key("Down")
    assert wiz.selected is not None
    first = wiz.selected.path
    key("Down")
    assert wiz.selected.path != first
    key("Up")
    assert wiz.selected.path == first
    key("Return")
    assert wiz.screen == Screen.CONFIRM
    # Entry char insertion is a stock Tk class binding; synthetic events on
    # some Tk builds carry no char, so drive the variable the Entry edits.
    app._confirm_var.set(wiz.confirm.token)
    root.update()
    assert wiz.token_ok
    key("Return")
    assert wiz.screen == Screen.METHOD
    key("2")
    assert wiz.method.value == "extra"
    key("1")
    assert wiz.method.value == "everyday"
    key("Return")
    assert wiz.screen == Screen.LAST_CHANCE
    # Back is focused: Enter returns safely, even during the countdown.
    key("Return")
    assert wiz.screen == Screen.METHOD
    key("Return")
    assert wiz.screen == Screen.LAST_CHANCE
    # Countdown over: deliberately focus Erase before pressing Enter.
    wiz._erase_until = 0.0
    wiz.tick()
    app._draw()
    root.update()
    assert wiz.erase_enabled
    key("Tab")
    assert root.focus_get() is app._primary
    key("Return")
    _wait_transition(wiz, app)
    assert wiz.screen == Screen.WORKING


def test_held_enter_does_not_erase_when_countdown_completes(ui, tmp_path, monkeypatch):
    """Same physical Enter that left Method must not fire Erase after 5s."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, app = ui()
    _drive_to(wiz, app, Screen.METHOD)
    root = app.root
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    root.update()
    assert wiz.screen == Screen.LAST_CHANCE
    assert not wiz.erase_enabled
    wiz._erase_until = 0.0
    wiz.tick()
    app._refresh_last_chance()
    root.update()
    assert wiz.erase_enabled
    app._primary.focus_set()
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    root.update()
    assert wiz.screen == Screen.LAST_CHANCE
    assert not getattr(wiz.runner, "started", False)
    (root.focus_get() or root).event_generate("<KeyRelease>", keysym="Return")
    root.update()
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    root.update()
    _wait_transition(wiz, app)
    assert wiz.screen == Screen.WORKING


def test_x11_release_press_autorepeat_pair_is_one_held_enter(ui, tmp_path, monkeypatch):
    """Queued X11 autorepeat Release/Press must not re-arm destructive Enter."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, app = ui()
    _drive_to(wiz, app, Screen.METHOD)
    app._on_return()
    assert wiz.screen == Screen.LAST_CHANCE
    wiz._erase_until = 0.0
    wiz.tick()
    # X11 queues this pair before the event loop becomes idle.
    app._on_return_release()
    app._on_return()
    assert wiz.screen == Screen.LAST_CHANCE
    assert not getattr(wiz.runner, "started", False)


def test_held_enter_does_not_skip_method_after_confirm(ui):
    """X11 auto-repeat Return after a matching token must not skip Method."""
    wiz, app = ui()
    _drive_to(wiz, app, Screen.CONFIRM)
    app._confirm_var.set(wiz.confirm.token)
    app.root.update()
    assert wiz.token_ok
    root = app.root
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    root.update()
    assert wiz.screen == Screen.METHOD
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    root.update()
    assert wiz.screen == Screen.METHOD
    (root.focus_get() or root).event_generate("<KeyRelease>", keysym="Return")
    root.update()
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    root.update()
    assert wiz.screen == Screen.LAST_CHANCE


def test_held_enter_does_not_shutdown_pick_empty(ui):
    """Auto-repeat Return from Owner must not power off the empty-disk copy."""
    wiz, app = ui(scenario="empty")
    wiz.preview = False
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    app._draw()
    app.root.update()
    root = app.root
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    root.update()
    assert wiz.screen == Screen.PICK_EMPTY
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    try:
        root.update()
    except tk.TclError:
        pytest.fail("Pick-empty Return tore down the window before the key was released")
    assert not wiz.wants_shutdown
    (root.focus_get() or root).event_generate("<KeyRelease>", keysym="Return")
    root.update()
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    try:
        root.update()
    except tk.TclError:
        pass
    assert wiz.wants_shutdown


def test_held_enter_does_not_shutdown_failed_done(ui):
    """Auto-repeat Return after a fast fail must not power off before Done is read."""
    wiz, app = ui(fail=True)
    wiz.preview = False
    wiz.runner.duration_s = 0.05
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz._erase_until = 0.0
    wiz.tick()
    app._draw()
    app.root.update()
    assert wiz.erase_enabled
    app._primary.focus_set()
    root = app.root
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    root.update()
    deadline = time.monotonic() + 3
    while wiz.screen != Screen.DONE and time.monotonic() < deadline:
        wiz.tick()
        try:
            root.update()
        except tk.TclError:
            break
        time.sleep(0.02)
    assert wiz.screen == Screen.DONE
    assert not wiz.done_ok
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    try:
        root.update()
    except tk.TclError:
        pytest.fail("Done Return tore down the window before the key was released")
    assert not wiz.wants_shutdown
    (root.focus_get() or root).event_generate("<KeyRelease>", keysym="Return")
    root.update()
    (root.focus_get() or root).event_generate("<KeyPress>", keysym="Return")
    try:
        root.update()
    except tk.TclError:
        pass
    assert wiz.wants_shutdown


def test_held_space_does_not_shutdown_pick_empty(ui):
    """Auto-repeat Space from Owner Continue must not power off the empty-disk copy."""
    wiz, app = ui(scenario="empty")
    wiz.preview = False
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    app._draw()
    app.root.update()
    continue_btn = app._primary
    assert continue_btn is not None
    continue_btn.focus_set()
    continue_btn.event_generate("<KeyPress>", keysym="space")
    app.root.update()
    assert wiz.screen == Screen.PICK_EMPTY
    shut = app._primary
    assert shut is not None
    shut.focus_set()
    shut.event_generate("<KeyPress>", keysym="space")
    try:
        app.root.update()
    except tk.TclError:
        pytest.fail("Pick-empty Space tore down the window before the key was released")
    assert not wiz.wants_shutdown
    shut = app._primary
    assert shut is not None
    shut.event_generate("<KeyRelease>", keysym="space")
    app.root.update()
    shut = app._primary
    assert shut is not None
    shut.focus_set()
    shut.event_generate("<KeyPress>", keysym="space")
    try:
        app.root.update()
    except tk.TclError:
        pass
    assert wiz.wants_shutdown


def test_held_space_does_not_shutdown_failed_done(ui):
    """Auto-repeat Space after a fast fail must not power off before Done is read."""
    wiz, app = ui(fail=True)
    wiz.preview = False
    wiz.runner.duration_s = 0.05
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz._erase_until = 0.0
    wiz.tick()
    app._draw()
    app.root.update()
    erase = app._primary
    assert erase is not None
    erase.focus_set()
    erase.event_generate("<KeyPress>", keysym="space")
    app.root.update()
    deadline = time.monotonic() + 3
    while wiz.screen != Screen.DONE and time.monotonic() < deadline:
        try:
            app.root.update()
        except tk.TclError:
            break
        time.sleep(0.02)
    assert wiz.screen == Screen.DONE
    assert not wiz.done_ok
    shut = app._primary
    assert shut is not None
    shut.focus_set()
    shut.event_generate("<KeyPress>", keysym="space")
    try:
        app.root.update()
    except tk.TclError:
        pytest.fail("Done Space tore down the window before the key was released")
    assert not wiz.wants_shutdown
    shut = app._primary
    assert shut is not None
    shut.event_generate("<KeyRelease>", keysym="space")
    app.root.update()
    shut = app._primary
    assert shut is not None
    shut.focus_set()
    shut.event_generate("<KeyPress>", keysym="space")
    try:
        app.root.update()
    except tk.TclError:
        pass
    assert wiz.wants_shutdown


def test_x11_space_release_press_pair_does_not_shutdown_done(ui):
    """A synthetic X11 release/press repeat pair is still one Space hold."""
    wiz, app = ui(scenario="empty")
    wiz.preview = False
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    app._draw()
    wiz.arm_done_keyboard()
    app._space_held = True
    app._on_space_release()

    shut = app._primary
    assert shut is not None
    shut._key()

    assert not wiz.wants_shutdown
    assert app._space_held


def test_held_space_from_save_cannot_repeat_onto_shutdown(ui, tmp_path, monkeypatch):
    """A fast report completion cannot move one held Space to Shut down."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, app = ui(fail=True)
    wiz.preview = False
    wiz.runner.duration_s = 0.05
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz._erase_until = 0.0
    wiz.tick()
    wiz.confirm_erase()
    deadline = time.monotonic() + 3
    while wiz.screen != Screen.DONE and time.monotonic() < deadline:
        wiz.tick()
        app.root.update()
    assert wiz.screen == Screen.DONE

    def exporter(**kwargs):
        from test_usb_report_workflow import _success_receipt

        return _success_receipt(**kwargs)

    wiz._report_exporter = exporter
    app._draw()
    save = _button_named(app, "Save report to USB")
    save.focus_set()
    save._key()
    deadline = time.monotonic() + 3
    while wiz.report_view.exporting and time.monotonic() < deadline:
        app.root.update()
    app._draw()
    assert wiz.report_status == "saved"
    assert not wiz._done_keyboard_armed

    shut = app._primary
    assert shut is not None
    shut._key()
    assert not wiz.wants_shutdown


def test_escape_goes_back(ui):
    wiz, app = ui()
    _drive_to(wiz, app, Screen.PICK)
    (app.root.focus_get() or app.root).event_generate("<KeyPress>", keysym="Escape")
    app.root.update()
    assert wiz.screen == Screen.OWNER


def _pick_list_overflows(app) -> bool:
    canvas = app._pick_canvas
    if canvas is None:
        return False
    app.root.update()
    bbox = canvas.bbox("all")
    return bool(bbox) and bbox[3] > canvas.winfo_height()


def test_pick_list_scrolls_selected_card_into_view(ui):
    """Keyboard navigation keeps the selected disk visible in long lists."""
    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.PICK, size=MIN_WINDOW)
    if not _pick_list_overflows(app):
        pytest.skip("disk list fits without scrolling at this size")
    ordered = sorted(wiz.selectable, key=lambda d: d.path)
    for _ in range(len(ordered)):
        (app.root.focus_get() or app.root).event_generate("<KeyPress>", keysym="Down")
        app.root.update()
    last = ordered[-1]
    assert wiz.selected is not None and wiz.selected.path == last.path
    canvas = app._pick_canvas
    card = app._pick_cards[last.path]
    top, bottom = canvas.yview()
    content_h = float(canvas.bbox("all")[3])
    y0 = card.winfo_y() / content_h
    y1 = (card.winfo_y() + card.winfo_height()) / content_h
    view_h = float(canvas.winfo_height())
    card_h = float(card.winfo_height())
    assert y0 >= top - 0.02, "selected card scrolled above the view"
    if card_h <= view_h:
        assert y1 <= bottom + 0.02, "selected card scrolled below the view"
    else:
        # Longer serial labels wrap until the card is taller than the list.
        # Restore keeps the identity (top) in view rather than the footer.
        assert abs(y0 - top) <= 0.02, "oversized selected card should stay top-aligned"


def test_leaving_picker_cancels_registered_restore_events(ui):
    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.PICK, size=MIN_WINDOW)
    app._draw()
    pending = set(app.root.tk.call("after", "info"))
    picker_events = set(app._pick_after_ids)
    assert len(picker_events) == 4
    assert picker_events <= pending
    wiz.back()
    app._draw()
    assert not picker_events.intersection(app.root.tk.call("after", "info"))
    assert app._pick_after_ids == []


def test_pick_list_keeps_scroll_position_on_click(ui):
    """Clicking a disk must not snap the rebuilt list back to the top."""
    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.PICK, size=MIN_WINDOW)
    if not _pick_list_overflows(app):
        pytest.skip("disk list fits without scrolling at this size")
    app._pick_canvas.yview_moveto(0.5)
    app.root.update()
    first = sorted(wiz.selectable, key=lambda d: d.path)[0]
    app._click_disk(first.path)
    app.root.update()
    assert app._pick_canvas.yview()[0] > 0.2


def test_every_screen_has_a_focusable_action(ui):
    """Keyboard users always land on (or can Tab to) a live control."""
    for screen in (Screen.WHAT, Screen.OWNER, Screen.PICK, Screen.CONFIRM,
                   Screen.METHOD, Screen.ADVANCED, Screen.LAST_CHANCE):
        wiz, app = ui()
        _drive_to(wiz, app, screen)
        focusable = []

        def visit(w):
            try:
                if w.winfo_ismapped():
                    tf = str(w.cget("takefocus"))
                    # Empty takefocus means "class default": Entries take
                    # focus, most other classes do not.
                    if tf == "1" or (tf == "" and w.winfo_class() == "Entry"):
                        focusable.append(w.winfo_class())
            except tk.TclError:
                pass
            for child in w.winfo_children():
                visit(child)

        visit(app.root)
        assert focusable, f"{screen} has no focusable widget"


def test_needs_display_skips_without_aborting(monkeypatch):
    """Headless must skip, never abort the gate (needs no display itself)."""
    import sys as _sys

    monkeypatch.setattr(_sys, "platform", "darwin")
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(pytest.skip.Exception):
        _needs_display()


def test_needs_display_skips_when_tk_raises(monkeypatch):
    """Linux/CI headless path: Tk() raising must skip, never propagate."""
    import sys as _sys
    import tkinter as _tkmod

    monkeypatch.setattr(_sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")

    def _boom(*args, **kwargs):
        raise _tkmod.TclError("couldn't connect to display")

    monkeypatch.setattr(_tkmod, "Tk", _boom)
    with pytest.raises(pytest.skip.Exception):
        _needs_display()


@pytest.mark.parametrize("method", list(METHODS))
@pytest.mark.parametrize("screen", [Screen.METHOD, Screen.LAST_CHANCE, Screen.DONE])
def test_method_facts_render_for_every_choice(ui, method, screen):
    from beamo_wipe.methods import METHODS

    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.METHOD)
    wiz.set_method(method)
    if screen != Screen.METHOD:
        wiz.continue_method()
    if screen == Screen.DONE:
        wiz.screen = Screen.DONE  # preview only; never starts a runner
    app._draw()
    app.root.update()
    texts = []
    def visit(widget):
        if widget.winfo_ismapped() and widget.winfo_class() == "Label":
            texts.append(str(widget.cget("text")))
        for child in widget.winfo_children():
            visit(child)
    visit(app.root)
    text = " ".join(texts)
    if screen == Screen.METHOD:
        for spec in METHODS.values():
            assert spec.overwrite_description in text
            assert spec.verification_description in text
    else:
        assert METHODS[method].summary in text
    if screen == Screen.DONE:
        assert wiz.method_result in text
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)


@pytest.mark.parametrize("kind", ["SSD", "HDD", "Unknown"])
@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_storage_limits_visible_and_keyboard_reachable(ui, kind, size):
    from dataclasses import replace
    from types import SimpleNamespace
    from beamo_wipe.models import DiskKind
    from beamo_wipe import storage_limits as limits

    wiz, app = ui(size=size)
    _drive_to(wiz, app, Screen.METHOD)
    wiz.selected = replace(wiz.selected, kind=DiskKind(kind))
    selected = wiz.selected
    method = wiz.method
    app._draw()
    app.root.update()
    texts = []
    def visit(widget):
        if widget.winfo_ismapped() and widget.winfo_class() == "Label":
            texts.append(str(widget.cget("text")))
        for child in widget.winfo_children():
            visit(child)
    visit(app.root)
    assert limits.notice(selected.kind) in texts
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    app._on_key(SimpleNamespace(keysym="l", char="l"))
    app.root.update()
    assert wiz.screen == Screen.LIMITS
    reader = app.root.focus_get()
    assert reader.winfo_class() == "Text"
    assert reader.get("1.0", "end-1c") == limits.full_text()
    reader.event_generate("<Next>")
    app.root.update()
    assert reader.yview()[0] > 0 or reader.yview()[1] == 1.0
    app._on_escape()
    assert wiz.screen == Screen.METHOD
    assert wiz.selected == selected
    assert wiz.method == method
    assert not wiz.runner.started


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_other_devices_read_only_and_keyboard_isolated(ui, size):
    from types import SimpleNamespace
    from beamo_wipe.inventory import full_text

    wiz, app = ui(size=size)
    _drive_to(wiz, app, Screen.PICK)
    readers = []
    def visit(widget):
        if getattr(widget, "_beamo_inventory", False):
            readers.append(widget)
        for child in widget.winfo_children():
            visit(child)
    visit(app.root)
    assert len(readers) == 1
    reader = readers[0]
    assert reader.winfo_ismapped()
    assert reader.cget("state") == "disabled"
    assert reader.get("1.0", "end-1c") == full_text(wiz.other_devices)
    assert set(app._pick_cards) == {d.path for d in wiz.selectable}
    before = wiz.selected
    reader.focus_force()
    app.root.update()
    app._on_key(SimpleNamespace(keysym="Down", char=""))
    reader.event_generate("<Return>")
    app.root.update()
    assert wiz.screen == Screen.PICK
    assert wiz.selected == before
    assert not _off_window_problems(app)
    assert not _clipping_problems(app)
    assert not wiz.runner.started




@pytest.mark.parametrize("case", RESULT_CASES, ids=[c[0] for c in RESULT_CASES])
@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_every_terminal_result_renders_consistent_text(ui, case, size):
    _, app = ui(size=size)
    wiz, evidence, _ = case_evidence(case)
    app.w = wiz
    app._draw()
    app.root.update()
    texts = []
    colors = []
    def visit(widget):
        if widget.winfo_ismapped() and widget.winfo_class() == "Label":
            texts.append(str(widget.cget("text")))
        if widget.winfo_class() == "Canvas":
            for item in widget.find_all():
                try:
                    colors.append(widget.itemcget(item, "fill"))
                except tk.TclError:
                    pass
        for child in widget.winfo_children():
            visit(child)
    visit(app.root)
    assert wiz.result_view.message in texts
    assert wiz.result_view.next_step in texts
    assert evidence["presentation"]["announcement"] == wiz.result_view.announcement
    from beamo_wipe import recovery as Rec
    if wiz.result_view.success:
        assert Rec.RECOVERY_HAPPENED not in texts
    else:
        assert Rec.RECOVERY_HAPPENED in texts
        assert Rec.RECOVERY_MEANING in texts
        assert Rec.RECOVERY_NEXT in texts
        assert Rec.recovery_for_view(wiz.result_view).meaning in texts
    from beamo_wipe.outcomes import AFTERCARE_SUCCESS
    shown = " ".join(texts)
    if wiz.result_view.success:
        assert AFTERCARE_SUCCESS in shown
    else:
        assert AFTERCARE_SUCCESS not in shown
        assert "was processed" not in shown
    from beamo_wipe.ui.tk_wizard import OK, WARN, DANGER
    tone = {"ok": OK, "warn": WARN, "danger": DANGER}[wiz.result_view.tone]
    assert tone in colors
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)


def test_held_f5_cannot_skip_refresh_wording(ui):
    from types import SimpleNamespace
    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    app._on_key(SimpleNamespace(keysym="F5", char=""))
    assert wiz.screen == Screen.REFRESH_CONFIRM
    assert wiz.selected is not None and wiz.owner_ok
    app._on_key(SimpleNamespace(keysym="F5", char=""))
    assert wiz.screen == Screen.REFRESH_CONFIRM
    app._on_f5_release()
    app._on_key(SimpleNamespace(keysym="F5", char=""))
    assert wiz.screen == Screen.REFRESHING
    assert _await_scan_done(app) == Screen.WHAT


@pytest.mark.parametrize("screen", [Screen.PICK, Screen.PICK_EMPTY, Screen.PICK_BLOCKED, Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE])
def test_graphical_refresh_restarts_full_authorization(ui, screen):
    from types import SimpleNamespace
    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz.screen = screen
    app._draw()
    app._on_key(SimpleNamespace(keysym="F5", char=""))
    assert wiz.screen == Screen.REFRESH_CONFIRM
    assert wiz.selected is not None
    app._on_f5_release()
    app._on_key(SimpleNamespace(keysym="F5", char=""))
    assert wiz.screen == Screen.REFRESHING
    assert _await_scan_done(app) == Screen.WHAT
    assert wiz.selected is None and not wiz.owner_ok and not wiz.confirm_input
    assert not wiz.runner.started
    assert not _clipping_problems(app)


@pytest.mark.parametrize("fresh_ok", [True, False])
def test_screen_reader_switch_clears_authorization(ui, monkeypatch, fresh_ok):
    wiz, app = ui()
    monkeypatch.setattr("beamo_wipe.ui.tk_wizard.sys.platform", "linux")
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    if not fresh_ok:
        def fail():
            raise OSError("fake discovery failure")
        wiz._rediscover = fail
    app._click_accessible()
    # Refresh now scans off the UI thread: the handoff lands once applied.
    assert wiz.screen == Screen.REFRESHING
    deadline = time.monotonic() + 15.0
    while not app._accessible_requested and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    assert wiz.selected is None and not wiz.owner_ok and not wiz.confirm_input
    assert app._accessible_requested  # Both successful and blocked refreshes use the reader view.
    assert wiz.screen == (Screen.WHAT if fresh_ok else Screen.PICK_BLOCKED)


def test_screen_reader_switch_unavailable_during_erase(ui, monkeypatch):
    wiz, app = ui()
    monkeypatch.setattr("beamo_wipe.ui.tk_wizard.sys.platform", "linux")
    wiz.screen = Screen.WORKING
    app._click_accessible()
    assert not app._accessible_requested and wiz.screen == Screen.WORKING


@pytest.mark.parametrize("screen", [Screen.PICK_EMPTY, Screen.PICK_BLOCKED, Screen.LAST_CHANCE])
def test_startup_diagnostic_path_renders_and_returns_without_wipe(ui, screen):
    wiz, app = ui(size=MIN_WINDOW)
    wiz.preview = False
    wiz.screen = screen
    wiz.error = "The safety checks prevented startup."
    app._draw()
    app.root.update_idletasks()
    assert wiz.can_open_diagnostic
    wiz.open_diagnostic()
    app._draw()
    app.root.update_idletasks()
    assert wiz.screen == Screen.DIAGNOSTIC
    assert _clipping_problems(app) == []
    assert _button_named(app, "Prepare")
    app._on_escape()
    app.root.update_idletasks()
    assert wiz.screen == screen and wiz._wipe_request is None


@pytest.mark.parametrize("wanted", [True, False])
@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize("origin", [Screen.WHAT, Screen.METHOD, Screen.ADVANCED])
def test_report_help_rendered_preference_and_layout(ui, wanted, size, origin):
    from beamo_wipe import copy as C
    wiz, app = ui(size=size)
    _drive_to(wiz, app, origin, size)

    def widgets(widget):
        yield widget
        for child in widget.winfo_children():
            yield from widgets(child)

    link = _button_named(app, C.REPORT_HELP_TITLE)
    link._command()
    app.root.update_idletasks()
    reader = next(w for w in widgets(app.root) if isinstance(w, tk.Text))
    assert reader.get('1.0', 'end-1c') == C.REPORT_HELP_TEXT
    checkbox = next(w for w in widgets(app.root) if isinstance(w, _CheckRow))
    assert not wiz.report_wanted
    if wanted:
        checkbox.invoke()
    assert wiz.report_wanted is wanted
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    reader.yview_moveto(1.0)
    app.root.update_idletasks()
    assert reader.yview()[1] == 1.0
    wiz.back()
    app._draw()
    assert wiz.screen == origin and not wiz.runner.started
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)


def test_saved_receipt_location_fits_minimum_window(ui, tmp_path):
    from beamo_wipe.support_export import destination_label_for
    from test_usb_report_workflow import _done_wizard, _success_receipt

    _, app = ui(size=MIN_WINDOW)
    wiz = _done_wizard(
        lambda **kw: _success_receipt(
            **kw,
            destination_label=destination_label_for("W" * 200, 32_000_000),
            log_status="tail",
        ),
        tmp_path,
    )
    wiz.screen = Screen.REPORT_HELP
    wiz.set_report_share_redacted(True)
    wiz.screen = Screen.DONE
    wiz.save_report_to_usb()
    app.w = wiz
    app._draw()
    app.root.update_idletasks()
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    rendered = []

    def visit(w):
        if isinstance(w, tk.Label):
            rendered.append(w.cget("text"))
        for child in w.winfo_children():
            visit(child)

    visit(app.root)
    blob = "\n".join(rendered)
    assert "Folder: BEAMO-WIPE-REPORTS/" in blob
    assert "RESULT.txt is the original report." in blob
    assert "SHARE.json is a privacy-reduced sharing copy" in blob
    assert "Engine log: only a final tail." in blob
    assert "/run/" not in blob and "/dev/" not in blob


@pytest.mark.parametrize('message', ['No new report USB found. Insert exactly one new FAT32 report USB, then try again.',
                                    'Use a FAT32 report USB. Other filesystems are not mounted.',
                                    'The report USB was removed.'])
def test_report_aftercare_errors_and_lifetime_at_minimum_size(ui, tmp_path, message):
    from beamo_wipe import copy as C
    from test_usb_report_workflow import _done_wizard, _success_receipt
    _, app = ui(size=MIN_WINDOW)
    wiz = _done_wizard(_success_receipt, tmp_path)
    wiz.report_status = 'error'
    wiz.report_message = message
    app.w = wiz
    app._draw()
    app.root.update_idletasks()
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    rendered = []
    def visit(w):
        if isinstance(w, tk.Label):
            rendered.append(w.cget('text'))
        for child in w.winfo_children():
            visit(child)
    visit(app.root)
    assert any(message in value and C.REPORT_VOLATILE in value for value in rendered)


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize("origin", [Screen.DONE, Screen.PICK_BLOCKED, Screen.WHAT])
def test_unsaved_report_decision_renders_and_defaults_to_keep(ui, size, origin):
    from beamo_wipe import copy as C

    w, app = ui(size=size)
    w.screen, w.report_wanted = origin, True
    app._close()
    app.root.update()
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not w.wants_shutdown
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    assert app.root.focus_get() == app._primary
    assert app._primary.itemcget(app._primary._label, "text") == C.SHUTDOWN_KEEP
    app._on_return()
    assert w.screen == origin and not w.wants_shutdown and w.report_wanted
    app._release_return()
    app._close()
    app._on_escape()
    assert w.screen == origin and not w.wants_shutdown


def test_tk_unsaved_report_discard_requires_new_focused_space(ui):
    from beamo_wipe import copy as C

    w, app = ui(size=MIN_WINDOW)
    w.screen, w.report_wanted = Screen.DONE, True
    w.preview = False
    w.arm_done_keyboard()
    app._on_return()
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not w.wants_shutdown
    app._on_return()
    assert not w.wants_shutdown
    app._release_return()
    discard = _button_named(app, C.SHUTDOWN_DISCARD)
    discard.focus_set()
    discard._key()
    assert w.wants_shutdown


@pytest.mark.parametrize("wanted,saved", [(False, False), (True, True), (True, False)])
def test_tk_finished_shutdown_uses_receipt_not_history(ui, tmp_path, wanted, saved):
    from test_usb_report_workflow import _done_wizard, _success_receipt

    _, app = ui(size=MIN_WINDOW)
    app.w = w = _done_wizard(_success_receipt, tmp_path)
    w.report_wanted = wanted
    if saved:
        w.save_report_to_usb()
    app._close()
    assert w.wants_shutdown is (not wanted or saved)
    if not w.wants_shutdown:
        assert w.screen == Screen.SHUTDOWN_CONFIRM


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize("case", [RESULT_CASES[0], RESULT_CASES[1]])
def test_recovered_done_warning_and_actions_fit(ui, size, case):
    wizard, _, _ = case_evidence(case)
    _, app = ui(size=size)
    app.w = wizard
    wizard._recovered = True
    app._draw()
    app.root.update_idletasks()
    assert "power loss" in wizard.result_view.next_step
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)


@pytest.mark.parametrize('size', [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize('phase', ['working', 'done', 'exhausted'])
def test_evidence_failure_warning_and_retry_layout(ui, tmp_path, monkeypatch, size, phase):
    from beamo_wipe import evidence
    from test_evidence_retry import start, complete, fail
    _, app = ui(size=size)
    monkeypatch.setattr(evidence, 'write_evidence_atomic', fail)
    w, clock = start(tmp_path, monkeypatch)
    app.w = w
    if phase != 'working':
        complete(w, clock)
    if phase == 'exhausted':
        for _ in range(3):
            w.retry_evidence_save()
    app._draw()
    app.root.update_idletasks()
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)
    text = '\n'.join(str(x.cget('text')) for x in walk(app.root) if x.winfo_class() == 'Label')
    assert w.evidence_warning in text
    if phase == 'working':
        assert app._progress_label is not None
        assert w.screen == Screen.WORKING
    else:
        buttons = [x for x in walk(app.root) if isinstance(x, _Button)]
        retry = next(x for x in buttons if x.itemcget(x._label, 'text') == 'Retry evidence save')
        assert retry._enabled == (phase == 'done')


def _wait_transition(w, app):
    deadline = time.monotonic() + 3
    while w.screen in {Screen.CHECKING, Screen.STOPPING} and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.005)
    assert w.screen not in {Screen.CHECKING, Screen.STOPPING}
    app._tick()


@pytest.mark.parametrize("phase", ["checking", "stopping"])
@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_busy_transition_renders_and_pumps_events(ui, monkeypatch, tmp_path, phase, size):
    from test_busy_transitions import Barrier
    w, app = ui(size=size)
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(w, "_write_evidence", lambda **kw: None)
    w.runner._clock = lambda: 0
    _drive_to(w, app, Screen.LAST_CHANCE)
    w._erase_until = 0
    barrier = Barrier()
    if phase == "checking":
        original = w.runner.start
        def slow(request):
            barrier.wait()
            original(request)
        monkeypatch.setattr(w.runner, "start", slow)
        app._nav(w.begin_erase)()
    else:
        w.confirm_erase()
        app._draw()
        original = w.runner.cancel
        def slow():
            barrier.wait()
            original()
        monkeypatch.setattr(w.runner, "cancel", slow)
        app._click_cancel()
        app._primary._command()
    try:
        assert barrier.entered.wait(2)
        beats = []
        app.root.after_idle(lambda: beats.append("event loop alive"))
        app.root.update()
        app._tick()
        assert beats == ["event loop alive"]
        assert app._shown == (Screen.CHECKING if phase == "checking" else Screen.STOPPING)
        assert app._primary is None
        assert _clipping_problems(app) == []
        assert _off_window_problems(app) == []
        app._close()
        app._on_escape()
        app._on_return()
        assert not w.wants_shutdown and w.screen == app._shown
    finally:
        barrier.join(w)
    _wait_transition(w, app)
    assert app._shown == w.screen


def test_rebuilt_last_chance_rejects_old_erase_callback(ui, monkeypatch):
    w, app = ui()
    _drive_to(w, app, Screen.LAST_CHANCE)
    w._erase_until = 0
    calls = []
    monkeypatch.setattr(w, "begin_erase", lambda: calls.append("erase"))
    stale = app._nav(w.begin_erase)
    app._draw()
    stale()
    assert not calls
    app._nav(w.begin_erase)()
    assert calls == ["erase"]


def test_working_timer_keeps_cancel_control_until_revision_changes(ui, monkeypatch, tmp_path):
    w, app = ui()
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(w, "_write_evidence", lambda **kw: None)
    w.runner._clock = lambda: 0
    _drive_to(w, app, Screen.LAST_CHANCE)
    w._erase_until = 0
    w.confirm_erase()
    app._draw()
    generation = app._draw_generation
    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)
    cancel = next(v for v in walk(app.root) if isinstance(v, _Button)
                  and v.itemcget(v._label, "text") == "Stop erase")
    app._tick()
    app._tick()
    assert app._draw_generation == generation and cancel.winfo_exists()
    with w._lock:
        w._touch_report_locked()
    app._tick()
    assert app._draw_generation == generation + 1


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_timing_text_readable_and_working_controls_stable(ui, size):
    from beamo_wipe.progress import ProgressView
    from unittest.mock import PropertyMock, patch
    from beamo_wipe.wizard import Wizard

    wiz, app = ui(size=size)
    wiz.screen = Screen.WORKING
    wiz.selected = wiz.selectable[0]
    view = ProgressView("Verifying", 82, 90061, 7200)
    with patch.object(Wizard, "progress_view", new_callable=PropertyMock, return_value=view):
        app._draw()
        app.root.update_idletasks()
        label = app._progress_label
        assert label.cget("text") == view.timing_text
        assert "Estimated time remaining: about 2 hours" in label.cget("text")
        assert label.winfo_height() >= label.winfo_reqheight()
        assert label.winfo_rooty() + label.winfo_height() < app.root.winfo_rooty() + app.root.winfo_height()
        for _ in range(10):
            app._refresh_working()
        assert app._progress_label is label
        assert app._progress_pct.cget("text") == "82%"


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_stale_progress_is_marked_old_and_does_not_animate(ui, size):
    from beamo_wipe.progress import STALE_MEANING, STALE_NEXT, ProgressView
    from unittest.mock import PropertyMock, patch
    from beamo_wipe.wizard import Wizard

    wiz, app = ui(size=size)
    wiz.screen = Screen.WORKING
    wiz.selected = wiz.selectable[0]
    view = ProgressView("Writing", 42, 120, stale_for=11, percent_is_old=True)
    with patch.object(Wizard, "progress_view", new_callable=PropertyMock, return_value=view):
        app._draw()
        app.root.update_idletasks()
        assert app._progress_pct.cget("text") == "42% (old)"
        assert "No new progress update for less than 1 minute." in app._progress_label.cget("text")
        assert STALE_MEANING in app._progress_label.cget("text")
        assert STALE_NEXT in app._progress_label.cget("text")
        label = app._progress_label
        assert label.winfo_height() >= label.winfo_reqheight()
        assert label.winfo_rooty() + label.winfo_height() < app.root.winfo_rooty() + app.root.winfo_height()
        before = [app._progress_bar.coords(item) for item in app._progress_bar.find_all()]
        for _ in range(10):
            app._refresh_working()
        after = [app._progress_bar.coords(item) for item in app._progress_bar.find_all()]
        assert after == before


def test_preparing_animates_only_before_the_first_number(ui):
    from beamo_wipe.progress import ProgressView
    from unittest.mock import PropertyMock, patch
    from beamo_wipe.wizard import Wizard

    wiz, app = ui()
    wiz.screen = Screen.WORKING
    wiz.selected = wiz.selectable[0]
    live = ProgressView("Preparing", None, 1)
    with patch.object(Wizard, "progress_view", new_callable=PropertyMock, return_value=live):
        app._draw()
        app.root.update_idletasks()
        before = [app._progress_bar.coords(item) for item in app._progress_bar.find_all()]
        for _ in range(8):
            app._refresh_working()
        moved = [app._progress_bar.coords(item) for item in app._progress_bar.find_all()]
        assert moved != before
    stale = ProgressView("Preparing", None, 21, stale_for=21)
    with patch.object(Wizard, "progress_view", new_callable=PropertyMock, return_value=stale):
        app._refresh_working()
        frozen = [app._progress_bar.coords(item) for item in app._progress_bar.find_all()]
        for _ in range(8):
            app._refresh_working()
        assert [app._progress_bar.coords(item) for item in app._progress_bar.find_all()] == frozen
        assert "No new progress update" in app._progress_label.cget("text")
        assert app._progress_pct.cget("text") == ""


def test_stopping_shows_elapsed_without_estimate(ui):
    wiz, app = ui()
    wiz.screen = Screen.STOPPING
    app._draw()
    app.root.update_idletasks()
    assert "Stopping" in app._progress_label.cget("text")
    assert "Elapsed:" in app._progress_label.cget("text")
    assert "remaining" not in app._progress_label.cget("text")


def test_working_redraw_keeps_receiver_for_held_enter_release(ui, tmp_path, monkeypatch):
    """Destroying the Erase button must not strand its pending key release."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, app = ui()
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz._erase_until = 0.0
    wiz.tick()
    app._draw()
    app.root.update()
    app._primary.focus_set()
    app.root.update()
    app._on_return()
    _wait_transition(wiz, app)
    assert wiz.screen == Screen.WORKING
    receiver = app.root.focus_get()
    assert receiver is not None, "Working redraw lost the keyboard release receiver"
    receiver.event_generate("<KeyRelease>", keysym="Return")
    app.root.update()
    assert not app._return_held


def test_isolated_x11_physical_return_release_after_start(ui, tmp_path, monkeypatch):
    """Exercise server-delivered key events only on an explicitly isolated Xvfb."""
    import ctypes
    import ctypes.util
    import os
    import sys

    if sys.platform != "linux" or os.environ.get("BEAMO_ISOLATED_X11_TEST") != "1":
        pytest.skip("physical key injection requires an isolated test X server")
    x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
    xtst = ctypes.CDLL(ctypes.util.find_library("Xtst"))
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_uint
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    connection = x11.XOpenDisplay(None)
    assert connection
    code = x11.XKeysymToKeycode(connection, 0xFF0D)
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, app = ui()
    wiz.runner.duration_s = 30
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz._erase_until = 0
    wiz.tick()
    app._draw()
    app.root.update()
    app._primary.focus_force()
    app.root.update()
    try:
        xtst.XTestFakeKeyEvent(connection, code, 1, 0)
        x11.XFlush(connection)
        deadline = time.monotonic() + 5
        while wiz.screen != Screen.WORKING and time.monotonic() < deadline:
            app.root.update()
            time.sleep(0.01)
        assert wiz.screen == Screen.WORKING
        # Keep the key held across the next report-driven working redraw.
        app._draw()
        repeat_until = time.monotonic() + 1.2
        while time.monotonic() < repeat_until:
            app.root.update()
            time.sleep(0.01)
        assert app._return_held
        xtst.XTestFakeKeyEvent(connection, code, 0, 0)
        x11.XFlush(connection)
        deadline = time.monotonic() + 3
        while app._return_held and time.monotonic() < deadline:
            app.root.update()
            time.sleep(0.01)
        assert not app._return_held, "server-delivered Return release was lost"
    finally:
        xtst.XTestFakeKeyEvent(connection, code, 0, 0)
        x11.XFlush(connection)
        x11.XCloseDisplay(connection)


def test_split_repeat_does_not_skip_method(ui):
    wiz, app = ui()
    _drive_to(wiz, app, Screen.CONFIRM)
    app._confirm_var.set(wiz.confirm.token)
    app.root.update()
    app._on_return(SimpleNamespace(time=100))
    assert wiz.screen == Screen.METHOD
    app._on_return_release(SimpleNamespace(time=200))
    app.root.update_idletasks()
    app._on_return(SimpleNamespace(time=200))
    assert wiz.screen == Screen.METHOD


def test_split_repeat_cannot_erase_after_countdown(ui, tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, app = ui()
    _drive_to(wiz, app, Screen.METHOD)
    app._on_return(SimpleNamespace(time=100))
    assert wiz.screen == Screen.LAST_CHANCE
    wiz._erase_until = 0
    wiz.tick()
    app._on_return_release(SimpleNamespace(time=200))
    app.root.update_idletasks()
    app._on_return(SimpleNamespace(time=200))
    assert wiz.screen == Screen.LAST_CHANCE
    assert not getattr(wiz.runner, "started", False)
    # A separate physical press on the explicitly focused Erase still works.
    app._refresh_last_chance()
    app._primary.focus_set()
    app._on_return_release(SimpleNamespace(time=300))
    app.root.update_idletasks()
    app._on_return(SimpleNamespace(time=400))
    _wait_transition(wiz, app)
    assert wiz.screen == Screen.WORKING


def test_split_space_repeat_does_not_toggle_owner_twice(ui):
    wiz, app = ui()
    _drive_to(wiz, app, Screen.OWNER)
    app._owner_key(SimpleNamespace(time=100))
    assert wiz.owner_ok
    app._on_space_release(SimpleNamespace(time=200))
    app.root.update_idletasks()
    app._owner_key(SimpleNamespace(time=200))
    assert wiz.owner_ok
    app._on_space_release(SimpleNamespace(time=300))
    app.root.update_idletasks()
    app._owner_key(SimpleNamespace(time=400))
    assert not wiz.owner_ok


@pytest.mark.parametrize("keysym", ["Return", "KP_Enter"])
@pytest.mark.parametrize("countdown_complete", [False, True])
def test_last_chance_enter_activates_default_back(ui, keysym, countdown_complete):
    from beamo_wipe import copy as C

    wiz, app = ui()
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    if countdown_complete:
        wiz._erase_until = 0
        app._refresh_last_chance()
    assert app.root.focus_get() is _button_named(app, C.BTN_BACK)
    app.root.focus_get().event_generate("<KeyPress>", keysym=keysym)
    app.root.update()
    assert wiz.screen == Screen.METHOD
    assert not getattr(wiz.runner, "started", False)


def _label_text(app) -> str:
    texts = []

    def visit(widget):
        if widget.winfo_ismapped() and widget.winfo_class() == "Label":
            texts.append(str(widget.cget("text")))
        for child in widget.winfo_children():
            visit(child)

    visit(app.root)
    return "\n".join(texts)


def test_what_screen_shows_backup_and_os_prepare_at_minimum_size(ui):
    from beamo_wipe import copy as C

    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.WHAT, size=MIN_WINDOW)
    shown = _label_text(app)
    for bullet in C.WHAT_BULLETS:
        assert bullet in shown
    assert "copies you need" in shown
    assert "recovery partitions on that disk" in shown
    assert C.POWER_REMINDER in shown
    assert C.POWER_BLANKING in shown
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)


@pytest.mark.parametrize("contents,prepare", [
    ("windows", "This selected disk shows Windows partitions"),
    ("system", "This selected disk shows operating-system partitions"),
    ("data", "does not show operating-system partitions"),
    ("unknown", "including any operating system"),
])
@pytest.mark.parametrize("screen", [Screen.CONFIRM, Screen.LAST_CHANCE])
def test_prepare_text_visible_for_system_and_data_disks(ui, contents, prepare, screen):
    from dataclasses import replace
    from beamo_wipe import copy as C

    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, screen, size=MIN_WINDOW)
    wiz.selected = replace(wiz.selected, contents=contents)
    app._draw()
    app.root.update_idletasks()
    app.root.update()
    shown = _label_text(app)
    assert prepare in shown
    assert wiz.selected.display_name in shown
    assert wiz.selected.serial in shown
    assert C.prepare_selected(wiz.selected) in shown
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW, (800, 600)])
def test_connection_is_visible_on_pick_without_show_more(ui, size):
    wiz, app = ui(size=size)
    wiz.screen = Screen.PICK
    app._show_more = False
    app._draw()
    app.root.update()

    def descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from descendants(child)

    shown = _label_text(app)
    assert "USB" in shown and "SATA" in shown and "NVMe" in shown
    labels = [w for w in descendants(app.root) if getattr(w, "_beamo_connection", False)]
    assert labels
    assert all(w.winfo_ismapped() for w in labels)
    assert wiz.selected is None or wiz.selected.path not in shown
    assert not app._show_more
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    assert not wiz.runner.started


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW, (800, 600)])
def test_serial_number_label_is_visible_without_show_more(ui, size):
    from beamo_wipe.identity import SERIAL_LABEL

    wiz, app = ui(size=size)
    wiz.screen = Screen.PICK
    app._show_more = False
    app._draw()
    app.root.update()
    shown = _label_text(app)
    assert SERIAL_LABEL in shown
    assert "S4EVNX0N123456" in shown
    assert "BEAMOUSB001" in shown
    assert not app._show_more
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    assert not wiz.runner.started


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW, (800, 600)])
def test_pick_shows_tb_capacity_and_type_unknown(ui, size):
    from beamo_wipe.copy import KIND_UNKNOWN
    from beamo_wipe.models import DiskKind

    wiz, app = ui(size=size)
    wiz.screen = Screen.PICK
    app._show_more = False
    unknown = replace(wiz.selectable[0], kind=DiskKind.UNKNOWN)
    wiz.discovery = replace(
        wiz.discovery,
        disks=tuple(unknown if d.path == unknown.path else d for d in wiz.discovery.disks),
        selectable=tuple(unknown if d.path == unknown.path else d for d in wiz.discovery.selectable),
    )
    app._draw()
    app.root.update()
    shown = _label_text(app)
    assert "1 TB (1000 GB)" in shown
    assert "256 GB" in shown
    assert KIND_UNKNOWN in shown
    assert not app._show_more
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    assert not wiz.runner.started


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize("scenario,expected", [
    ("happy", "3 disks available to erase · Beamo USB protected · 1 other device not available"),
    ("empty", "No disks available to erase · Beamo USB protected · 1 other device not available"),
    ("blocked", "Disk list could not be confirmed. No disk is available to erase."),
])
def test_inventory_count_is_visible_on_pick_screens(ui, size, scenario, expected):
    wiz, app = ui(scenario=scenario, size=size)
    screen = {
        "happy": Screen.PICK,
        "empty": Screen.PICK_EMPTY,
        "blocked": Screen.PICK_BLOCKED,
    }[scenario]
    wiz.screen = screen
    app._draw()
    app.root.update()

    def descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from descendants(child)

    labels = [w for w in descendants(app.root) if getattr(w, "_beamo_inventory_count", False)]
    shown = _label_text(app)
    assert expected in shown
    if scenario != "blocked":
        assert len(labels) == 1
        assert expected in str(labels[0].cget("text"))
        assert labels[0].winfo_ismapped()
    assert "Choose one disk" not in shown
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    assert wiz.discovery.boot is None or wiz.discovery.boot.path not in app._pick_cards
    assert not wiz.runner.started


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize("scenario", ["happy", "empty"])
@pytest.mark.parametrize("long_identity", [False, True])
def test_protected_boot_card_is_separate_and_never_clickable(ui, size, scenario, long_identity):
    wiz, app = ui(scenario=scenario, size=size)
    screen = Screen.PICK if scenario == "happy" else Screen.PICK_EMPTY
    if long_identity:
        boot = replace(wiz.discovery.boot, model="VeryLongBootModel" * 12,
                       raw_model="VeryLongBootModel" * 12, serial="BOOTIDENTITY" * 24)
        wiz.discovery = replace(wiz.discovery, boot=boot,
                                disks=tuple(boot if d.path == boot.path else d for d in wiz.discovery.disks))
    wiz.screen = screen
    app._draw()
    app.root.update()
    def descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from descendants(child)
    cards = [w for w in descendants(app.root) if getattr(w, "_beamo_protected_boot", False)]
    assert len(cards) == 1
    card = cards[0]
    labels = " ".join(str(w.cget("text")) for w in descendants(card) if isinstance(w, tk.Label))
    assert "Beamo USB" in labels and "protected, cannot be erased" in labels
    assert wiz.discovery.boot.serial in labels.replace("\u200b", "").replace("\n", "")
    assert card.winfo_ismapped()
    for widget in descendants(card):
        assert not widget.bind("<Button-1>")
    assert wiz.discovery.boot.path not in app._pick_cards
    before = wiz.selected
    wiz.select_disk(wiz.discovery.boot.path)
    assert wiz.selected == before and not wiz.runner.started
    assert not _off_window_problems(app)
    assert not _clipping_problems(app)


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize("long", [False, True])
def test_serial_comparison_markers_wrap_and_leave_controls_visible(size, long):
    from test_serial_comparison import comparison_wizard
    _needs_display()
    serials = ("A" * 240 + "X" + "Z" * 80, "A" * 240 + "Y" + "Z" * 80) if long else ("ABC123XYZ", "ABC124XYZ")
    wiz = comparison_wizard(serials)
    app = TkWizard(wiz)
    try:
        app.root.geometry(f"{size[0]}x{size[1]}+40+40")
        _drive_to(wiz, app, Screen.PICK, size=size)
        for disk in wiz.selectable:
            labels = []
            def visit(widget):
                if isinstance(widget, tk.Label):
                    labels.append(widget)
                for child in widget.winfo_children():
                    visit(child)
            visit(app._pick_cards[disk.path])
            view = wiz.disk_view(disk)
            assert any(str(label.cget('text')).replace('\n', '') == view.marked_id for label in labels)
            assert any(view.comparison_note == str(label.cget('text')) for label in labels)
            for label in labels:
                assert label.winfo_reqwidth() <= label.winfo_width() + 2
                assert label.winfo_reqheight() <= label.winfo_height() + 2
        assert not _off_window_problems(app)
        assert not _clipping_problems(app)
    finally:
        app._teardown()


@pytest.mark.parametrize('size', [WINDOW, MIN_WINDOW])
def test_unsure_disk_keyboard_return_and_reader(ui, size):
    from beamo_wipe import copy as C
    w, app = ui(size=size)
    w.skip_intro()
    w.accept_what()
    w.set_owner(True)
    w.continue_owner()
    w.select_disk(w.selectable[0].path)
    app._draw()
    app.root.update()
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    unsure = next(x for x in descendants(app.root) if isinstance(x, _Button) and x.itemcget(x._label, "text") == C.DISK_HELP_BUTTON)
    unsure.focus_set()
    app.root.update()
    unsure.event_generate('<Return>')
    app.root.update()
    assert w.screen == Screen.DISK_HELP and w.selected is None
    reader = next(x for x in descendants(app.root) if isinstance(x, tk.Text))
    assert C.DISK_HELP_TEXT == reader.get('1.0', 'end-1c')
    assert app.root.focus_get() == reader
    reader.event_generate('<Next>')
    reader.event_generate('<Return>')
    app.root.update()
    assert w.screen == Screen.DISK_HELP and w.selected is None
    for x in descendants(app.root):
        if isinstance(x, _Button) and x.winfo_ismapped():
            assert x.winfo_rooty() + x.winfo_height() <= app.root.winfo_rooty() + size[1]
    reader.event_generate('<Escape>')
    app.root.update()
    assert w.screen == Screen.PICK and w.selected is None
    assert not w.runner.started


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW, (800, 600)])
def test_method_keeps_selected_disk_identity(ui, size):
    wiz, app = ui(size=size)
    _drive_to(wiz, app, Screen.METHOD, size=size)
    selected = wiz.selected
    view = wiz.disk_view(selected)
    text = _label_text(app)
    for value in (view.title, view.capacity, view.id_value, view.connection):
        assert value in text
    app._more_button._command()
    app.root.update()
    assert selected.path in _label_text(app)
    for method in METHODS:
        app._choose_method(method)
        app.root.update()
        assert wiz.selected is selected
        assert view.id_value in _label_text(app)
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.selected is selected


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("enlarged", [False, True])
def test_method_identity_wraps_without_losing_values(ui, missing, enlarged):
    wiz, app = ui(size=(800, 600))
    _drive_to(wiz, app, Screen.METHOD, size=(800, 600))
    wiz.selected = replace(
        wiz.selected,
        model="" if missing else "LONGMODEL" * 18,
        serial="" if missing else "LONGSERIAL" * 18,
        bus="" if missing else "SATA",
        path="/dev/" + "longpath" * 18,
    )
    if enlarged:
        for name, font in vars(app).items():
            if name.startswith("font_"):
                font.configure(size=round(int(font.cget("size")) * 1.5))
    app._show_more = True
    app._draw()
    app.root.update()
    # Soft line breaks may split unbroken hardware identifiers, never truncate.
    packed = "".join(_label_text(app).split())
    view = wiz.disk_view(wiz.selected)
    for value in (view.title, view.capacity, view.id_value, view.connection,
                  view.system_path, *view.notes):
        assert "".join(value.split()) in packed
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    assert app._body_canvas is not None
    app._body_canvas.yview_moveto(1)
    app.root.update()
    assert app._body_canvas.yview()[1] == 1.0

@pytest.mark.parametrize("size", [(800, 600), MIN_WINDOW, WINDOW, (1600, 1000)])
def test_review_timer_is_secondary_and_completion_preserves_focus(ui, size):
    from tkinter import font
    from beamo_wipe import copy as C

    wiz, app = ui(size=size)
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    app.root.update()
    focus = app.root.focus_get()
    assert app._countdown_ring.winfo_width() <= 64
    numeral = font.Font(root=app.root, font=app._countdown_num.cget("font"))
    assert abs(numeral.cget("size")) <= abs(app.font_bold.cget("size"))
    assert "selected disk and method" in C.LAST_LEAD
    assert "never starts erasure" in C.LAST_LEAD
    wiz._erase_until = 0
    app._refresh_last_chance()
    app.root.update()
    assert app.root.focus_get() == focus
    assert wiz.screen == Screen.LAST_CHANCE
    assert not wiz.runner.started
    assert app._countdown_label.cget("text") == C.COUNTDOWN_READY


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_stop_confirmation_is_deliberate_and_fits(ui, monkeypatch, tmp_path, size):
    from beamo_wipe import copy as C
    w, app = ui(size=size)
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(w, "_write_evidence", lambda **kw: None)
    w.runner._clock = lambda: 0
    _drive_to(w, app, Screen.LAST_CHANCE)
    w._erase_until = 0
    w.confirm_erase()
    app._draw()
    app._on_escape()
    app.root.update()
    assert w.screen == Screen.WORKING and w.stop_confirmation is not None
    assert not w.runner.cancelled
    assert _clipping_problems(app) == []
    assert _off_window_problems(app) == []
    assert app.root.focus_get().itemcget(app.root.focus_get()._label, "text") == C.STOP_KEEP
    stale = app._primary._command
    app._on_escape()
    stale()
    assert not w.runner.cancelled and w.stop_confirmation is None
    app._close()
    assert not w.runner.cancelled and w.stop_confirmation is not None
    app._primary._command()
    _wait_transition(w, app)
    assert w.runner.cancelled

@pytest.mark.parametrize("case", RESULT_CASES, ids=[case[0] for case in RESULT_CASES])
@pytest.mark.parametrize("status", ["idle", "saving", "saved", "error"])
def test_done_separates_report_status_at_minimum_size(ui, case, status):
    from beamo_wipe import copy as C
    _, app = ui(size=MIN_WINDOW)
    app.w, _, _ = case_evidence(case)
    app.w.report_status = status
    app._draw()
    app.root.update()
    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)
    labels = {widget.cget("text"): widget for widget in walk(app.root) if isinstance(widget, tk.Label)}
    # #95: the specific outcome is the main heading; the generic label is gone.
    message = app.w.result_view.message
    assert message in labels
    assert "Erase status" not in labels
    assert C.REPORT_STATUS_TITLE in labels
    assert app.w.report_view.headline in labels
    assert labels[message].winfo_rooty() < labels[C.REPORT_STATUS_TITLE].winfo_rooty()
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)

@pytest.mark.parametrize("evidence_failed", [False, True])
def test_erase_another_report_guard_and_layout(ui, evidence_failed):
    from beamo_wipe import copy as C
    from test_result_presentations import CASES, case_evidence
    w, app = ui(size=MIN_WINDOW)
    completed, evidence, _ = case_evidence(CASES[0])
    w.preview = False
    w.screen = Screen.DONE
    w.selected = completed.selected
    w.wipe_result = completed.wipe_result
    w.evidence = evidence
    if evidence_failed:
        w.evidence_error = "Temporary storage is not writable."
    app._draw()
    app.root.update()
    assert not _off_window_problems(app)
    assert not _clipping_problems(app)
    button = _button_named(app, C.BTN_ERASE_ANOTHER)
    assert button.winfo_ismapped()
    button._command()
    assert w.screen == Screen.SHUTDOWN_CONFIRM
    app.root.update()
    assert _button_named(app, C.SHUTDOWN_KEEP).winfo_ismapped()
    _button_named(app, C.SHUTDOWN_KEEP)._command()
    assert w.screen == Screen.DONE
    _button_named(app, C.BTN_ERASE_ANOTHER)._command()
    _button_named(app, C.ANOTHER_DISCARD)._command()
    assert w.wants_new_session and not w.wants_shutdown


def test_cursor_roles_arrow_content_hand2_actions_xterm_text(ui):
    """Backlog #85: ordinary content resolves to arrow, never the X cursor.

    Enabled actions keep hand2, disabled buttons keep arrow, text entry
    and readers keep the xterm I-beam. Needs a display; skips headless.
    """
    from beamo_wipe import copy as C
    from test_arrow_cursor import effective_cursor

    wiz, app = ui()
    assert app.root.cget("cursor") == "arrow"

    def descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from descendants(child)

    _drive_to(wiz, app, Screen.PICK)
    labels = [w for w in descendants(app.root) if w.winfo_class() == "Label"]
    assert labels
    assert all(w.cget("cursor") == "" for w in labels)
    assert all(effective_cursor(w) in {"arrow", "hand2"} for w in labels)
    content = [w for w in labels if effective_cursor(w) == "arrow"]
    assert content, "ordinary copy must inherit the root arrow cursor"
    frames = [w for w in descendants(app.root) if w.winfo_class() == "Frame"]
    assert frames
    assert all(effective_cursor(w) in {"arrow", "hand2"} for w in frames)
    assert any(effective_cursor(w) == "arrow" for w in frames)
    assert _button_named(app, C.BTN_MORE).cget("cursor") == "hand2"
    frame = tk.Frame(app.root)
    disabled = _Button(
        frame, text="Off", command=lambda: None, font=app.font_btn, enabled=False
    )
    assert disabled.cget("cursor") == "arrow"
    disabled.set_enabled(True)
    assert disabled.cget("cursor") == "hand2"
    assert app._reader(frame, height=2).cget("cursor") == "xterm"
    _drive_to(wiz, app, Screen.CONFIRM)
    entries = [w for w in descendants(app.root) if w.winfo_class() == "Entry"]
    assert entries
    assert all(e.cget("cursor") == "xterm" for e in entries)


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_working_sounds_toggle_and_hear(ui, size, monkeypatch):
    from beamo_wipe import copy as C
    from beamo_wipe import sound as sound_module

    monkeypatch.setattr(
        sound_module, "_run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned audio")),
    )
    monkeypatch.setattr(
        sound_module, "_popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned audio")),
    )
    wiz, app = ui(size=size)
    wiz.screen = Screen.WORKING
    wiz.selected = wiz.selectable[0]
    app._draw()
    app.root.update_idletasks()
    toggle = _button_named(app, C.SOUND_TOGGLE_OFF)
    toggle._command()
    assert wiz.sounds_enabled is True
    assert wiz.sound_message == C.SOUND_TOGGLE_ON
    _button_named(app, C.SOUND_TOGGLE_ON)
    app.root.update_idletasks()
    hear = _button_named(app, C.SOUND_HEAR)
    hear._command()
    assert wiz.sound_message == C.SOUND_OUTCOME_OFF_LIVE


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_done_auto_plays_once_and_offers_replay(ui, size):
    from unittest.mock import patch

    from beamo_wipe import copy as C
    from beamo_wipe import sound as sound_module
    from beamo_wipe.models import WipeResult

    wiz, app = ui(size=size)
    wiz.preview = False
    wiz.screen = Screen.DONE
    wiz.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    wiz.set_sounds_enabled(True)
    calls = []
    with patch.object(
        sound_module, "play_outcome",
        lambda kind: calls.append(kind) or sound_module.SoundResult(True, ""),
    ):
        app._draw()
        app.root.update_idletasks()
        message_before = wiz.result_view.message
        app._draw()
        app.root.update_idletasks()
    assert calls == [sound_module.KIND_ATTENTION]
    assert wiz.result_view.message == message_before
    _button_named(app, C.SOUND_TOGGLE_ON)
    replay = _button_named(app, C.SOUND_HEAR_AGAIN)
    with patch.object(
        sound_module, "play_test",
        lambda kind: calls.append(("hear", kind))
        or sound_module.SoundResult(True, "played"),
    ):
        replay._command()
    assert calls[-1] == ("hear", sound_module.KIND_ATTENTION)


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize("code", ["verified", "unverified", "cancelled", "engine_failed"])
def test_done_heading_is_outcome_message(ui, size, code):
    import tkinter.font as tkfont

    from beamo_wipe import copy as C
    from beamo_wipe.outcomes import VIEWS

    case = next(c for c in RESULT_CASES if c[0] == code)
    _, app = ui(size=size)
    app.w, _, _ = case_evidence(case)
    app._draw()
    app.root.update()
    labels = {w.cget("text"): w for w in descendants(app.root) if isinstance(w, tk.Label)}
    message = VIEWS[code].message
    assert app.w.result_view.message == message
    assert message in labels
    assert "Erase status" not in labels
    font_size = tkfont.nametofont(labels[message].cget("font")).actual("size")
    assert font_size == app.font_h.actual("size")
    assert labels[message].winfo_rooty() < labels[C.REPORT_STATUS_TITLE].winfo_rooty()
    assert not _clipping_problems(app)


def test_done_heading_long_german_text_no_clip(ui):
    from beamo_wipe import lang
    from beamo_wipe import outcomes

    try:
        lang.set_language("de")
        views = outcomes.VIEWS
        code = max(views, key=lambda c: len(views[c].message))
        case = next(c for c in RESULT_CASES if c[0] == code)
        _, app = ui(size=MIN_WINDOW)
        app.w, _, _ = case_evidence(case)
        app.w.set_language("de")
        app._draw()
        app.root.update()
        labels = {w.cget("text") for w in descendants(app.root) if isinstance(w, tk.Label)}
        assert views[code].message in labels
        assert not _clipping_problems(app)
    finally:
        lang.set_language("en")


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize(
    "code,shown",
    [("verified", True), ("engine_failed", True), ("cancelled", True), ("open_failed", False)],
)
def test_done_post_erase_boot_note(ui, size, code, shown):
    from beamo_wipe import copy as C

    case = next(c for c in RESULT_CASES if c[0] == code)
    _, app = ui(size=size)
    app.w, _, _ = case_evidence(case)
    app._draw()
    app.root.update()
    labels = {w.cget("text"): w for w in descendants(app.root) if isinstance(w, tk.Label)}
    assert (C.POST_ERASE_BOOT in labels) == shown
    if shown:
        message = app.w.result_view.message
        assert labels[message].winfo_rooty() < labels[C.POST_ERASE_BOOT].winfo_rooty()
        assert labels[C.POST_ERASE_BOOT].winfo_rooty() < labels[C.REPORT_STATUS_TITLE].winfo_rooty()
    assert not _clipping_problems(app)


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_shutdown_confirm_media_steps(ui, size):
    from beamo_wipe import copy as C

    case = next(c for c in RESULT_CASES if c[0] == "verified")
    _, app = ui(size=size)
    app.w, _, _ = case_evidence(case)
    app.w.report_wanted = True
    app.w.shutdown()
    assert app.w.screen == Screen.SHUTDOWN_CONFIRM
    app._draw()
    app.root.update()
    labels = {w.cget("text"): w for w in descendants(app.root) if isinstance(w, tk.Label)}
    assert C.SHUTDOWN_LOSS in labels
    assert C.MEDIA_STEPS_TITLE in labels
    assert app.w.exit_media_steps in labels
    assert (
        labels[C.SHUTDOWN_LOSS].winfo_rooty()
        < labels[C.MEDIA_STEPS_TITLE].winfo_rooty()
        < labels[app.w.exit_media_steps].winfo_rooty()
    )
    assert not _clipping_problems(app)


def test_shutdown_confirm_media_steps_erase_another(ui):
    from beamo_wipe import copy as C

    case = next(c for c in RESULT_CASES if c[0] == "verified")
    _, app = ui(size=MIN_WINDOW)
    app.w, _, _ = case_evidence(case)
    app.w.report_wanted = True
    app.w.shutdown()
    app.w.keep_report_session()
    assert app.w.can_erase_another
    app.w.erase_another_disk()
    assert app.w.screen == Screen.SHUTDOWN_CONFIRM
    app._draw()
    app.root.update()
    labels = {w.cget("text") for w in descendants(app.root) if isinstance(w, tk.Label)}
    assert C.MEDIA_STEP_ANOTHER in app.w.exit_media_steps
    assert app.w.exit_media_steps in labels
    assert not _clipping_problems(app)


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_what_report_media_notice_above_power(ui, size):
    from beamo_wipe import copy as C

    wiz, app = ui(size=size)
    wiz.preview = False
    wiz.skip_intro()
    assert wiz.screen == Screen.WHAT
    app._draw()
    app.root.update()
    labels = {w.cget("text"): w for w in descendants(app.root) if isinstance(w, tk.Label)}
    assert C.REPORT_MEDIA_WHAT in labels
    assert labels[C.REPORT_MEDIA_WHAT].winfo_rooty() < labels[C.POWER_REMINDER].winfo_rooty()
    assert not _clipping_problems(app)


@pytest.mark.parametrize("wanted", [True, False])
def test_pick_report_media_notice_follows_preference(ui, wanted):
    from beamo_wipe import copy as C

    wiz, app = ui(size=MIN_WINDOW)
    wiz.preview = False
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    wiz.report_wanted = wanted
    app._draw()
    app.root.update()
    labels = {w.cget("text") for w in descendants(app.root) if isinstance(w, tk.Label)}
    assert (C.REPORT_MEDIA_WANTED in labels) == wanted
    assert not _clipping_problems(app)


@pytest.mark.parametrize(
    "status,message,marked,unmarked",
    [
        ("idle", "", ("1. ", "(now)"), ()),
        ("saving", None, ("(done)", "(now)"), ()),
        ("saved", None, ("(done)", "(now)"), ()),
        ("error", "Report USB was removed.", ("Save report to USB again",), ("Insert the report USB",)),
    ],
)
def test_done_export_stages_per_state(ui, tmp_path, status, message, marked, unmarked):
    from beamo_wipe import copy as C
    from test_usb_report_workflow import _done_wizard, _success_receipt

    _, app = ui(size=MIN_WINDOW)
    wiz = _done_wizard(_success_receipt, tmp_path)
    if status == "saved":
        wiz.save_report_to_usb()
    elif status == "saving":
        from beamo_wipe.wizard import REPORT_SAVING

        wiz.report_status = "saving"
        wiz.report_message = REPORT_SAVING
    elif status == "error":
        wiz.report_status = "error"
        wiz.report_message = message
    app.w = wiz
    app._draw()
    app.root.update()
    labels = {w.cget("text") for w in descendants(app.root) if isinstance(w, tk.Label)}
    blob = "\n".join(labels)
    for index, stage in enumerate(C.EXPORT_STAGES, 1):
        assert (f"{index}. {stage}" in blob) == (status != "error")
    for needle in marked:
        assert needle in blob
    for needle in unmarked:
        assert needle not in blob
    assert not _clipping_problems(app)


def test_diagnostic_rejection_shows_next_step(ui):
    from beamo_wipe import copy as C
    from beamo_wipe import support_export as E
    from beamo_wipe.demo import make_demo_wizard

    _, app = ui(size=MIN_WINDOW)
    wiz = make_demo_wizard()
    wiz.screen = Screen.DIAGNOSTIC
    wiz.diagnostic_message = E.USB_FAT32_ONLY
    app.w = wiz
    app._draw()
    app.root.update()
    labels = {w.cget("text") for w in descendants(app.root) if isinstance(w, tk.Label)}
    assert E.USB_FAT32_ONLY in labels
    assert E.NEXT_DIFFERENT_STICK in labels
    assert C.SUPPORT_CODE_LABEL in labels
    assert C.SUPPORT_BUILD_LABEL in labels
    assert not _clipping_problems(app)
