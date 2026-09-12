# SPDX-License-Identifier: GPL-3.0-or-later
"""Mapped Tk windows and 80x24 pseudo-terminals for owner-visible outcomes.

This file is rendered proof. Source-string tests elsewhere are not substitutes.
Fake devices, DryRunRunner, and injected clocks only.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.identity import DUPLICATE_ID, present_disk
from beamo_wipe.models import Screen
from beamo_wipe.outcomes import VIEWS
from beamo_wipe.ui.layout import LARGE_SIZE, MIN_SIZE
from test_adaptive_layout import _assert_actions_on_window, _buttons, _texts
from test_console_parity import _draw, _footer
from test_result_presentations import CASES, case_evidence
from test_tk_runtime import (
    WINDOW,
    _button_named,
    _clipping_problems,
    _drive_to,
    _off_window_problems,
    ui,  # noqa: F401
)
from test_usb_report_workflow import _done_wizard, _success_receipt


def _mapped_text(app) -> str:
    app.root.update_idletasks()
    app.root.update()
    return _texts(app.root)


def _assert_geometry(app) -> None:
    app.root.update_idletasks()
    app.root.update()
    _assert_actions_on_window(app)
    assert _clipping_problems(app) == []
    if app._body_canvas is None:
        assert _off_window_problems(app) == []


@pytest.mark.parametrize("size", [MIN_SIZE, LARGE_SIZE])
@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_every_outcome_renders_message_next_step_and_actions(ui, size, case):  # noqa: F811
    wiz, _, _ = case_evidence(case)
    view = wiz.result_view
    assert view.code == case[0]
    _, app = ui(size=size)
    app.w = wiz
    app.root.minsize(*MIN_SIZE)
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app._draw()
    shown = _mapped_text(app)
    assert view.message in shown
    assert view.next_step in shown
    assert wiz.selected.display_name in shown
    if view.success:
        assert "verification passed" in shown or "was not performed" in shown
    else:
        assert "verification passed" not in shown
    labels = [b.itemcget(b._label, "text") for b in _buttons(app) if b.winfo_ismapped()]
    assert C.BTN_SHUTDOWN in labels
    save = next(b for b in _buttons(app) if b.itemcget(b._label, "text") == C.BTN_SAVE_REPORT)
    assert save._enabled is bool(wiz.report_view.can_save)
    _assert_geometry(app)


def test_verified_and_unverified_stay_visibly_distinct(ui):  # noqa: F811
    verified, _, _ = case_evidence(CASES[0])
    unverified, _, _ = case_evidence(CASES[1])
    assert verified.result_view.success and unverified.result_view.success
    _, app = ui(size=MIN_SIZE)
    app.root.minsize(*MIN_SIZE)
    app.w = verified
    app._draw()
    ok_shown = _mapped_text(app)
    app.w = unverified
    app._draw()
    warn_shown = _mapped_text(app)
    assert VIEWS["verified"].message in ok_shown
    assert VIEWS["unverified"].message in warn_shown
    assert VIEWS["verified"].message not in warn_shown
    assert "read-back pass" in warn_shown.lower() or "was not performed" in warn_shown
    assert VIEWS["verified"].next_step in ok_shown
    assert VIEWS["unverified"].next_step in warn_shown
    _assert_geometry(app)


def test_cancelled_working_and_result_keep_reachable_actions(ui):  # noqa: F811
    wiz, app = ui(size=MIN_SIZE)
    app.root.minsize(*MIN_SIZE)
    _drive_to(wiz, app, Screen.LAST_CHANCE, size=MIN_SIZE)
    wiz.screen = Screen.WORKING
    app._draw()
    shown = _mapped_text(app)
    assert "Cancel erase" in shown
    cancel = next(
        b for b in _buttons(app) if "Cancel" in b.itemcget(b._label, "text")
    )
    assert cancel._enabled
    _assert_geometry(app)
    cancelled, _, _ = case_evidence(CASES[6])
    app.w = cancelled
    app._draw()
    shown = _mapped_text(app)
    assert VIEWS["cancelled"].message in shown
    assert VIEWS["cancelled"].next_step in shown
    _assert_geometry(app)


def test_unsaved_report_shutdown_dialog_defaults_to_keep(ui):  # noqa: F811
    wiz, app = ui(size=MIN_SIZE)
    app.root.minsize(*MIN_SIZE)
    wiz.preview = False
    wiz.report_wanted = True
    wiz.screen = Screen.DONE
    wiz.shutdown()
    app._draw()
    shown = _mapped_text(app)
    assert wiz.screen == Screen.SHUTDOWN_CONFIRM
    assert C.SHUTDOWN_TITLE in shown
    assert C.SHUTDOWN_LOSS in shown
    keep = _button_named(app, C.SHUTDOWN_KEEP)
    discard = _button_named(app, C.SHUTDOWN_DISCARD)
    assert keep._enabled and discard._enabled
    assert app.root.focus_get() is keep
    _assert_geometry(app)
    app._on_return()
    assert wiz.screen == Screen.DONE
    assert not wiz.wants_shutdown


def test_saved_report_receipt_is_visible_on_done(ui, tmp_path):  # noqa: F811
    _, app = ui(size=MIN_SIZE)
    app.root.minsize(*MIN_SIZE)
    wiz = _done_wizard(_success_receipt, tmp_path)
    wiz.save_report_to_usb()
    app.w = wiz
    app._draw()
    shown = _mapped_text(app)
    assert "Folder: BEAMO-WIPE-REPORTS/" in shown
    assert "safe to remove" in shown.lower() or "RESULT.txt" in shown
    save = _button_named(app, C.BTN_SAVE_REPORT)
    assert save._enabled is bool(wiz.report_view.can_save)
    _assert_geometry(app)


def test_long_and_duplicate_identities_render_without_truncation(ui):  # noqa: F811
    wiz, app = ui(size=MIN_SIZE)
    app.root.minsize(*MIN_SIZE)
    _drive_to(wiz, app, Screen.PICK, size=MIN_SIZE)
    first, second = sorted(wiz.selectable, key=lambda d: d.path)[:2]
    long = replace(
        first,
        model="Very Long Disk Model Name That Exceeds Normal Length 12340",
        serial="DUP-" + ("A" * 48),
    )
    twin = replace(second, model="Other drive", serial=long.serial)
    remaining = [d for d in wiz.selectable if d.path not in {first.path, second.path}]
    selectable = (long, twin) + tuple(remaining)
    wiz.discovery = replace(
        wiz.discovery,
        disks=selectable + ((wiz.discovery.boot,) if wiz.discovery.boot else ()),
        selectable=selectable,
    )
    wiz.selected = long
    app._draw()
    shown = _mapped_text(app)
    assert long.model in shown
    assert long.serial in shown or long.serial[:20] in shown.replace("\n", "")
    assert DUPLICATE_ID in shown
    _assert_geometry(app)
    wiz.continue_pick()
    if wiz.screen == Screen.CONFIRM:
        app._draw()
        shown = _mapped_text(app)
        view = present_disk(long, wiz.listed_disks)
        assert view.title in shown
        assert DUPLICATE_ID in shown
        _assert_geometry(app)


def test_enlarged_type_still_keeps_warnings_and_actions(ui):  # noqa: F811
    wiz, compact = ui(size=MIN_SIZE)
    compact.root.minsize(*MIN_SIZE)
    compact.root.geometry("800x600+40+40")
    _drive_to(wiz, compact, Screen.LAST_CHANCE, size=MIN_SIZE)
    compact_size = abs(int(str(compact.font_h.cget("size"))))
    large_wiz, large = ui(size=LARGE_SIZE)
    large.root.geometry("1600x1000+40+40")
    _drive_to(large_wiz, large, Screen.LAST_CHANCE, size=LARGE_SIZE)
    assert abs(int(str(large.font_h.cget("size")))) > compact_size
    shown = _mapped_text(large)
    assert large_wiz.selected.display_name in shown
    assert "cannot get" in shown.lower() or large_wiz.erase_label() in shown
    erase = _button_named(large, C.BTN_ERASE)
    assert erase._enabled is bool(large_wiz.erase_enabled)
    _assert_geometry(large)


def test_focus_order_and_gated_actions(ui):  # noqa: F811
    wiz, app = ui(size=WINDOW)
    _drive_to(wiz, app, Screen.OWNER, size=WINDOW)
    continue_btn = _button_named(app, C.BTN_CONTINUE)
    assert not wiz.owner_ok
    assert not continue_btn._enabled
    wiz.set_owner(True)
    app._draw()
    app.root.update()
    continue_btn = _button_named(app, C.BTN_CONTINUE)
    assert continue_btn._enabled
    wiz.continue_owner()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    app._draw()
    app.root.update()
    assert wiz.screen == Screen.CONFIRM
    confirm = _button_named(app, C.BTN_CONTINUE)
    assert not confirm._enabled
    assert app.root.focus_get() is not None
    wiz.set_confirm_input(wiz.confirm.token)
    app._confirm_var.set(wiz.confirm.token)
    app._draw()
    app.root.update()
    confirm = _button_named(app, C.BTN_CONTINUE)
    assert confirm._enabled
    wiz.continue_confirm()
    wiz.continue_method()
    app._draw()
    app.root.update()
    assert wiz.screen == Screen.LAST_CHANCE
    erase = _button_named(app, C.BTN_ERASE)
    assert erase._enabled is bool(wiz.erase_enabled)
    focus = app.root.focus_get()
    assert focus is not erase
    assert focus.itemcget(focus._label, "text") == C.BTN_BACK


def test_console_every_outcome_fits_80x24_without_overflow(monkeypatch):
    for case in CASES:
        wiz, _, _ = case_evidence(case)
        shown, packed, term = _draw(monkeypatch, wiz)
        view = wiz.result_view
        assert view.message in shown
        assert view.next_step in shown
        assert all(len(line) < 80 for line in term.frames[-1].values())
        assert max(term.frames[-1]) < 24
        footer = _footer(term)
        assert "shut down" in footer.lower() or "save" in footer.lower()
        wiz.wants_shutdown = False


def test_console_long_identity_and_shutdown_stay_in_viewport(monkeypatch):
    wiz = make_demo_wizard()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.selected = replace(disk, model="很长" * 40, serial="SERIAL-" + ("Z" * 48))
    wiz.screen = Screen.CONFIRM
    shown, packed, term = _draw(monkeypatch, wiz)
    assert "SERIAL-" in packed
    assert all(len(line) < 80 for line in term.frames[-1].values())
    assert max(term.frames[-1]) < 24
    wiz.wants_shutdown = False
    wiz, _, _ = case_evidence(CASES[0])
    wiz.report_wanted = True
    wiz.shutdown()
    shown, packed, term = _draw(monkeypatch, wiz)
    assert C.SHUTDOWN_TITLE in shown
    assert C.SHUTDOWN_LOSS in shown
    footer = _footer(term)
    assert "keep session open" in footer.lower()
    assert max(term.frames[-1]) < 24
    assert all(len(line) < 80 for line in term.frames[-1].values())


@pytest.mark.parametrize('size', [(800, 600), (1024, 600), (1024, 740), (1280, 820)])
def test_result_checks_keep_details_visible_and_warnings_scrollable(ui, size):  # noqa: F811
    wiz, _, _ = case_evidence(CASES[0])
    assert len(wiz.check_alerts) == 2
    _, app = ui(size=size)
    app.w = wiz
    app.root.minsize(*MIN_SIZE)
    app.root.geometry(f'{size[0]}x{size[1]}+40+40')
    app._draw()
    shown = _mapped_text(app)
    for warning in wiz.check_alerts:
        assert warning in shown
    canvas = app._body_canvas
    assert canvas is not None
    details = _button_named(app, C.BTN_MORE)
    assert details.winfo_rooty() >= canvas.winfo_rooty()
    assert details.winfo_rooty() + details.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()
    if canvas.yview()[1] < 1.0:
        before = canvas.yview()[0]
        app.root.event_generate('<Next>')
        app.root.update()
        assert canvas.yview()[0] > before
    for label in (C.BTN_SAVE_REPORT, C.BTN_SHUTDOWN):
        button = _button_named(app, label)
        assert button.winfo_rooty() >= app._footer.winfo_rooty()
        assert button.winfo_rooty() + button.winfo_height() <= app.root.winfo_rooty() + size[1]
