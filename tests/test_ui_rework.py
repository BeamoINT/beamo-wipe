# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendered regression checks for wayfinding and review on small screens.

All operations use fake disks and DryRunRunner.
"""
from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.ui.tk_wizard import _Button
from test_design_runtime import descendants
from test_tk_runtime import ui, _drive_to, _clipping_problems, _off_window_problems  # noqa: F401


@pytest.mark.parametrize("screen", [Screen.PICK, Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE])
def test_canvas_controls_are_fully_visible_at_minimum_size(ui, screen):  # noqa: F811
    wiz, app = ui(size=(1024, 740))
    _drive_to(wiz, app, screen)
    for _ in range(8):
        app.root.update()
    for widget in descendants(app.root):
        if isinstance(widget, _Button):
            title = widget.itemcget(widget._label, "text")
            assert widget.winfo_ismapped(), title
            assert widget.winfo_height() >= widget.winfo_reqheight(), title
            x0, y0, x1, y1 = widget.bbox(widget._label)
            assert 0 <= x0 < x1 <= widget.winfo_width(), title
            assert 0 <= y0 < y1 <= widget.winfo_height(), title


def test_review_keeps_full_long_disk_identity_and_safe_default(ui):  # noqa: F811
    wiz, app = ui(size=(1024, 740))
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    wiz.selected = replace(wiz.selected, model="Long model " * 10, serial="ABCD1234" * 16)
    app._draw()
    for _ in range(8):
        app.root.update()
    labels = [w for w in descendants(app.root) if w.winfo_class() == "Label"]
    for expected in (C.SELECTED_DISK, wiz.selected.display_name, wiz.selected.serial,
                     wiz.method_summary, C.REVIEW_CHECK):
        matches = [w for w in labels if w.cget("text") == expected]
        assert len(matches) == 1
        label = matches[0]
        assert label.winfo_ismapped()
        assert label.winfo_reqheight() <= label.winfo_height() + 2
        assert label.winfo_reqwidth() <= label.winfo_width() + 2
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    focus = app.root.focus_get()
    assert isinstance(focus, _Button)
    assert focus.itemcget(focus._label, "text") == C.BTN_BACK
    assert not wiz.erase_enabled


def test_header_wayfinding_fits_and_cannot_navigate(ui):  # noqa: F811
    wiz, app = ui(size=(1024, 740))
    _drive_to(wiz, app, Screen.CONFIRM)
    wiz.set_confirm_input("")
    app._confirm_var.set("")
    header = app._header
    labels = {header.itemcget(item, "text"): item for item in header.find_all()
              if header.type(item) == "text"}
    for text in (*C.JOURNEY_LABELS, "Step 4 of 8"):
        item = labels[text]
        x0, y0, x1, y1 = header.bbox(item)
        assert 0 <= x0 < x1 <= header.winfo_width()
        assert 0 <= y0 < y1 <= header.winfo_height()
        header.event_generate("<Button-1>", x=int((x0 + x1) / 2), y=int((y0 + y1) / 2))
        app.root.update()
        assert wiz.screen == Screen.CONFIRM
        assert not wiz.token_ok
        assert wiz.confirm_input == ""
