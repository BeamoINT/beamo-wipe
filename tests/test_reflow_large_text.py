# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #80: enlarged type reflows cards, warnings, footers, and review."""

from __future__ import annotations

import tkinter as tk

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.ui.tk_wizard import _Box
from test_result_presentations import CASES, case_evidence
from test_tk_runtime import MIN_WINDOW, _clipping_problems, _drive_to, _off_window_problems, ui  # noqa: F401

SCREENS = (
    Screen.KEYBOARD,
    Screen.WHAT,
    Screen.PICK,
    Screen.CONFIRM,
    Screen.METHOD,
    Screen.LAST_CHANCE,
    Screen.WORKING,
    Screen.DONE,
    Screen.REPORT_HELP,
)


def _card_wrap_problems(app) -> list[str]:
    """Labels inside rounded cards whose wrap is wider than the parent."""
    app.root.update_idletasks()
    problems: list[str] = []

    def visit(node):
        try:
            if not node.winfo_ismapped():
                return
        except tk.TclError:
            return
        if isinstance(node, _Box):
            def labels(inner):
                try:
                    if inner.winfo_class() == "Label" and inner.winfo_ismapped():
                        wrap = int(float(str(inner.cget("wraplength") or 0)))
                        parent_w = inner.master.winfo_width()
                        if wrap > parent_w + 16 and parent_w > 40:
                            problems.append(
                                f"wrap {wrap}>{parent_w} {str(inner.cget('text'))[:32]!r}"
                            )
                except tk.TclError:
                    return
                for child in inner.winfo_children():
                    labels(child)

            labels(node.inner)
        for child in node.winfo_children():
            visit(child)

    visit(app.root)
    return problems


def _show(wiz, app, screen: Screen) -> None:
    if screen == Screen.REPORT_HELP:
        _drive_to(wiz, app, Screen.WHAT)
        wiz.open_report_help()
        app._draw()
        app.root.update()
        return
    if screen == Screen.WORKING:
        _drive_to(wiz, app, Screen.LAST_CHANCE)
        wiz.screen = Screen.WORKING
        app._draw()
        app.root.update()
        return
    if screen == Screen.DONE:
        done, ev, _ = case_evidence(CASES[0])
        wiz.screen = Screen.DONE
        wiz.wipe_result = done.wipe_result
        wiz.evidence = ev
        wiz.selected = done.selected
        wiz.preview = False
        app._draw()
        app.root.update()
        return
    if screen == Screen.KEYBOARD:
        wiz.skip_splash()
        app._draw()
        app.root.update()
        return
    _drive_to(wiz, app, screen)


@pytest.mark.parametrize("size", [(800, 600), MIN_WINDOW])
@pytest.mark.parametrize("screen", SCREENS)
def test_enlarged_type_reflows_without_clipping_or_lost_actions(ui, size, screen):  # noqa: F811
    """Would fail when wraplength stayed at lay.wrap inside fixed cards."""
    wiz, app = ui(size=size)
    assert wiz.set_text_size("extra")
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    _show(wiz, app, screen)
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app._sync_layout()
    app._draw()
    app.root.update_idletasks()
    app.root.update()
    assert app.lay.text_size == "extra"
    assert app.lay.type_scale == 1.35
    assert app.lay.stack_review
    if screen == Screen.LAST_CHANCE:
        assert app._ring_px >= 64
    shown = []

    def collect(node):
        try:
            if node.winfo_class() == "Label":
                shown.append(str(node.cget("text")))
        except tk.TclError:
            return
        for child in node.winfo_children():
            collect(child)

    collect(app.root)
    blob = "\n".join(shown)
    if screen in {Screen.CONFIRM, Screen.LAST_CHANCE, Screen.METHOD} and wiz.selected:
        assert wiz.selected.serial in blob
    if screen == Screen.LAST_CHANCE:
        assert "cannot get" in blob.lower() or C.BTN_ERASE in blob
    buttons = [w for w in app.root.winfo_children()]
    assert buttons
    if app._body_canvas is None and screen not in {
        Screen.PICK, Screen.REPORT_HELP, Screen.DISK_HELP, Screen.LIMITS,
    }:
        assert _clipping_problems(app) == []
    assert _card_wrap_problems(app) == []
    # Footer actions stay on the window even when the body scrolls.
    if app._primary is not None and app._primary.winfo_ismapped():
        y = app._primary.winfo_rooty() - app.root.winfo_rooty()
        assert y + app._primary.winfo_height() <= app.root.winfo_height() + 2


def test_enlarged_type_uses_one_comparison_column():
    import inspect
    from beamo_wipe.ui import tk_wizard as tkui
    from beamo_wipe.ui.layout import layout_for

    src = inspect.getsource(tkui.TkWizard._comparison)
    assert "type_scale" in src
    assert "columns = 1" in src
    assert layout_for(1024, 740, "extra").stack_review
    assert not layout_for(1024, 740, "standard").stack_review
