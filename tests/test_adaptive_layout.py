# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendered geometry for every wizard screen at supported sizes.

Fake devices and DryRunRunner only. Source-string checks are not enough:
each case maps a real Tk window and asserts identity, warnings, and
actions stay reachable without truncation.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.ui.layout import DEFAULT_SIZE, LARGE_SIZE, MIN_SIZE, NETBOOK_SIZE, SUPPORTED_SIZE
from beamo_wipe.ui.tk_wizard import _Button
from test_result_presentations import CASES, case_evidence
from test_tk_runtime import _clipping_problems, _drive_to, _off_window_problems, ui  # noqa: F401

SIZES = (MIN_SIZE, NETBOOK_SIZE, SUPPORTED_SIZE, DEFAULT_SIZE, LARGE_SIZE)

WALK_SCREENS = (
    Screen.WHAT,
    Screen.OWNER,
    Screen.PICK,
    Screen.CONFIRM,
    Screen.METHOD,
    Screen.ADVANCED,
    Screen.LAST_CHANCE,
    Screen.LIMITS,
    Screen.REPORT_HELP,
)


def _texts(widget) -> str:
    import tkinter as tk

    chunks = []

    def visit(node):
        try:
            cls = node.winfo_class()
            if cls == "Label":
                chunks.append(str(node.cget("text")))
            if cls == "Label":
                wrap = str(node.cget("wraplength") or "0")
                if wrap not in {"", "0"}:
                    assert int(float(wrap)) <= node.winfo_toplevel().winfo_width() + 8
            if isinstance(node, tk.Canvas):
                for item in node.find_all():
                    if node.type(item) == "text":
                        chunks.append(str(node.itemcget(item, "text")))
        except tk.TclError:
            return
        for child in node.winfo_children():
            visit(child)

    visit(widget)
    return "\n".join(chunks)


def _buttons(app):
    found = []

    def visit(node):
        if isinstance(node, _Button):
            found.append(node)
        for child in node.winfo_children():
            visit(child)

    visit(app.root)
    return found


def _assert_actions_on_window(app):
    app.root.update_idletasks()
    ww = app.root.winfo_width()
    wh = app.root.winfo_height()
    buttons = [b for b in _buttons(app) if b.winfo_ismapped()]
    assert buttons, "no mapped actions"
    for btn in buttons:
        x = btn.winfo_rootx() - app.root.winfo_rootx()
        y = btn.winfo_rooty() - app.root.winfo_rooty()
        assert y >= -2
        assert y + btn.winfo_height() <= wh + 2
        assert x + btn.winfo_width() <= ww + 2
        assert btn.winfo_height() >= 28
    # Body content may scroll on short windows; widgets inside the body
    # canvas are reachable by PageDown. Footer actions must stay on-window.
    if app._body_canvas is None:
        assert _off_window_problems(app) == []
        assert _clipping_problems(app) == []


def _show(wiz, app, screen):
    if screen == Screen.SPLASH:
        app._draw()
        app.root.update()
        return
    if screen == Screen.LIMITS:
        _drive_to(wiz, app, Screen.METHOD)
        wiz.open_limits()
        app._draw()
        app.root.update()
        return
    if screen == Screen.REPORT_HELP:
        _drive_to(wiz, app, Screen.WHAT)
        wiz.open_report_help()
        app._draw()
        app.root.update()
        return
    if screen == Screen.ADVANCED:
        _drive_to(wiz, app, Screen.METHOD)
        wiz.open_advanced()
        app._draw()
        app.root.update()
        return
    _drive_to(wiz, app, screen)


@pytest.mark.parametrize("size", SIZES)
def test_every_walkable_screen_keeps_actions_and_copy(ui, size):  # noqa: F811
    for screen in WALK_SCREENS:
        wiz, app = ui(size=size)
        app.root.minsize(*MIN_SIZE)
        app.root.geometry(f"{size[0]}x{size[1]}+40+40")
        app.root.update_idletasks()
        app.root.update()
        _show(wiz, app, screen)
        app.root.geometry(f"{size[0]}x{size[1]}+40+40")
        app.root.update_idletasks()
        app.root.update()
        assert wiz.screen == screen
        shown = _texts(app.root)
        _assert_actions_on_window(app)
        if screen == Screen.WHAT:
            assert C.POWER_REMINDER in shown
            assert "copies you need" in shown
        if screen in {Screen.CONFIRM, Screen.LAST_CHANCE} and wiz.selected is not None:
            assert wiz.selected.display_name in shown
            assert wiz.selected.serial in shown
            assert "cannot get" in shown.lower() or wiz.prepare_text() in shown
        if screen == Screen.LAST_CHANCE:
            labels = [b.itemcget(b._label, "text") for b in _buttons(app)]
            assert C.BTN_ERASE in labels
            assert C.BTN_BACK in labels


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("scenario,screen", [("empty", Screen.PICK_EMPTY), ("blocked", Screen.PICK_BLOCKED)])
def test_empty_and_blocked_keep_shutdown(ui, size, scenario, screen):  # noqa: F811
    wiz, app = ui(scenario=scenario, size=size)
    app.root.minsize(*MIN_SIZE)
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    app._draw()
    app.root.update()
    assert wiz.screen == screen
    _assert_actions_on_window(app)
    shown = _texts(app.root)
    assert C.TITLE_EMPTY in shown or C.TITLE_BLOCKED in shown or "cannot tell" in shown.lower() or "no disk" in shown.lower()


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("busy", [Screen.CHECKING, Screen.STOPPING, Screen.REFRESHING, Screen.WORKING])
def test_busy_states_keep_identity_or_status(ui, size, busy):  # noqa: F811
    wiz, app = ui(size=size)
    app.root.minsize(*MIN_SIZE)
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz.selected = wiz.selectable[0]
    wiz.screen = busy
    app._draw()
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app.root.update()
    shown = _texts(app.root)
    if busy == Screen.WORKING:
        assert wiz.selected.display_name in shown
        assert "Cancel erase" in shown
        _assert_actions_on_window(app)
    else:
        assert "Checking" in shown or "Stopping" in shown or "cleared" in shown.lower()


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("case", [CASES[0], CASES[1], CASES[6], CASES[8]], ids=["verified", "unverified", "cancelled", "verification_failed"])
def test_result_states_keep_outcome_and_actions(ui, size, case):  # noqa: F811
    wiz, _, _ = case_evidence(case)
    _, app = ui(size=size)
    app.w = wiz
    app.root.minsize(*MIN_SIZE)
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app._draw()
    app.root.update()
    shown = _texts(app.root)
    assert wiz.result_view.message in shown
    assert wiz.selected.display_name in shown
    _assert_actions_on_window(app)


@pytest.mark.parametrize("size", SIZES)
def test_shutdown_dialog_keeps_keep_session_default(ui, size):  # noqa: F811
    wiz, app = ui(size=size)
    app.root.minsize(*MIN_SIZE)
    _drive_to(wiz, app, Screen.WHAT)
    wiz.preview = False
    wiz.report_wanted = True
    wiz.shutdown()
    app._draw()
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app.root.update()
    assert wiz.screen == Screen.SHUTDOWN_CONFIRM
    shown = _texts(app.root)
    assert C.SHUTDOWN_KEEP in shown or C.SHUTDOWN_TITLE in shown
    labels = [b.itemcget(b._label, "text") for b in _buttons(app)]
    assert C.SHUTDOWN_KEEP in labels
    _assert_actions_on_window(app)
    if app._primary is not None:
        app._primary.focus_set()
        app.root.update()
    focus = app.root.focus_get()
    assert isinstance(focus, _Button)
    assert focus.itemcget(focus._label, "text") == C.SHUTDOWN_KEEP


@pytest.mark.parametrize("size", SIZES)
def test_long_unicode_identity_wraps_without_ellipsis(ui, size):  # noqa: F811
    wiz, app = ui(size=size)
    app.root.minsize(*MIN_SIZE)
    _drive_to(wiz, app, Screen.CONFIRM)
    wiz.selected = replace(
        wiz.selected,
        model="삼성 " + ("很长" * 40),
        serial="시리얼-ΑΒΓΔ-" + ("A" * 48),
    )
    app._draw()
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app.root.update()
    shown = _texts(app.root)
    assert "삼성" in shown
    assert "시리얼" in shown
    assert "…" not in shown and "..." not in shown
    _assert_actions_on_window(app)


def test_large_window_uses_larger_type_than_compact(ui):  # noqa: F811
    _, compact = ui(size=MIN_SIZE)
    compact.root.minsize(*MIN_SIZE)
    compact.root.geometry("800x600+40+40")
    compact.root.update()
    compact._draw()
    _, large = ui(size=LARGE_SIZE)
    large.root.geometry("1600x1000+40+40")
    large.root.update()
    large._draw()
    assert abs(int(str(compact.font_h.cget("size")))) < abs(int(str(large.font_h.cget("size"))))
    assert compact.lay.scale < large.lay.scale
    assert large.lay.scale <= 1.2
