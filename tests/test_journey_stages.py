# SPDX-License-Identifier: GPL-3.0-or-later
"""Journey chrome is Preparation / Erase / Result, not eight equal pages.

Fake disks only. Wipe percent stays on the working screen, not in the header.
"""

from __future__ import annotations

import inspect
import re

from beamo_wipe import copy as C
from beamo_wipe.gallery import gallery_html
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.ui import tk_wizard as tkui
from beamo_wipe.wizard import format_progress_percent
from test_tk_runtime import ui, _drive_to  # noqa: F401


EQUAL_EIGHT = (
    "Start",
    "Owner",
    "Disk",
    "Confirm",
    "Method",
    "Review",
    "Erase",
    "Result",
)
STEP_OF_EIGHT = re.compile(r"Step [1-8] of 8")


def test_journey_is_three_unequal_stages_not_eight_equal_pages():
    assert C.JOURNEY_LABELS != EQUAL_EIGHT
    assert C.JOURNEY_LABELS == ("Preparation", "Erase", "Result")
    assert "Step 1 of 8" not in C.JOURNEY_LABELS
    source = inspect.getsource(tkui)
    assert "Step 1 of 8" not in source
    assert "Step 7 of 8" not in source
    html = gallery_html()
    assert "Step 1 of 8" not in html
    assert "Step 7 of 8" not in html
    assert STEP_OF_EIGHT.search(html) is None


def test_every_screen_maps_to_a_truthful_stage():
    prep = {
        Screen.KEYBOARD,
        Screen.WHAT,
        Screen.OWNER,
        Screen.PICK,
        Screen.DISK_HELP,
        Screen.PICK_EMPTY,
        Screen.PICK_BLOCKED,
        Screen.CONFIRM,
        Screen.METHOD,
        Screen.ADVANCED,
        Screen.LIMITS,
        Screen.LAST_CHANCE,
        Screen.CHECKING,
        Screen.REFRESHING,
        Screen.REPORT_HELP,
    }
    erase = {Screen.WORKING, Screen.STOPPING}
    result = {Screen.DONE}
    none = {
        Screen.SPLASH,
        Screen.SHUTDOWN_CONFIRM,
        Screen.DIAGNOSTIC,
        Screen.REFRESH_CONFIRM,
    }
    assert prep | erase | result | none == set(Screen)
    for screen in prep:
        assert C.journey_stage(screen) == C.JOURNEY_PREPARATION
        assert C.journey_caption(screen) == "Preparation"
        assert "%" not in C.journey_caption(screen)
    for screen in erase:
        assert C.journey_stage(screen) == C.JOURNEY_ERASE
        assert C.journey_caption(screen) == "Erase"
        assert C.journey_caption(screen) != format_progress_percent(50)
    for screen in result:
        assert C.journey_stage(screen) == C.JOURNEY_RESULT
        assert C.journey_caption(screen) == "Result"
    for screen in none:
        assert C.journey_stage(screen) == 0
        assert C.journey_caption(screen) == ""


def test_cancellation_and_failure_do_not_call_stopping_a_result():
    assert C.journey_stage(Screen.STOPPING) == C.JOURNEY_ERASE
    assert C.journey_stage(Screen.WORKING) == C.JOURNEY_ERASE
    assert C.journey_stage(Screen.DONE) == C.JOURNEY_RESULT
    html = gallery_html()
    assert "stop_confirm:[2,erase" in html.replace(" ", "")
    src = inspect.getsource(console)
    assert "journey_caption" in src


def test_tk_and_gallery_stage_indexes_match_and_are_not_percent_bars():
    for screen, (index, caption, _title) in tkui._STEP_ORDER.items():
        expected = C.journey_stage(screen)
        assert index == expected, screen
        if caption in C.JOURNEY_LABELS:
            assert caption == C.journey_caption(screen)
        assert "%" not in caption
        assert STEP_OF_EIGHT.search(caption) is None
    html = gallery_html()
    for label in C.JOURNEY_LABELS:
        assert label in html
    assert "/ 8 *" not in html
    assert "/ 8*" not in html
    strip = inspect.getsource(tkui.TkWizard._draw_strip)
    assert "/ 8" not in strip
    assert "len(C.JOURNEY_LABELS)" in strip or "JOURNEY_LABELS" in strip


def test_accessible_view_announces_stage_separately_from_wipe_percent():
    from pathlib import Path

    gtk_src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "beamo_wipe"
        / "ui"
        / "accessible_wizard.py"
    ).read_text(encoding="utf-8")
    assert "journey_announcement" in gtk_src or "journey_caption" in gtk_src
    assert C.journey_announcement(Screen.WORKING) == "Erase."
    assert C.journey_announcement(Screen.DONE) == "Result."
    assert "%" not in C.journey_announcement(Screen.WORKING)


def _header_texts(app):
    header = app._header
    return [
        str(header.itemcget(item, "text"))
        for item in header.find_all()
        if header.type(item) == "text"
    ]


def test_rendered_headers_name_preparation_erase_result_not_equal_pages(ui):  # noqa: F811
    wiz, app = ui(size=(1280, 820))
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    texts = _header_texts(app)
    assert "Preparation" in texts
    assert "Erase" in texts
    assert "Result" in texts
    assert all(" of 8" not in text and not text.startswith("Step ") for text in texts)
    assert wiz.screen == Screen.LAST_CHANCE
    wiz.screen = Screen.WORKING
    app._draw()
    app.root.update()
    texts = _header_texts(app)
    assert "Erase" in texts
    assert all(not text.endswith("%") for text in texts)
    wiz.screen = Screen.STOPPING
    app._draw()
    app.root.update()
    texts = _header_texts(app)
    assert "Erase" in texts
    assert "Result" in texts
    wiz.screen = Screen.DONE
    app._draw()
    app.root.update()
    texts = _header_texts(app)
    assert "Result" in texts
    assert all(" of 8" not in text for text in texts)


def test_curses_80x24_names_preparation_without_hiding_pick_count(monkeypatch):
    from test_console_parity import _at_pick, _draw

    wiz = _at_pick()
    shown, packed, _term = _draw(monkeypatch, wiz, h=24, w=80)
    assert "Preparation" in packed
    assert "3 disks available to erase" in packed
    assert wiz.selectable[0].serial in packed
    assert "Step 1 of 8" not in shown


def test_curses_16x48_keeps_count_when_journey_stage_cannot_fit(monkeypatch):
    from test_console_parity import _at_pick, _draw

    wiz = _at_pick()
    first = sorted(wiz.selectable, key=lambda d: d.path)[0]
    shown, packed, _term = _draw(monkeypatch, wiz, h=16, w=48)
    assert "3 disks available to erase" in packed
    assert first.serial in packed
    assert "same size" in shown.lower()
    assert "Step 1 of 8" not in shown