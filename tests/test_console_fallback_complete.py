# SPDX-License-Identifier: GPL-3.0-or-later
"""Complete customer console fallback. Fake devices only; no real nwipe."""

from __future__ import annotations

from dataclasses import replace

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import Wizard
from test_console_parity import _at_pick, _draw, _footer, _long_list, replace_selectable


def test_display_wrap_keeps_every_cjk_character():
    token = "很长" * 40
    lines = console._lines(token, 40)
    assert "".join(lines) == token
    assert all(console._display_cols(line) <= 38 for line in lines)
    assert len(lines) > 1


def test_curses_chrome_uses_customer_title_not_screen_enum(monkeypatch):
    wiz = _at_pick()
    shown, packed, _term = _draw(monkeypatch, wiz)
    assert C.TITLE_PICK in shown
    assert C.APP_NAME in shown
    assert not any(row.strip() == f"{C.APP_NAME}   {Screen.PICK.value}" for row in _term.frames[-1].values())
    assert Screen.PICK.value not in " ".join(_term.frames[-1].values()).split()


def test_plain_loop_uses_customer_title(monkeypatch, capsys):
    wiz = _at_pick()
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    assert C.TITLE_PICK in text
    assert f"{C.APP_NAME} {Screen.PICK.value}" not in text


def test_identity_fields_are_separate_wrapped_lines(monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.selected = disk
    view = wiz.disk_view(disk)
    shown, packed, term = _draw(monkeypatch, wiz)
    assert view.title in shown
    assert view.capacity in shown
    assert f"{view.id_label}:" in packed or view.id_label in shown
    assert view.id_value in packed
    assert view.announcement not in "\n".join(term.frames[-1].values())


def test_long_ascii_serial_is_complete_across_wrapped_rows(monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    serial = "SERIAL-" + ("ABCDEFGHJK" * 12)
    assert len(serial) > 80
    wiz.selected = replace(disk, serial=serial)
    wiz.screen = Screen.CONFIRM
    shown, packed, term = _draw(
        monkeypatch, wiz, keys=[console.curses.KEY_DOWN] * 8, h=24, w=80
    )
    assert serial in packed
    assert all(console._display_cols(row) < 80 for row in term.frames[-1].values())
    assert "cannot get" in shown.lower() or "will be erased" in shown.lower()


def test_cjk_identity_wraps_to_display_columns(monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    model = "삼성 " + ("很长" * 40)
    serial = "시리얼-ΑΒΓΔ-" + ("한" * 36)
    wiz.selected = replace(disk, model=model, serial=serial)
    wiz.screen = Screen.CONFIRM
    shown, packed, term = _draw(
        monkeypatch, wiz, keys=[console.curses.KEY_DOWN] * 12, h=24, w=80
    )
    assert "삼성" in packed
    assert "시리얼" in packed
    assert serial in packed
    assert "很长" * 40 in packed
    last = term.frames[-1]
    assert all(console._display_cols(row) < 80 for row in last.values())
    assert max(last) < 24


def test_tall_selected_identity_pages_without_dropping_serial(monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    serial = "ID-" + ("Z" * 900)
    updated = replace(disk, serial=serial, model="Very long model " + ("M" * 40))
    peers = [updated if d.path == disk.path else d for d in wiz.selectable]
    wiz.discovery = replace_selectable(wiz, peers)
    wiz.selected = next(d for d in wiz.selectable if d.path == disk.path)
    shown, packed, term = _draw(
        monkeypatch,
        wiz,
        keys=[console.curses.KEY_NPAGE] * 8,
        h=24,
        w=80,
    )
    all_packed = "".join(
        "".join(frame.get(y, "") for y in sorted(frame)) for frame in term.frames
    )
    chunks = [serial[i:i + 40] for i in range(0, len(serial), 40)]
    assert all(chunk in all_packed for chunk in chunks)
    assert C.CON_MORE_DISKS_BELOW in all_packed or C.CON_MORE_BELOW in all_packed or serial in packed


def test_boot_identity_is_not_truncated_to_first_footer_line(monkeypatch):
    wiz = _at_pick()
    boot = wiz.protected_boot
    assert boot is not None
    serial = "BOOTSERIAL-" + ("Q" * 120)
    wiz.discovery = replace(
        wiz.discovery,
        boot=replace(boot, serial=serial, model="Beamo Live USB " + ("W" * 30)),
    )
    shown, packed, term = _draw(monkeypatch, wiz)
    all_packed = "".join(
        "".join(frame.get(y, "") for y in sorted(frame)) for frame in term.frames
    )
    assert serial in all_packed
    footer = _footer(term, rows=6)
    assert "B:" in footer or "identity" in footer.lower() or C.CON_PROTECTED_BOOT_MEDIA in shown


def test_short_terminal_keeps_shutdown_recovery_action(monkeypatch):
    wiz = make_demo_wizard(scenario="empty")
    wiz.preview = False
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK_EMPTY
    shown, packed, term = _draw(
        monkeypatch,
        wiz,
        keys=[console.curses.KEY_DOWN] * 8,
        sizes=[(12, 40)] * 10,
    )
    all_text = " ".join(" ".join(frame[y] for y in sorted(frame)) for frame in term.frames)
    assert "shut down" in all_text.lower()
    last_footer = _footer(term, rows=4)
    assert "shut down" in last_footer.lower() or "Enter" in last_footer
    support_lead = C.support_text().split(".")[0]
    assert support_lead.split()[0] in all_text or "More below" in all_text or support_lead in all_text
    assert all(console._display_cols(row) < 40 for frame in term.frames for row in frame.values())


def test_blocked_error_and_support_page_into_view(monkeypatch):
    from beamo_wipe.models import DiscoveryResult
    from beamo_wipe.nwipe_runner import DryRunRunner

    wiz = Wizard(
        DiscoveryResult(error="fake discovery", error_code="discovery_failed"),
        DryRunRunner(),
    )
    wiz.preview = False
    wiz.screen = Screen.PICK_BLOCKED
    shown, packed, term = _draw(
        monkeypatch, wiz, keys=[console.curses.KEY_DOWN] * 6, h=16, w=60
    )
    all_text = " ".join(" ".join(frame[y] for y in sorted(frame)) for frame in term.frames)
    assert C.blocked_title(wiz.error, recovered=wiz._recovered) in all_text
    assert (wiz.error or C.IDENTIFY_ERROR) in all_text
    assert "shut down" in _footer(term).lower()


def test_many_disks_paginate_without_hiding_later_serials(monkeypatch):
    wiz = _at_pick()
    many = _long_list(wiz, count=18)
    wiz.selected = many[0]
    shown, packed, term = _draw(
        monkeypatch, wiz, keys=[console.curses.KEY_NPAGE] * 12
    )
    all_packed = "".join(
        "".join(frame.get(y, "") for y in sorted(frame)) for frame in term.frames
    )
    assert many[0].serial in all_packed
    assert any(disk.serial in all_packed for disk in many[6:])
    assert C.CON_MORE_DISKS_BELOW in all_packed or many[-1].serial in all_packed


def test_done_keeps_retry_or_shutdown_on_narrow_terminal(monkeypatch):
    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.preview = False
    wiz.screen = Screen.DONE
    wiz.wipe_result = WipeResult(False, 1, "The wipe did not finish.", "/tmp/x.log")
    shown, packed, term = _draw(
        monkeypatch,
        wiz,
        keys=[console.curses.KEY_DOWN] * 4,
        sizes=[(16, 48)] * 6,
    )
    footer = " ".join(
        " ".join(frame.get(y, "") for y in range(max(0, 16 - 5), 16))
        for frame in term.frames
        if frame
    )
    assert "shut down" in footer.lower() or "retry" in footer.lower()
    assert wiz.result_view.message in " ".join(
        " ".join(frame[y] for y in sorted(frame)) for frame in term.frames if frame
    )


def test_add_does_not_drop_identity_characters_when_wrapping():
    serial = "S" * 120
    lines = console._lines(f"Serial: {serial}", 24)
    painted = "".join(lines)
    assert serial in painted
    assert all(console._display_cols(line) <= 22 for line in lines)
