# SPDX-License-Identifier: GPL-3.0-or-later
"""#99: report-media requirements before erase. Fake devices only."""

from __future__ import annotations

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from test_console_parity import _draw


def _at_what():
    wiz = make_demo_wizard()
    wiz.skip_intro()
    assert wiz.screen == Screen.OWNER
    return wiz


def _at_pick(wanted: bool):
    wiz = make_demo_wizard()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    wiz.report_wanted = wanted
    return wiz


def test_what_notice_names_media_timing_and_refusal():
    assert "FAT32" in C.REPORT_MEDIA_WHAT
    assert "one volume" in C.REPORT_MEDIA_WHAT
    assert "unplugged" in C.REPORT_MEDIA_WHAT
    assert "asks for it" in C.REPORT_MEDIA_WHAT
    assert "already plugged in" in C.REPORT_MEDIA_WHAT
    assert "Need a report?" in C.REPORT_MEDIA_WHAT


def test_pick_notice_names_unplug_remedy_and_confusion():
    assert "unplugged" in C.REPORT_MEDIA_WANTED
    assert "already plugged in" in C.REPORT_MEDIA_WANTED
    assert "Check disks again" in C.REPORT_MEDIA_WANTED
    assert "confuse" in C.REPORT_MEDIA_WANTED


def test_full_requirements_stay_in_report_help():
    assert "FAT32" in C.REPORT_HELP_NEED
    assert "exFAT" in C.REPORT_HELP_NEED
    assert "FAT16" in C.REPORT_HELP_NEED
    assert "one writable, unmounted volume" in C.REPORT_HELP_NEED
    assert C.REPORT_HELP_NEED in C.REPORT_HELP_TEXT
    assert "remove only that" in C.REPORT_HELP_TEXT


def test_what_console_shows_media_notice(monkeypatch):
    shown, _, _ = _draw(monkeypatch, _at_what())
    assert C.REPORT_MEDIA_WHAT.split(".")[0] in shown


def test_what_plain_console_shows_media_notice(monkeypatch, capsys):
    wiz = _at_what()

    def fake_input(prompt=""):
        wiz.wants_shutdown = True
        return ""

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wiz)
    assert C.REPORT_MEDIA_WHAT in capsys.readouterr().out


@pytest.mark.parametrize("wanted", [True, False])
def test_pick_console_notice_follows_preference(monkeypatch, wanted):
    shown, _, _ = _draw(monkeypatch, _at_pick(wanted))
    assert (C.REPORT_MEDIA_WANTED.split(".")[0] in shown) == wanted


def test_pick_plain_console_notice_follows_preference(monkeypatch, capsys):
    wiz = _at_pick(True)
    calls = []

    def fake_input(prompt=""):
        calls.append(prompt)
        wiz.wants_shutdown = True
        return ""

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wiz)
    assert C.REPORT_MEDIA_WANTED in capsys.readouterr().out


def test_report_help_checkbox_still_drives_preference():
    wiz = _at_what()
    assert wiz.can_open_report_help
    wiz.open_report_help()
    assert wiz.screen == Screen.REPORT_HELP
    wiz.set_report_wanted(True)
    assert wiz.report_wanted
    wiz.close_report_help()
    assert wiz.screen == Screen.OWNER
    # Preference set directly is honored; the checkbox only works in help.
    wiz.set_report_wanted(False)
    assert wiz.report_wanted


def test_report_help_checkbox_toggles_by_keyboard(monkeypatch):
    wiz = _at_what()
    assert not wiz.report_wanted
    _draw(monkeypatch, wiz, keys=[ord("r"), ord(" ")])
    assert wiz.report_wanted
    wiz.wants_shutdown = False
    wiz.close_report_help()
    assert wiz.screen == Screen.OWNER
    _draw(monkeypatch, wiz, keys=[ord("r"), ord(" ")])
    assert not wiz.report_wanted


def test_gallery_embeds_preesase_notices():
    from beamo_wipe.gallery import gallery_html

    html = gallery_html()
    assert C.REPORT_MEDIA_WHAT in html
    assert C.REPORT_MEDIA_WANTED in html


def test_report_media_keys_translated_in_fr_and_de():
    from beamo_wipe.locales import de as de_locale
    from beamo_wipe.locales import fr as fr_locale

    for key in ("REPORT_MEDIA_WHAT", "REPORT_MEDIA_WANTED"):
        assert key in fr_locale.STRINGS["copy"]
        assert key in de_locale.STRINGS["copy"]
        assert fr_locale.STRINGS["copy"][key] != getattr(C, key)
        assert de_locale.STRINGS["copy"][key] != getattr(C, key)


def test_report_media_notices_follow_active_language():
    from beamo_wipe import lang

    try:
        lang.set_language("fr")
        assert "FAT32" in C.REPORT_MEDIA_WHAT
        assert "débranchée" in C.REPORT_MEDIA_WHAT or "débranché" in C.REPORT_MEDIA_WHAT
    finally:
        lang.set_language("en")


@pytest.mark.parametrize("name", ["index.html", "fr.html", "de.html"])
def test_helper_states_media_requirements_up_front(name):
    from beamo_wipe.gallery import project_root

    text = (project_root() / "helper" / name).read_text(encoding="utf-8")
    card = text.split('id="after-erasing"', 1)[0]
    markers = {
        "index.html": ("FAT32", "unplugged until"),
        "fr.html": ("FAT32", "débranchée jusqu"),
        "de.html": ("FAT32", "abgezogen, bis"),
    }[name]
    for marker in markers:
        assert marker in card
