# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #110: layout checks must see labels inside canvas-hosted cards.

The 2026-09-08 native probe clipped a 1,485 px serial inside an 840 px
device card. Cards are Canvas windows, and ``_clipping_problems`` used to
skip that tree. Fake disks and DryRunRunner only.
"""

from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from beamo_wipe import copy as C
from beamo_wipe import inventory
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui.layout import (
    DEFAULT_SIZE,
    LARGE_SIZE,
    MIN_SIZE,
    NETBOOK_SIZE,
    SUPPORTED_SIZE,
)
from beamo_wipe.ui.tk_wizard import (
    INK,
    TkWizard,
    _Button,
    _CheckRow,
    _soft_break_tokens,
)
from test_adaptive_layout import _assert_actions_on_window, _texts
from test_identity_soft_break import EVIDENCE_MODEL, EVIDENCE_SERIAL
from test_result_presentations import CASES, case_evidence
from test_tk_runtime import (
    _clipping_problems,
    _drive_to,
    _in_canvas,
    _long_identity_app,
    _needs_display,
    descendants,
    ui,  # noqa: F401
)

try:
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError:
    pytest.skip("tkinter not available", allow_module_level=True)

SIZES = (MIN_SIZE, NETBOOK_SIZE, SUPPORTED_SIZE, DEFAULT_SIZE, LARGE_SIZE)
CARD_PX = 840
SERIAL_PX = 1485


def _plain_app(root):
    return SimpleNamespace(root=root)


def _font_for_serial_px(root, min_px=SERIAL_PX):
    font = tkfont.Font(root, family="DejaVu Sans Mono", size=12)
    size = 12
    while font.measure(EVIDENCE_SERIAL) < min_px and size < 80:
        size += 1
        font.configure(size=size)
    return font


def _unwrapped_serial_card(root, font, width=CARD_PX):
    canvas = tk.Canvas(root, width=width, height=120, bg="white", highlightthickness=0)
    canvas.pack()
    inner = tk.Frame(canvas, bg="white")
    canvas.create_window((0, 0), window=inner, anchor="nw", width=width)
    label = tk.Label(inner, text=EVIDENCE_SERIAL, font=font, bg="white", anchor="w")
    label.pack(fill=tk.X)
    root.update_idletasks()
    root.update()
    return label


def _inject_evidence_disk(wiz):
    target = sorted(wiz.selectable, key=lambda d: d.path)[0]
    disks, selectable = [], []
    for disk in wiz.discovery.disks:
        if disk.path == target.path:
            disk = replace(disk, model=EVIDENCE_MODEL, serial=EVIDENCE_SERIAL)
        disks.append(disk)
        if disk in wiz.discovery.selectable or disk.path == target.path:
            if not disk.is_boot:
                selectable.append(disk)
    wiz.discovery = replace(
        wiz.discovery, disks=tuple(disks), selectable=tuple(selectable)
    )
    return target.path


def _grow_identity_fonts(app, text, min_px=SERIAL_PX):
    fonts = (app.font_mono_bold, app.font_mono, app.font_bold)
    measured = 0
    for font in fonts:
        size = abs(int(str(font.cget("size")))) or 12
        while font.measure(text) < min_px and size < 80:
            size += 1
            font.configure(size=size)
        measured = max(measured, font.measure(text))
    return measured


def _shown_blob(app) -> str:
    return _texts(app.root).replace("\n", "")


def _plain_shown(app) -> str:
    """Mapped copy with comparison brackets removed so the raw serial matches."""
    return _shown_blob(app).replace("[", "").replace("]", "")


def _nearest_canvas(widget):
    node = widget.master
    while node is not None:
        if isinstance(node, tk.Canvas):
            return node
        node = node.master
    return None


def _overlap_problems(app) -> list:
    """Mapped labels on the same card canvas whose boxes cover each other."""
    app.root.update_idletasks()
    boxes = []

    def visit(w):
        try:
            if w.winfo_class() == "Label" and w.winfo_ismapped():
                text = str(w.cget("text")).strip()
                host = _nearest_canvas(w)
                if text and host is not None:
                    x = w.winfo_rootx()
                    y = w.winfo_rooty()
                    boxes.append(
                        (
                            host,
                            x,
                            y,
                            x + w.winfo_width(),
                            y + w.winfo_height(),
                            text[:40],
                        )
                    )
        except tk.TclError:
            return
        for child in w.winfo_children():
            visit(child)

    visit(app.root)
    problems = []
    for i, (host_a, ax0, ay0, ax1, ay1, at) in enumerate(boxes):
        for host_b, bx0, by0, bx1, by1, bt in boxes[i + 1 :]:
            if host_a is not host_b:
                continue
            ix0, iy0 = max(ax0, bx0), max(ay0, by0)
            ix1, iy1 = min(ax1, bx1), min(ay1, by1)
            if ix1 - ix0 > 4 and iy1 - iy0 > 4:
                problems.append(f"overlap {at!r} x {bt!r}")
    return problems


def _in_viewport(canvas, widget) -> bool:
    """True when the widget's top edge lies in the canvas viewport."""
    top = widget.winfo_rooty() - canvas.winfo_rooty()
    return -2 <= top < canvas.winfo_height() + 2


def _scroll_widget_into_view(canvas, widget) -> None:
    bounds = canvas.bbox("all")
    if not bounds:
        return
    top = widget.winfo_rooty() - canvas.winfo_rooty()
    canvas.yview_moveto((canvas.canvasy(0) + top) / max(1, bounds[3]))
    canvas.update_idletasks()


def _to_working(wiz, app, size):
    _drive_to(wiz, app, Screen.LAST_CHANCE, size=size)
    wiz._erase_until = 0.0
    wiz.tick()
    wiz.confirm_erase()
    app._draw()
    app.root.update_idletasks()
    app.root.update()


def _to_done(wiz, app, size, *, preview=False):
    wiz.preview = preview
    _drive_to(wiz, app, Screen.LAST_CHANCE, size=size)
    wiz._erase_until = 0.0
    wiz.tick()
    wiz.runner.duration_s = 0.15
    wiz.confirm_erase()
    deadline = time.monotonic() + 5
    while wiz.screen != Screen.DONE and time.monotonic() < deadline:
        wiz.tick()
        app.root.update()
        time.sleep(0.02)
    app._draw()
    app.root.update_idletasks()
    app.root.update()


def test_helper_fails_on_1485px_serial_in_840px_canvas():
    """Unwrapped evidence serial must fail the canvas-aware helper."""
    _needs_display()
    root = tk.Tk()
    try:
        root.geometry("1024x740+40+40")
        font = _font_for_serial_px(root)
        measure = font.measure(EVIDENCE_SERIAL)
        assert measure >= SERIAL_PX
        label = _unwrapped_serial_card(root, font)
        assert _in_canvas(label)
        assert label.winfo_reqwidth() >= SERIAL_PX
        assert label.winfo_width() == CARD_PX
        problems = _clipping_problems(_plain_app(root))
        assert problems, "canvas-hosted 1,485 px serial must be reported"
        blob = " ".join(problems)
        assert "h-clip" in blob
        assert f"req={label.winfo_reqwidth()}" in blob
        assert f"actual={CARD_PX}" in blob
        assert EVIDENCE_SERIAL[:24] in blob
    finally:
        root.destroy()


def test_helper_passes_when_1485px_serial_is_wrapped():
    _needs_display()
    root = tk.Tk()
    try:
        root.geometry("1024x740+40+40")
        font = _font_for_serial_px(root)
        broken = _soft_break_tokens(EVIDENCE_SERIAL, font.measure, CARD_PX - 8)
        assert "\n" in broken
        assert broken.replace("\n", "") == EVIDENCE_SERIAL
        canvas = tk.Canvas(
            root, width=CARD_PX, height=200, bg="white", highlightthickness=0
        )
        canvas.pack()
        inner = tk.Frame(canvas, bg="white")
        canvas.create_window((0, 0), window=inner, anchor="nw", width=CARD_PX)
        label = tk.Label(
            inner,
            text=broken,
            font=font,
            bg="white",
            anchor="w",
            justify=tk.LEFT,
            wraplength=CARD_PX - 8,
        )
        label.pack(fill=tk.X)
        root.update_idletasks()
        root.update()
        assert _clipping_problems(_plain_app(root)) == []
        assert label.winfo_reqwidth() <= label.winfo_width() + 2
    finally:
        root.destroy()


def test_unwrapped_pick_card_fails_1485px_check(monkeypatch):
    """The live pick card without wrapping reproduces the dated clip."""
    _needs_display()

    def plain(self, parent, text, *, font, bg, fg=INK):
        label = tk.Label(
            parent,
            text=text,
            font=font,
            fg=fg,
            bg=bg,
            anchor="w",
            justify=tk.LEFT,
        )
        label.pack(fill=tk.X)
        return label

    monkeypatch.setattr(TkWizard, "_wrapping_label", plain)
    wiz = make_demo_wizard()
    _inject_evidence_disk(wiz)
    app = TkWizard(wiz)
    try:
        app.root.geometry("1024x740+40+40")
        app.root.update_idletasks()
        measured = _grow_identity_fonts(app, EVIDENCE_SERIAL)
        assert measured >= SERIAL_PX
        _drive_to(wiz, app, Screen.PICK, size=SUPPORTED_SIZE)
        clipped = []
        for widget in descendants(app.root):
            try:
                if widget.winfo_class() != "Label" or not widget.winfo_ismapped():
                    continue
                text = (
                    str(widget.cget("text"))
                    .replace("\n", "")
                    .replace("[", "")
                    .replace("]", "")
                )
            except tk.TclError:
                continue
            if EVIDENCE_SERIAL not in text:
                continue
            req, actual = widget.winfo_reqwidth(), widget.winfo_width()
            if req > actual + 2:
                clipped.append((req, actual, text[:48]))
        assert clipped, _clipping_problems(app)
        req, actual, _snippet = clipped[0]
        assert req >= SERIAL_PX
        assert actual < SERIAL_PX
        blob = " ".join(_clipping_problems(app))
        assert "h-clip" in blob and "req=" in blob and "actual=" in blob
    finally:
        app._teardown()


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize(
    "screen",
    [Screen.PICK, Screen.CONFIRM, Screen.LAST_CHANCE],
)
def test_long_identity_cards_stay_unclipped_at_supported_sizes(size, screen):
    wiz, app = _long_identity_app(size)
    try:
        _drive_to(wiz, app, screen, size=size)
        app._show_more = True
        app._draw()
        app.root.update_idletasks()
        app.root.update()
        assert app.w.screen == screen
        assert _clipping_problems(app) == []
        assert _overlap_problems(app) == []
        selected = app.w.selected
        assert selected is not None
        blob = _plain_shown(app)
        assert selected.serial in blob
        assert selected.display_name.replace("\n", "") in blob
        _assert_actions_on_window(app)
    finally:
        app._teardown()


def test_pick_card_keeps_1485px_serial_complete(ui):  # noqa: F811
    wiz, app = ui(size=SUPPORTED_SIZE)
    _inject_evidence_disk(wiz)
    measured = _grow_identity_fonts(app, EVIDENCE_SERIAL)
    assert measured >= SERIAL_PX
    _drive_to(wiz, app, Screen.PICK, size=SUPPORTED_SIZE)
    app._show_more = True
    app._draw()
    app.root.update_idletasks()
    app.root.update()
    assert _clipping_problems(app) == []
    blob = _plain_shown(app)
    assert EVIDENCE_SERIAL in blob
    assert EVIDENCE_MODEL.replace("\n", "") in blob
    assert "…" not in blob and "..." not in blob
    _assert_actions_on_window(app)


@pytest.mark.parametrize("size", SIZES)
def test_progress_card_keeps_percent_and_identity(ui, size):  # noqa: F811
    wiz, app = ui(size=size)
    app.root.minsize(*MIN_SIZE)
    _to_working(wiz, app, size)
    assert wiz.screen == Screen.WORKING
    assert app._progress_bar is not None
    assert app._progress_pct is not None
    assert _in_canvas(app._progress_pct)
    assert _clipping_problems(app) == []
    blob = _plain_shown(app)
    assert wiz.selected.display_name in blob
    assert wiz.selected.serial in blob
    assert C.ERASE_PROGRESS_LABEL in blob
    bar = app._progress_bar
    assert bar.winfo_width() <= app.root.winfo_width()
    _assert_actions_on_window(app)


@pytest.mark.parametrize("size", [MIN_SIZE, SUPPORTED_SIZE, LARGE_SIZE])
@pytest.mark.parametrize("code", ["verified", "cancelled", "engine_failed"])
def test_dense_results_keep_identity_and_status(size, code):
    _needs_display()
    wiz, _, _ = case_evidence(next(c for c in CASES if c[0] == code))
    app = TkWizard(wiz)
    try:
        app.root.minsize(*MIN_SIZE)
        app.root.geometry(f"{size[0]}x{size[1]}+40+40")
        app._draw()
        app.root.update()
        assert _clipping_problems(app) == []
        blob = _plain_shown(app)
        assert wiz.result_view.message in blob
        assert wiz.selected.display_name in blob
        assert wiz.selected.serial in blob
        assert C.REPORT_STATUS_TITLE in blob
        _assert_actions_on_window(app)
        if app._body_canvas is not None:
            labels = [
                w
                for w in descendants(app._body_canvas)
                if w.winfo_class() == "Label" and w.winfo_ismapped()
            ]
            assert labels
            app._body_canvas.yview_moveto(1.0)
            app.root.update()
            bottom = max(labels, key=lambda w: w.winfo_rooty())
            assert _in_viewport(app._body_canvas, bottom)
    finally:
        app._teardown()


def test_german_long_copy_and_identity_stay_in_cards(ui):  # noqa: F811
    from beamo_wipe import lang
    from beamo_wipe import outcomes

    try:
        lang.set_language("de")
        views = outcomes.VIEWS
        code = max(views, key=lambda c: len(views[c].message))
        case = next(c for c in CASES if c[0] == code)
        wiz, _, _ = case_evidence(case)
        wiz.set_language("de")
        _, app = ui(size=SUPPORTED_SIZE)
        app.w = wiz
        app._draw()
        app.root.update()
        assert _clipping_problems(app) == []
        blob = _plain_shown(app)
        assert views[code].message.replace("\n", "") in blob
        assert wiz.selected.serial in blob
        _assert_actions_on_window(app)
    finally:
        lang.set_language("en")


def test_comparison_readers_keep_long_serials_and_scroll(ui):  # noqa: F811
    wiz, app = ui(size=SUPPORTED_SIZE)
    sample = wiz.selectable[0]
    disks = tuple(
        replace(sample, path=f"/dev/sd{chr(97 + i)}", serial=f"SERIAL-{i}-" + "X" * 80)
        for i in range(6)
    )
    wiz.discovery = replace(wiz.discovery, disks=disks, selectable=disks)
    wiz.screen = Screen.PICK
    wiz.select_disk(disks[-1].path)
    app.root.geometry("1024x740+40+40")
    app._draw()
    app.root.update()
    toggle = next(
        w
        for w in descendants(app.root)
        if isinstance(w, _CheckRow) and w.cget("text") == inventory.COMPARE_TITLE
    )
    toggle.invoke()
    app.root.update()
    readers = [
        w
        for w in descendants(app.root)
        if isinstance(w, tk.Text) and w.get("1.0", "end").startswith("Disk ")
    ]
    assert len(readers) == 6
    for reader in readers:
        body = reader.get("1.0", "end")
        assert "X" * 80 in body
        assert reader.winfo_width() <= app.root.winfo_width()
    assert _clipping_problems(app) == []
    last = readers[-1]
    canvas = app._pick_canvas
    assert canvas is not None
    last.focus_force()
    app.root.update()
    assert _in_viewport(canvas, last)
    _assert_actions_on_window(app)


def test_pick_list_scroll_reveals_last_card(ui):  # noqa: F811
    wiz, app = ui(size=SUPPORTED_SIZE)
    sample = wiz.selectable[0]
    disks = tuple(
        replace(sample, path=f"/dev/vd{chr(97 + i)}", serial=f"ID{i}-" + "Z" * 24)
        for i in range(8)
    )
    wiz.discovery = replace(wiz.discovery, disks=disks, selectable=disks)
    wiz.screen = Screen.PICK
    wiz.select_disk(disks[-1].path)
    app.root.geometry("1024x740+40+40")
    app._draw()
    app.root.update()
    canvas = app._pick_canvas
    assert canvas is not None
    cards = [
        w
        for w in descendants(canvas)
        if w.winfo_class() == "Label" and "Z" * 24 in str(w.cget("text"))
    ]
    assert cards
    last = max(cards, key=lambda w: w.winfo_rooty())
    _scroll_widget_into_view(canvas, last)
    app.root.update()
    assert _in_viewport(canvas, last)
    assert disks[-1].serial in _plain_shown(app)
    assert _clipping_problems(app) == []
    _assert_actions_on_window(app)


def test_large_type_window_keeps_canvas_cards_readable(ui):  # noqa: F811
    wiz, app = ui(size=LARGE_SIZE)
    _inject_evidence_disk(wiz)
    _grow_identity_fonts(app, EVIDENCE_SERIAL, min_px=SERIAL_PX)
    _drive_to(wiz, app, Screen.CONFIRM, size=LARGE_SIZE)
    app._show_more = True
    app._draw()
    app.root.update()
    assert app.lay.scale > 1.0
    assert _clipping_problems(app) == []
    assert EVIDENCE_SERIAL in _plain_shown(app)
    _assert_actions_on_window(app)


def test_show_more_keyboard_keeps_path_unclipped(ui):  # noqa: F811
    wiz, app = ui(size=SUPPORTED_SIZE)
    _drive_to(wiz, app, Screen.PICK, size=SUPPORTED_SIZE)
    more = next(
        b
        for b in descendants(app.root)
        if isinstance(b, _Button) and b.itemcget(b._label, "text") == C.BTN_MORE
    )
    more.focus_set()
    app.root.update()
    more.event_generate("<Return>")
    app.root.update()
    assert app._show_more
    assert _clipping_problems(app) == []
    blob = _plain_shown(app)
    assert wiz.selected.serial in blob
    from beamo_wipe.identity import SYSTEM_PATH_NOTE

    assert SYSTEM_PATH_NOTE.replace("\n", "") in blob
    _assert_actions_on_window(app)
