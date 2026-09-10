# SPDX-License-Identifier: GPL-3.0-or-later
"""80x24 curses and plain-console parity. Fake devices only."""

from __future__ import annotations

from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe import diagnostic_report as D
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.identity import present_disk
from beamo_wipe.methods import METHODS
from beamo_wipe.models import DiscoveryResult, Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import Wizard
from test_result_presentations import CASES, case_evidence


class Terminal:
    def __init__(self, wizard, h=24, w=80, keys=None, sizes=None):
        self.wizard = wizard
        self.h = h
        self.w = w
        self.rows = {}
        self.frames = []
        self._keys = iter(keys or [])
        self._sizes = list(sizes or [])

    def getmaxyx(self):
        if self._sizes:
            self.h, self.w = self._sizes[0]
        return self.h, self.w

    def addstr(self, y, x, text, attr=0):
        assert 0 <= y < self.h, y
        assert len(text) < self.w, (len(text), text[:40])
        self.rows[y] = text

    def erase(self):
        if self.rows:
            self.frames.append(dict(self.rows))
        self.rows = {}

    def getch(self):
        self.frames.append(dict(self.rows))
        if self._sizes:
            self._sizes.pop(0)
        try:
            return next(self._keys)
        except StopIteration:
            self.wizard.wants_shutdown = True
            return -1

    def __getattr__(self, name):
        return lambda *a, **k: None


def _draw(monkeypatch, wiz, **kw):
    terminal = Terminal(wiz, **kw)
    for name in ("curs_set", "use_default_colors", "echo", "noecho"):
        monkeypatch.setattr(console.curses, name, lambda *a, **k: None)
    console._loop(terminal, wiz)
    last = terminal.frames[-1] if terminal.frames else {}
    shown = " ".join(last[y] for y in sorted(last))
    packed = "".join(last[y] for y in sorted(last))
    return shown, packed, terminal


def _footer(term, rows=4):
    last = term.frames[-1]
    return " ".join(last.get(y, "") for y in range(max(0, term.h - rows), term.h))


def _at_pick():
    wiz = make_demo_wizard()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    return wiz


def replace_selectable(wiz, disks):
    return DiscoveryResult(
        disks=tuple(disks) + ((wiz.discovery.boot,) if wiz.discovery.boot else ()),
        selectable=tuple(disks),
        boot=wiz.discovery.boot,
        boot_identified=True,
        excluded=wiz.discovery.excluded,
    )


def _long_list(wiz, count=18):
    base = wiz.selectable[0]
    many = []
    for i in range(count):
        many.append(
            replace(
                base,
                path=f"/dev/vd{chr(97 + i)}",
                name=f"vd{chr(97 + i)}",
                serial=f"SERIAL-{i:04d}-" + ("Z" * 40),
                model=f"Disk {i} " + ("很长" * 12),
            )
        )
    wiz.discovery = replace_selectable(wiz, many)
    assert len(wiz.selectable) == count
    return many


def test_what_keeps_enter_action_on_80x24(monkeypatch):
    wiz = make_demo_wizard()
    wiz.skip_intro()
    shown, packed, term = _draw(monkeypatch, wiz)
    footer = _footer(term)
    assert "Enter: I understand" in footer
    assert "copies you need" in shown
    assert "F5: Check disks again" in shown
    assert "R: Need a report?" in shown


def test_pick_keeps_selection_and_action_visible_with_long_list(monkeypatch):
    wiz = _at_pick()
    many = _long_list(wiz)
    wiz.selected = many[-1]
    shown, packed, term = _draw(monkeypatch, wiz)
    last = term.frames[-1]
    assert many[-1].serial in packed
    assert ">" in shown
    assert "Up/Down then Enter" in _footer(term)
    assert all(len(line) < 80 for line in last.values())
    assert max(last) < 24


def test_pick_page_keys_move_selection_into_view(monkeypatch):
    wiz = _at_pick()
    many = _long_list(wiz)
    wiz.selected = many[0]
    shown, packed, term = _draw(monkeypatch, wiz, keys=[console.curses.KEY_NPAGE])
    assert wiz.selected.path == many[min(8, len(many) - 1)].path
    assert wiz.selected.serial in packed


@pytest.mark.parametrize("method", list(METHODS))
def test_method_screen_shows_overwrite_and_verification(method, monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.set_method(method)
    shown, packed, term = _draw(monkeypatch, wiz)
    for spec in METHODS.values():
        assert spec.overwrite_description in shown
        assert spec.verification_description in shown
        assert spec.description in shown
    assert "L: limits" in shown
    assert "F5: Check disks again" in shown
    assert "R: Need a report?" in shown


@pytest.mark.parametrize("method", list(METHODS))
def test_last_chance_and_done_keep_full_identity(method, monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.set_method(method)
    wiz.continue_method()
    shown, packed, term = _draw(monkeypatch, wiz)
    view = present_disk(wiz.selected, wiz.listed_disks)
    assert view.title in shown
    assert view.id_value in shown
    assert view.kind_chip in shown
    assert (
        METHODS[method].overwrite_description.split(":")[0] in shown
        or METHODS[method].summary in shown
    )
    footer = _footer(term)
    assert "Enter to erase" in footer or "Wait" in footer
    wiz.wants_shutdown = False
    wiz.screen = Screen.DONE
    shown, packed, term = _draw(monkeypatch, wiz)
    assert view.title in shown
    assert view.id_value in shown
    assert METHODS[method].summary in shown
    assert wiz.result_view.message in shown or wiz.method_result in shown


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_every_outcome_console_keeps_identity_and_footer(case, monkeypatch):
    wiz, _, _ = case_evidence(case)
    shown, packed, term = _draw(monkeypatch, wiz)
    assert wiz.result_view.message in shown
    assert wiz.result_view.next_step in shown
    assert wiz.selected.display_name in shown
    footer = _footer(term)
    assert "shut down" in footer.lower() or "run again" in footer.lower()


@pytest.mark.parametrize("screen", [Screen.CHECKING, Screen.STOPPING, Screen.REFRESHING, Screen.WORKING])
def test_busy_screens_keep_identity_and_reachable_status(screen, monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.screen = screen
    shown, packed, term = _draw(monkeypatch, wiz)
    assert disk.display_name in shown
    assert disk.serial in packed
    last = term.frames[-1]
    assert max(last) < 24
    if screen == Screen.WORKING:
        assert "cancel" in _footer(term).lower()
    else:
        assert "wait" in shown.lower() or "Stopping" in shown or "Checking" in shown


def test_unicode_identity_wraps_on_80x24(monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.selected = replace(disk, model="삼성 " + ("很长" * 30), serial="시리얼-ΑΒΓΔ-" + ("A" * 48))
    wiz.screen = Screen.CONFIRM
    shown, packed, term = _draw(monkeypatch, wiz)
    assert "삼성" in packed
    assert "시리얼" in packed
    assert all(len(line) < 80 for line in term.frames[-1].values())
    assert "cannot get" in shown.lower() or "will be erased" in shown.lower()
    assert "F5: Check disks again" in shown
    assert max(term.frames[-1]) < 24


def test_short_terminal_scrolls_power_warning_into_view(monkeypatch):
    wiz = make_demo_wizard()
    wiz.skip_intro()
    shown, packed, term = _draw(
        monkeypatch,
        wiz,
        keys=[console.curses.KEY_DOWN] * 8,
        sizes=[(16, 60)] * 10,
    )
    all_text = " ".join(" ".join(frame[y] for y in sorted(frame)) for frame in term.frames)
    assert "Enter: I understand" in all_text
    assert "wall power" in all_text
    assert all(max(frame) < 16 for frame in term.frames if frame)
    assert all(len(row) < 60 for frame in term.frames for row in frame.values())


def test_resize_keeps_action_on_last_rows(monkeypatch):
    wiz = make_demo_wizard()
    wiz.skip_intro()
    shown, packed, term = _draw(
        monkeypatch,
        wiz,
        keys=[console.KEY_RESIZE, console.KEY_RESIZE],
        sizes=[(24, 80), (16, 60), (24, 80)],
    )
    last = term.frames[-1]
    footer = _footer(term)
    assert "Enter: I understand" in footer
    assert all(y < term.h for y in last)
    shorts = [frame for frame in term.frames if frame and max(frame) < 16]
    assert shorts
    short = shorts[0]
    assert any("Enter: I understand" in row for row in short.values())
    assert all(len(row) < 60 for row in short.values())


def test_plain_fallback_methods_identity_and_busy(monkeypatch, capsys):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    for spec in METHODS.values():
        assert spec.overwrite_description in text
        assert spec.verification_description in text
        assert spec.description in text
    wiz.wants_shutdown = False
    wiz.screen = Screen.CHECKING
    monkeypatch.setattr(console.time, "sleep", lambda *_: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    busy = capsys.readouterr().out
    assert "Checking disk" in busy
    assert disk.display_name in busy


def test_report_help_is_reachable_from_what(monkeypatch):
    wiz = make_demo_wizard()
    wiz.skip_intro()
    shown, packed, term = _draw(monkeypatch, wiz, keys=[ord("r")])
    assert C.REPORT_HELP_TITLE in shown
    assert "FAT32" in packed
    assert "Arrows/Pg: read" in _footer(term)


def test_diagnostic_keeps_notice_and_action(monkeypatch):
    wiz = Wizard(
        DiscoveryResult(error="fake discovery", error_code="discovery_failed"),
        DryRunRunner(),
    )
    wiz.preview = False
    wiz.screen = Screen.PICK_BLOCKED
    assert wiz.can_open_diagnostic
    wiz.open_diagnostic()
    assert wiz.screen == Screen.DIAGNOSTIC
    shown, packed, term = _draw(monkeypatch, wiz)
    assert D.NOTICE.split(".")[0] in shown or "not erase evidence" in shown.lower()
    assert "prepare" in shown.lower() or "R:" in _footer(term)
    assert "shut down" in _footer(term).lower()


def test_shutdown_confirm_keeps_loss_and_actions(monkeypatch):
    wiz, _, _ = case_evidence(CASES[0])
    wiz.report_wanted = True
    wiz.shutdown()
    assert wiz.screen == Screen.SHUTDOWN_CONFIRM
    shown, packed, term = _draw(monkeypatch, wiz)
    assert C.SHUTDOWN_TITLE in shown
    assert C.SHUTDOWN_LOSS in shown
    footer = _footer(term)
    assert "keep session open" in footer
    assert "without saving" in footer.lower()


def test_working_escape_is_advertised_and_handled(monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.screen = Screen.WORKING
    shown, packed, term = _draw(monkeypatch, wiz, keys=[27])
    assert "cancel" in " ".join(
        " ".join(frame.get(y, "") for y in sorted(frame)) for frame in term.frames
    ).lower()


def test_plain_terminal_confirm_and_help_are_deterministic(monkeypatch, capsys):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    answers = iter(["REPORT", "BACK", wiz.confirm.token])

    def fake_input(_prompt=""):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    assert disk.display_name in text
    assert "CHECK DISKS AGAIN" in text or "DIAGNOSTIC" in text or "REPORT" in text
