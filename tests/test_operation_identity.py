# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #89: method and disk identity stay visible while erasing."""

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.methods import METHODS
from beamo_wipe.models import MethodId, Screen
from test_console_parity import _draw
from test_progress_timing import Clock
from test_tk_runtime import _drive_to, ui  # noqa: F401


def _working(method=MethodId.EXTRA):
    clock = Clock()
    clock.add = clock.advance
    wiz = make_demo_wizard()
    wiz.preview = False
    wiz._clock = clock
    wiz.runner._clock = clock
    wiz.runner.duration_s = 1000
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(sorted(wiz.selectable, key=lambda d: d.path)[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.set_method(method)
    wiz.continue_method()
    clock.add(5.0)
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert wiz._wipe_request is not None
    return wiz, clock


def _request_disk(wiz):
    return next(
        disk for disk in wiz.listed_disks if disk.path == wiz._wipe_request.device
    )


def test_operation_identity_matches_request_disk():
    wiz, _clock = _working()
    disk = _request_disk(wiz)
    assert wiz.operation_identity_text == wiz.disk_view(disk).announcement
    assert disk.serial in wiz.operation_identity_text


def test_operation_identity_ignores_tampered_selection():
    wiz, _clock = _working()
    disk = _request_disk(wiz)
    other = sorted(wiz.selectable, key=lambda d: d.path)[1]
    assert other.path != disk.path
    wiz.selected = other
    assert wiz.operation_identity_text == wiz.disk_view(disk).announcement
    assert other.serial not in wiz.operation_identity_text


def test_operation_method_matches_request():
    wiz, _clock = _working(MethodId.EXTRA)
    assert wiz._wipe_request.method == MethodId.EXTRA
    assert wiz.operation_method_text == METHODS[MethodId.EXTRA].operation_summary
    wiz.method = MethodId.QUICK_ZERO
    assert wiz.operation_method_text == METHODS[MethodId.EXTRA].operation_summary


def test_unresolvable_request_device_shows_path_and_note():
    from dataclasses import replace

    wiz, _clock = _working()
    disk = _request_disk(wiz)
    wiz._wipe_request = replace(wiz._wipe_request, device="/dev/ghost")
    text = wiz.operation_identity_text
    assert "/dev/ghost" in text
    assert "Device identity unavailable" in text
    assert disk.serial not in text


def _at_working_screen(monkeypatch, screen):
    wiz = make_demo_wizard()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.method = MethodId.EXTRA
    wiz.screen = screen
    return wiz, disk


def test_curses_working_shows_method(monkeypatch):
    wiz, disk = _at_working_screen(monkeypatch, Screen.WORKING)
    shown, packed, _term = _draw(monkeypatch, wiz)
    assert disk.serial in packed
    assert METHODS[MethodId.EXTRA].operation_summary in shown


def test_curses_working_wraps_long_identity(monkeypatch):
    from dataclasses import replace

    wiz, _disk = _at_working_screen(monkeypatch, Screen.WORKING)
    wiz.selected = replace(
        wiz.selected,
        model="삼성 " + ("很长" * 30),
        serial="시리얼-ΑΒΓΔ-" + ("A" * 48),
    )
    _shown, packed, term = _draw(monkeypatch, wiz)
    assert "삼성" in packed
    assert "시리얼" in packed
    assert all(len(line) < 80 for line in term.frames[-1].values())
    assert max(term.frames[-1]) < 24


def test_curses_stopping_shows_method(monkeypatch):
    wiz, disk = _at_working_screen(monkeypatch, Screen.STOPPING)
    shown, packed, _term = _draw(monkeypatch, wiz)
    assert disk.serial in packed
    assert METHODS[MethodId.EXTRA].operation_summary in shown


def test_plain_working_repeats_identity_and_method(monkeypatch, capsys):
    import sys

    from beamo_wipe.ui import console_wizard as console

    wiz, _clock = _working(MethodId.EXTRA)
    disk = _request_disk(wiz)
    monkeypatch.setattr(
        console.select, "select", lambda *a, **k: ([sys.stdin], [], [])
    )

    class _Eof:
        def readline(self):
            return ""

    monkeypatch.setattr(sys, "stdin", _Eof())
    monkeypatch.setattr(
        "builtins.input", lambda *_: (_ for _ in ()).throw(EOFError())
    )
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    assert disk.serial in text
    assert METHODS[MethodId.EXTRA].operation_summary in text


def test_plain_stopping_shows_method(monkeypatch, capsys):
    from beamo_wipe.ui import console_wizard as console

    wiz = make_demo_wizard()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.method = MethodId.EXTRA
    wiz.screen = Screen.STOPPING
    monkeypatch.setattr(
        console.time, "sleep", lambda *_: (_ for _ in ()).throw(EOFError())
    )
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    assert disk.serial in text
    assert METHODS[MethodId.EXTRA].operation_summary in text


def test_accessible_stopping_shows_identity_and_method():
    pytest.importorskip("gi")
    from test_accessible_runtime import text, wait_for_window_size

    from beamo_wipe.ui.accessible_wizard import AccessibleWizard

    wiz = make_demo_wizard()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.method = MethodId.EXTRA
    wiz.screen = Screen.STOPPING
    app = AccessibleWizard(wiz)
    app.window.resize(800, 600)
    wait_for_window_size(app.window, (800, 600))
    rendered = text(app)
    assert disk.serial in rendered
    assert METHODS[MethodId.EXTRA].operation_summary in rendered


def test_gallery_stop_frames_carry_method():
    from beamo_wipe.gallery import gallery_html

    html = gallery_html("en")
    assert 'id="stop-method"' in html
    assert "P.methods[method].operation" in html


def test_tk_stop_confirm_shows_method(ui, tmp_path, monkeypatch):
    w, app = ui()
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
    labels = _tk_labels(app)
    assert METHODS[w.method].operation_summary in labels


def test_tk_stopping_shows_identity_and_method(ui):
    w, app = ui()
    disk = sorted(w.selectable, key=lambda d: d.path)[0]
    w.selected = disk
    w.screen = Screen.STOPPING
    app._draw()
    app.root.update_idletasks()
    labels = _tk_labels(app)
    assert disk.serial in labels
    assert METHODS[w.method].operation_summary in labels
    assert C.BUSY_STOPPING_TITLE in labels


def _tk_labels(app):
    import tkinter as tk

    found = []

    def visit(widget):
        if isinstance(widget, tk.Label):
            try:
                found.append(str(widget.cget("text")))
            except tk.TclError:
                pass
        for child in widget.winfo_children():
            visit(child)

    visit(app.root)
    return "\n".join(found)
