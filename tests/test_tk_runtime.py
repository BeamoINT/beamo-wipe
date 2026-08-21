# SPDX-License-Identifier: GPL-3.0-or-later
"""Runtime tests for the real Tk wizard on fake disks.

Nothing is erased: every test uses the demo wizard (DryRunRunner). These
tests need a display; on a headless host they skip. They exist to catch
layout regressions (clipped text, buttons pushed off the window at the
minimum size) and broken keyboard flows that source inspection cannot see.
"""

import time

import pytest

tk = pytest.importorskip("tkinter")

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui.tk_wizard import TkWizard

WINDOW = (1280, 820)
MIN_WINDOW = (1024, 740)  # TkWizard.minsize; oldest laptops the USB targets


@pytest.fixture
def ui():
    created = []

    def build(scenario="happy", fail=False, size=WINDOW):
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


def test_done_screen_fits(ui):
    wiz, app = ui()
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
    assert _clipping_problems(app) == []
    assert _off_window_problems(app) == []


def test_keyboard_only_flow_reaches_working(ui):
    """No mouse: any-key, Enter, Space, Up/Down, digits, Enter all the way."""
    wiz, app = ui()
    root = app.root

    def key(keysym):
        (root.focus_get() or root).event_generate("<KeyPress>", keysym=keysym)
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
    key("Return")
    assert wiz.screen == Screen.LAST_CHANCE, "Enter during countdown must not erase"
    # Countdown over: the very same Enter key now starts the (dry-run) erase.
    wiz._erase_until = 0.0
    wiz.tick()
    app._draw()
    root.update()
    assert wiz.erase_enabled
    key("Return")
    assert wiz.screen == Screen.WORKING


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
