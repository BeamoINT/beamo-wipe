# SPDX-License-Identifier: GPL-3.0-or-later
"""Runtime tests for the real Tk wizard on fake disks.

Nothing is erased: every test uses the demo wizard (DryRunRunner). These
tests need a display; on a headless host they skip. They exist to catch
layout regressions (clipped text, buttons pushed off the window at the
minimum size) and broken keyboard flows that source inspection cannot see.
"""

import time
from types import SimpleNamespace

import pytest
from test_result_presentations import CASES as RESULT_CASES, case_evidence

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.methods import METHODS
from beamo_wipe.support_export import ExportReceipt
try:
    import tkinter as tk
    from beamo_wipe.ui.tk_wizard import TkWizard, _Button
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
MIN_WINDOW = (1024, 740)  # TkWizard.minsize; oldest laptops the USB targets


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


def _clipping_problems(app) -> list:
    """Labels/entries asking for more space than the layout gave them."""
    app.root.update_idletasks()
    problems = []

    def visit(w):
        try:
            if not w.winfo_ismapped():
                return
        except tk.TclError:
            return
        cls = w.winfo_class()
        if cls in ("Label", "Entry") and not _in_canvas(w):
            if w.winfo_reqwidth() > w.winfo_width() + 2:
                problems.append(f"h-clip {cls} {str(w.cget('text'))[:40]!r}")
            if w.winfo_reqheight() > w.winfo_height() + 2:
                problems.append(f"v-clip {cls} {str(w.cget('text'))[:40]!r}")
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
        wiz.skip_splash()
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


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
@pytest.mark.parametrize(
    "screen",
    [Screen.WHAT, Screen.OWNER, Screen.PICK, Screen.CONFIRM, Screen.METHOD,
     Screen.ADVANCED, Screen.LAST_CHANCE],
)
def test_screen_fits_without_clipping(ui, screen, size):
    wiz, app = ui(size=size)
    _drive_to(wiz, app, screen, size=size)
    assert app.w.screen == screen
    assert _clipping_problems(app) == []
    assert _off_window_problems(app) == []


@pytest.mark.parametrize("size", [WINDOW, MIN_WINDOW])
def test_status_screens_fit(ui, size):
    for scenario, screen in (("empty", Screen.PICK_EMPTY), ("blocked", Screen.PICK_BLOCKED)):
        wiz, app = ui(scenario=scenario, size=size)
        wiz.skip_splash()
        wiz.accept_what()
        wiz.set_owner(True)
        wiz.continue_owner()
        app._draw()
        app.root.update_idletasks()
        app.root.update()
        assert app.w.screen == screen
        assert _clipping_problems(app) == []
        assert _off_window_problems(app) == []


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
    wiz.skip_splash()
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
    wiz.skip_splash()
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
    wiz.skip_splash()
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
        return ExportReceipt(
            True,
            True,
            "saved_verified_unmounted",
            evidence_sha256=kwargs["expected_evidence_sha256"],
            session_name="report-0123456789abcdef01234567",
        )

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
    assert y0 >= top - 0.02, "selected card scrolled above the view"
    assert y1 <= bottom + 0.02, "selected card scrolled below the view"


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
    from beamo_wipe.ui.tk_wizard import OK, WARN, DANGER
    tone = {"ok": OK, "warn": WARN, "danger": DANGER}[wiz.result_view.tone]
    assert tone in colors
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)


@pytest.mark.parametrize("screen", [Screen.PICK, Screen.PICK_EMPTY, Screen.PICK_BLOCKED, Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE])
def test_graphical_refresh_restarts_full_authorization(ui, screen):
    from types import SimpleNamespace
    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz.screen = screen
    app._draw()
    app._on_key(SimpleNamespace(keysym="F5", char=""))
    assert wiz.screen == Screen.WHAT
    assert wiz.selected is None and not wiz.owner_ok and not wiz.confirm_input
    assert not wiz.runner.started
    assert not _clipping_problems(app)


@pytest.mark.parametrize("fresh_ok", [True, False])
def test_screen_reader_switch_clears_authorization(ui, monkeypatch, fresh_ok):
    wiz, app = ui()
    monkeypatch.setattr("beamo_wipe.ui.tk_wizard.sys.platform", "linux")
    wiz.skip_splash()
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
    checkbox = next(w for w in widgets(app.root) if isinstance(w, tk.Checkbutton))
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
                  and v.itemcget(v._label, "text") == "Cancel erase")
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
