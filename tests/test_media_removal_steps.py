# SPDX-License-Identifier: GPL-3.0-or-later
"""#98: explicit shutdown and USB-removal steps. Fake devices only."""

from __future__ import annotations

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import WAIT_REPORT_USB
from test_console_parity import _draw
from test_result_presentations import CASES, case_evidence

SHUTDOWN_CASES = [c for c in CASES if c[0] in {"verified", "engine_failed", "cancelled", "interrupted"}]


def _at_shutdown_confirm(case):
    wiz, _, _ = case_evidence(case)
    assert wiz.screen == Screen.DONE
    wiz.report_wanted = True
    wiz.shutdown()
    assert wiz.screen == Screen.SHUTDOWN_CONFIRM
    return wiz


def test_media_steps_name_every_medium_in_safe_order():
    steps = C.media_steps()
    ordered = (
        C.MEDIA_STEP_REPORT,
        C.MEDIA_STEP_STAY,
        C.MEDIA_STEP_BEAMO_OFF,
        C.MEDIA_STEP_RESTART,
        C.MEDIA_STEP_UNSURE,
    )
    positions = [steps.index(step) for step in ordered]
    assert positions == sorted(positions)
    assert "1." in steps.splitlines()[0]


def test_media_steps_cover_report_condition_and_beamo_removal_moment():
    steps = C.media_steps()
    assert "saved message" in steps
    assert "only after the computer is fully off" in steps
    assert "ends this session immediately" in steps
    assert "do not guess" in steps


def test_media_steps_erase_another_keeps_beamo_usb_for_next_erase():
    steps = C.media_steps(stay_in_session=True)
    assert C.MEDIA_STEP_ANOTHER in steps
    assert C.MEDIA_STEP_BEAMO_OFF not in steps


def test_wizard_exposes_shutdown_variant_by_default():
    wiz = _at_shutdown_confirm(CASES[0])
    assert wiz.exit_media_steps == C.media_steps(stay_in_session=False)


def test_wizard_exposes_stay_variant_for_erase_another():
    wiz = _at_shutdown_confirm(CASES[0])
    wiz.keep_report_session()
    assert wiz.screen == Screen.DONE
    assert wiz.can_erase_another
    wiz.erase_another_disk()
    assert wiz.screen == Screen.SHUTDOWN_CONFIRM
    assert wiz.exit_media_steps == C.media_steps(stay_in_session=True)


@pytest.mark.parametrize("case", SHUTDOWN_CASES, ids=[c[0] for c in SHUTDOWN_CASES])
def test_shutdown_confirm_console_shows_loss_and_steps(monkeypatch, case):
    wiz = _at_shutdown_confirm(case)
    shown, _, _ = _draw(monkeypatch, wiz)
    assert C.SHUTDOWN_LOSS in shown
    assert C.MEDIA_STEPS_TITLE in shown
    for step in (
        C.MEDIA_STEP_REPORT,
        C.MEDIA_STEP_STAY,
        C.MEDIA_STEP_BEAMO_OFF,
        C.MEDIA_STEP_RESTART,
        C.MEDIA_STEP_UNSURE,
    ):
        assert step.split(".")[0] in shown


def test_shutdown_confirm_console_pages_long_translations(monkeypatch):
    import curses

    from beamo_wipe import lang

    try:
        lang.set_language("de")
        wiz = _at_shutdown_confirm(CASES[0])
        _, _, term = _draw(monkeypatch, wiz, keys=[curses.KEY_DOWN] * 3)
        first = " ".join(term.frames[0][y] for y in sorted(term.frames[0]))
        last = " ".join(term.frames[-1][y] for y in sorted(term.frames[-1]))
        assert C.CON_MORE_BELOW in first
        assert "während der Computer aus ist" in last
        assert wiz.exit_confirmation_title in last
    finally:
        lang.set_language("en")


def test_shutdown_confirm_console_shows_stay_variant_for_erase_another(monkeypatch):
    wiz = _at_shutdown_confirm(CASES[0])
    wiz.keep_report_session()
    wiz.erase_another_disk()
    assert wiz.screen == Screen.SHUTDOWN_CONFIRM
    shown, _, _ = _draw(monkeypatch, wiz)
    assert C.MEDIA_STEP_ANOTHER.split(".")[0] in shown


def test_shutdown_confirm_plain_console_shows_steps(monkeypatch, capsys):
    wiz = _at_shutdown_confirm(CASES[0])
    calls = []

    def fake_input(prompt=""):
        calls.append(prompt)
        wiz.wants_shutdown = True
        return "NOPE"

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wiz)
    visible = capsys.readouterr().out
    assert "You asked to save a report" in visible
    assert C.MEDIA_STEPS_TITLE in visible
    assert C.MEDIA_STEP_BEAMO_OFF in visible


def test_export_in_progress_blocks_shutdown_with_wait_message():
    wiz, _, _ = case_evidence(CASES[0])
    wiz._report_exporting = True
    wiz.shutdown()
    assert wiz.screen == Screen.DONE
    assert not wiz.wants_shutdown
    assert wiz.report_message == WAIT_REPORT_USB


def test_working_blocks_shutdown_without_steps():
    wiz, _, _ = case_evidence(CASES[0])
    wiz.screen = Screen.WORKING
    wiz.shutdown()
    assert wiz.screen == Screen.WORKING
    assert not wiz.wants_shutdown


def test_no_report_keeps_direct_shutdown():
    wiz, _, _ = case_evidence(CASES[0])
    wiz.report_wanted = False
    wiz.shutdown()
    assert wiz.wants_shutdown


def test_gallery_payload_embeds_media_steps():
    from beamo_wipe.gallery import gallery_html

    html = gallery_html()
    assert '"mediaSteps"' in html
    assert C.MEDIA_STEP_BEAMO_OFF in html


def test_media_step_keys_translated_in_fr_and_de():
    from beamo_wipe.locales import de as de_locale
    from beamo_wipe.locales import fr as fr_locale

    keys = (
        "MEDIA_STEPS_TITLE",
        "MEDIA_STEP_REPORT",
        "MEDIA_STEP_STAY",
        "MEDIA_STEP_BEAMO_OFF",
        "MEDIA_STEP_RESTART",
        "MEDIA_STEP_UNSURE",
        "MEDIA_STEP_ANOTHER",
    )
    for key in keys:
        assert key in fr_locale.STRINGS["copy"]
        assert key in de_locale.STRINGS["copy"]
        assert fr_locale.STRINGS["copy"][key] != getattr(C, key)
        assert de_locale.STRINGS["copy"][key] != getattr(C, key)


def test_media_steps_follow_active_language():
    from beamo_wipe import lang

    try:
        lang.set_language("fr")
        assert C.MEDIA_STEP_BEAMO_OFF in C.media_steps()
        assert "totalement éteint" in C.media_steps()
    finally:
        lang.set_language("en")
    assert C.media_steps() == C.media_steps(stay_in_session=False)


@pytest.mark.parametrize("name", ["index.html", "fr.html", "de.html"])
def test_helper_lists_removal_steps_in_order(name):
    from beamo_wipe.gallery import project_root

    text = (project_root() / "helper" / name).read_text(encoding="utf-8")
    text = text.split('id="removing-usb"', 1)[1]
    markers = {
        "index.html": (
            "Report first",
            "fully off",
            "restart",
            "do not guess",
        ),
        "fr.html": (
            "rapport d’abord",
            "totalement éteint",
            "redémarrez",
            "ne devinez pas",
        ),
        "de.html": (
            "Bericht zuerst",
            "vollständig ausgeschaltet",
            "neu starten",
            "raten Sie nicht",
        ),
    }[name]
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions)
