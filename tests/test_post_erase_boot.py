# SPDX-License-Identifier: GPL-3.0-or-later
"""#97: explain post-erase computer behavior without guessing disk role.

Fake disks and canned views only; no subprocess or disk I/O.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from beamo_wipe import copy as C
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.outcomes import VIEWS

ROOT = Path(__file__).resolve().parent.parent

SHOWN = (
    "verified",
    "unverified",
    "verification_failed",
    "interrupted",
    "cancelled",
    "completion_missing",
    "process_failed",
    "engine_failed",
    "indeterminate",
    "stop_unconfirmed",
)
HIDDEN = ("start_failed", "occupied", "open_failed", "geometry_unusable")


def test_may_have_erased_mapping_is_exact():
    from beamo_wipe.outcomes import may_have_erased

    assert set(SHOWN) | set(HIDDEN) == set(VIEWS)
    for code in SHOWN:
        assert may_have_erased(code) is True, code
    for code in HIDDEN:
        assert may_have_erased(code) is False, code
    assert may_have_erased("preview") is False
    assert may_have_erased("bogus-code") is True
    assert may_have_erased("") is True


def test_note_is_conditional_and_never_guesses_role():
    note = C.POST_ERASE_BOOT
    assert "If this was the disk" in note
    assert "may not start" in note
    assert "may need to install" in note
    lowered = note.lower()
    assert "will not start" not in lowered
    assert "your operating system was erased" not in lowered
    assert "was the operating-system disk" not in lowered
    from test_copy import FORBIDDEN

    for phrase in FORBIDDEN:
        assert phrase not in lowered, phrase


def test_note_is_translated_without_role_guesses():
    from beamo_wipe import lang

    try:
        lang.set_language("fr")
        assert C.POST_ERASE_BOOT.startswith("Si ")
        assert "peut-être" in C.POST_ERASE_BOOT
        lang.set_language("de")
        assert C.POST_ERASE_BOOT.startswith("Wenn ")
        assert "möglicherweise" in C.POST_ERASE_BOOT
    finally:
        lang.set_language("en")


def _done_wizard():
    from test_wizard_flow import _wiz

    wiz, _ = _wiz()
    wiz.preview = False
    wiz.screen = Screen.DONE
    wiz.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    return wiz


def test_curses_done_shows_note_by_outcome(monkeypatch):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.wizard import Wizard
    from test_console_parity import _at_pick, _draw

    for code in SHOWN:
        wiz = _at_pick()
        disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
        wiz.select_disk(disk.path)
        wiz.preview = False
        wiz.screen = Screen.DONE
        wiz.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
        with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
            view.return_value = VIEWS[code]
            shown, _, term = _draw(monkeypatch, wiz)
        assert C.POST_ERASE_BOOT in shown, code
        assert shown.index(VIEWS[code].message) < shown.index(C.POST_ERASE_BOOT), code
        assert shown.index(C.POST_ERASE_BOOT) < shown.index(C.REPORT_STATUS_TITLE), code
        last = term.frames[-1]
        assert max(last) < 24
        assert all(len(line) < 80 for line in last.values())
    for code in HIDDEN:
        wiz = _at_pick()
        disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
        wiz.select_disk(disk.path)
        wiz.preview = False
        wiz.screen = Screen.DONE
        wiz.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
        with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
            view.return_value = VIEWS[code]
            shown, _, _ = _draw(monkeypatch, wiz)
        assert C.POST_ERASE_BOOT not in shown, code


def test_plain_done_shows_note_by_outcome(monkeypatch, capsys):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.ui.console_wizard import _plain_loop
    from beamo_wipe.wizard import Wizard

    for code in ("verified", "engine_failed", "cancelled", "interrupted"):
        wiz = _done_wizard()
        with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
            view.return_value = VIEWS[code]
            monkeypatch.setattr("builtins.input", lambda _: "SHUTDOWN")
            assert _plain_loop(wiz) == 0
        out = capsys.readouterr().out
        assert C.POST_ERASE_BOOT in out, code
    for code in HIDDEN:
        wiz = _done_wizard()
        with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
            view.return_value = VIEWS[code]
            monkeypatch.setattr("builtins.input", lambda _: "SHUTDOWN")
            assert _plain_loop(wiz) == 0
        out = capsys.readouterr().out
        assert C.POST_ERASE_BOOT not in out, code


def test_note_shows_for_internal_external_and_unknown_targets(monkeypatch):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.wizard import Wizard
    from test_console_parity import (
        _at_pick,
        _draw,
        replace_selectable,
    )

    for bus in ("SATA", "USB", ""):
        wiz = _at_pick()
        base = sorted(wiz.selectable, key=lambda d: d.path)[0]
        disk = replace(base, bus=bus)
        wiz.discovery = replace_selectable(wiz, [disk])
        wiz.select_disk(disk.path)
        wiz.preview = False
        wiz.screen = Screen.DONE
        wiz.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
        with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
            view.return_value = VIEWS["verified"]
            shown, _, _ = _draw(monkeypatch, wiz)
        assert C.POST_ERASE_BOOT in shown, bus


def test_gallery_done_omits_note_and_shows_message_once():
    from beamo_wipe import gallery

    html = gallery.gallery_html("en")
    assert C.POST_ERASE_BOOT not in html
    done_html = html.split('screen === "done"')[1].split("} else if")[0]
    assert done_html.count("${result.message}") == 1


def test_helper_after_erasing_card_in_every_language():
    from test_helper_boot_guidance import FORBIDDEN, _Doc

    for name, heading, conditional in (
        ("index.html", "If the computer does not start after erasing", "may "),
        (
            "fr.html",
            "Si l’ordinateur ne démarre pas après l’effacement",
            "peut",
        ),
        (
            "de.html",
            "Wenn der Computer nach dem Löschen nicht startet",
            "möglicherweise",
        ),
    ):
        raw = (ROOT / "helper" / name).read_text(encoding="utf-8")
        doc = _Doc()
        doc.feed(raw)
        assert "after-erasing" in doc.ids, name
        titles = [title for _, title in doc.headings]
        assert heading in titles, name
        levels = [level for level, _ in doc.headings]
        assert levels == sorted(levels), name
        card = raw.split('id="after-erasing"', 1)[1].split("</div>", 1)[0]
        assert conditional in card, name
        assert (
            "operating system" in card or "système" in card or "Betriebssystem" in card
        ), name
        lowered = card.lower()
        assert "will not start" not in lowered, name
        for phrase in FORBIDDEN:
            assert phrase not in lowered, (name, phrase)
