# SPDX-License-Identifier: GPL-3.0-or-later
"""Blocked screens lead with the specific problem, not a generic Stop."""

from __future__ import annotations

from beamo_wipe import copy as C
from beamo_wipe.copy import blocked_heading_for


def _blocked_errors():
    from beamo_wipe import safety
    from beamo_wipe.app import STARTUP_BLOCKED

    return {
        C.IDENTIFY_ERROR: "identify the Beamo USB",
        safety.BOOT_APPEARED_SELECTABLE: "appeared as a disk to erase",
        safety.BOOT_APPEARED_ALIAS: "under two names",
        STARTUP_BLOCKED: "Startup was blocked",
        C.REDISCOVER_ERROR: "check the disks again",
    }


def test_every_blocked_error_has_unique_specific_heading():
    cases = _blocked_errors()
    headings = [blocked_heading_for(error) for error in cases]
    assert all(heading for heading in headings)
    assert len(set(headings)) == len(headings)
    for error, fragment in cases.items():
        heading = blocked_heading_for(error)
        assert fragment in heading, error
        assert heading != C.TITLE_BLOCKED
        assert len(heading) <= 60, heading


def test_heading_keys_match_source_constants():
    from beamo_wipe import safety
    from beamo_wipe.app import STARTUP_BLOCKED

    blocked_heading_for(C.IDENTIFY_ERROR)  # ensure lazy map is built
    assert set(C.BLOCKED_HEADINGS) == {
        C.IDENTIFY_ERROR,
        safety.BOOT_APPEARED_SELECTABLE,
        safety.BOOT_APPEARED_ALIAS,
        STARTUP_BLOCKED,
        C.REDISCOVER_ERROR,
    }


def test_unknown_and_empty_errors_fall_back_safely():
    assert blocked_heading_for("some future failure") == ""
    # Empty error renders the identify explanation, so the heading matches it.
    assert blocked_heading_for("") == blocked_heading_for(C.IDENTIFY_ERROR)
    assert blocked_heading_for(None) == blocked_heading_for(C.IDENTIFY_ERROR)


def test_headings_follow_session_language():
    from beamo_wipe import lang

    try:
        lang.set_language("fr")
        assert "Beamo" in blocked_heading_for(C.IDENTIFY_ERROR)
        assert (
            blocked_heading_for(C.IDENTIFY_ERROR)
            != "We could not identify the Beamo USB"
        )
        lang.set_language("de")
        assert "Beamo" in blocked_heading_for(C.IDENTIFY_ERROR)
    finally:
        lang.set_language("en")
    assert (
        blocked_heading_for(C.IDENTIFY_ERROR) == "We could not identify the Beamo USB"
    )


def test_console_plain_blocked_leads_with_heading(monkeypatch, capsys):
    from beamo_wipe.models import DiscoveryResult, Screen
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.ui import console_wizard as console

    wiz = make_demo_wizard()
    wiz.preview = False
    wiz.discovery = DiscoveryResult(error=C.IDENTIFY_ERROR)
    wiz.error = C.IDENTIFY_ERROR
    wiz.screen = Screen.PICK_BLOCKED
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    heading = blocked_heading_for(C.IDENTIFY_ERROR)
    assert heading in text
    assert text.index(heading) < text.index(C.SEVERITY_ERROR)
    assert C.IDENTIFY_ERROR in text


def test_console_curses_blocked_leads_with_heading(monkeypatch):
    from test_console_parity import _draw

    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import DiscoveryResult, Screen

    wiz = make_demo_wizard()
    wiz.preview = False
    wiz.discovery = DiscoveryResult(error=C.IDENTIFY_ERROR)
    wiz.error = C.IDENTIFY_ERROR
    wiz.screen = Screen.PICK_BLOCKED
    shown, _, _ = _draw(monkeypatch, wiz)
    heading = blocked_heading_for(C.IDENTIFY_ERROR)
    assert heading in shown
    assert shown.index(heading) < shown.index(C.SEVERITY_ERROR)


def test_gallery_blocked_title_is_specific():
    import json

    from beamo_wipe import gallery

    html = gallery.gallery_html("en")
    heading = blocked_heading_for(C.IDENTIFY_ERROR)
    assert f'"blocked": {json.dumps(heading)}' in html
    assert f'"blocked": {json.dumps(C.TITLE_BLOCKED)}' not in html
