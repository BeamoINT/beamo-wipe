# SPDX-License-Identifier: GPL-3.0-or-later
"""#100: staged report-export guidance. Fake devices only."""

from __future__ import annotations

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from test_console_parity import _draw
from test_result_presentations import CASES, case_evidence
from test_usb_report_workflow import (
    _done_wizard as _eligible_wizard,
)
from test_usb_report_workflow import (
    _success_receipt as _ok_receipt,
)


def _done_wizard(case=CASES[0]):
    wiz, _, _ = case_evidence(case)
    assert wiz.screen == Screen.DONE
    return wiz


def test_export_stages_name_five_steps_in_order():
    assert C.EXPORT_STAGES == (
        C.EXPORT_STAGE_INSERT,
        C.EXPORT_STAGE_CHECK,
        C.EXPORT_STAGE_SAVE,
        C.EXPORT_STAGE_VERIFY,
        C.EXPORT_STAGE_REMOVE,
    )


def test_idle_marks_insert_now():
    lines = C.export_stage_lines("idle").splitlines()
    assert len(lines) == 5
    assert lines[0].startswith("1. ") and "(now)" in lines[0]
    assert all("(done)" not in line and "(now)" not in line for line in lines[1:])


def test_saving_marks_insert_done_and_middle_band_now():
    lines = C.export_stage_lines("saving").splitlines()
    assert "(done)" in lines[0]
    assert all("(now)" in line for line in lines[1:4])
    assert "(now)" not in lines[4] and "(done)" not in lines[4]


def test_saved_marks_all_done_but_removal_now():
    lines = C.export_stage_lines("saved").splitlines()
    assert all("(done)" in line for line in lines[:4])
    assert "(now)" in lines[4]


def test_idle_aftercare_stages_insert_guidance():
    text = C.report_aftercare(can_save=True, status="idle", message="")
    assert C.EXPORT_STAGE_INSERT in text
    assert C.EXPORT_STAGE_REMOVE in text
    assert C.REPORT_INSERT in text
    assert C.REPORT_VOLATILE in text


def test_saving_aftercare_stages_working_guidance():
    text = C.report_aftercare(can_save=False, status="saving", message="Saving x")
    assert "(done)" in text and "(now)" in text
    assert "Saving x" in text
    assert "couple of minutes" in text
    assert "Do not remove" in text


def test_saved_aftercare_stages_then_receipt_verbatim():
    receipt = "Report saved and verified on X. The report USB is safe to remove."
    text = C.report_aftercare(can_save=False, status="saved", message=receipt)
    assert text.endswith(receipt)
    assert C.EXPORT_STAGE_REMOVE in text
    assert "(done)" in text


def test_error_aftercare_has_no_stages_no_promises():
    text = C.report_aftercare(
        can_save=False, status="error", message="Report USB was removed."
    )
    assert "removed" in text and C.REPORT_VOLATILE in text
    assert "Insert" not in text and "safe to remove" not in text
    assert "Save report to USB again" in text


def test_unavailable_aftercare_unchanged():
    text = C.report_aftercare(can_save=False, status="idle", message="")
    assert text == C.REPORT_EXPORT_UNAVAILABLE + " " + C.REPORT_VOLATILE


def test_done_console_pages_full_stage_block(monkeypatch, tmp_path):
    import curses

    wiz = _eligible_wizard(lambda **kw: _ok_receipt(**kw), tmp_path)
    assert wiz.report_view.can_save
    _, _, term = _draw(
        monkeypatch, wiz, keys=[curses.KEY_DOWN] * 6, sizes=[(24, 80)] * 8
    )
    all_text = " ".join(
        " ".join(frame[y] for y in sorted(frame)) for frame in term.frames
    )
    for stage in C.EXPORT_STAGES:
        assert stage in all_text


def test_done_console_narrow_pages_full_stage_block(monkeypatch, tmp_path):
    import curses

    wiz = _eligible_wizard(lambda **kw: _ok_receipt(**kw), tmp_path)
    _, _, term = _draw(
        monkeypatch,
        wiz,
        keys=[curses.KEY_DOWN] * 10,
        sizes=[(24, 60)] * 12,
    )
    all_text = " ".join(
        " ".join(frame[y] for y in sorted(frame)) for frame in term.frames
    )
    for stage in C.EXPORT_STAGES:
        assert stage in all_text
    assert C.REPORT_VOLATILE in all_text
    assert all(max(frame) < 24 for frame in term.frames if frame)


def test_done_console_saved_marks_removal_now(monkeypatch, tmp_path):
    import curses

    wiz = _eligible_wizard(lambda **kw: _ok_receipt(**kw), tmp_path)
    wiz.save_report_to_usb()
    assert wiz.report_view.status == "saved"
    shown, packed, term = _draw(
        monkeypatch, wiz, keys=[curses.KEY_DOWN] * 12
    )
    all_text = " ".join(
        " ".join(frame[y] for y in sorted(frame)) for frame in term.frames if frame
    )
    assert C.EXPORT_STAGE_REMOVE in all_text
    assert "safe to remove" in all_text
    view = wiz.disk_view(wiz.selected) if wiz.selected else None
    if view is not None:
        assert view.id_value in all_text


def test_done_console_error_shows_retry_without_stages(monkeypatch, tmp_path):
    from beamo_wipe.safety import SafetyError

    def exporter(**kw):
        raise SafetyError("Report USB was removed.")

    wiz = _eligible_wizard(exporter, tmp_path)
    wiz.save_report_to_usb()
    assert wiz.report_view.status == "error"
    shown, _, _ = _draw(monkeypatch, wiz)
    assert "Report USB was removed." in shown
    assert "Save report to USB again" in shown
    assert C.EXPORT_STAGE_INSERT not in shown


def test_done_plain_console_shows_stages(monkeypatch, capsys, tmp_path):
    wiz = _eligible_wizard(lambda **kw: _ok_receipt(**kw), tmp_path)

    def fake_input(prompt=""):
        wiz.wants_shutdown = True
        return "NOPE"

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wiz)
    visible = capsys.readouterr().out
    assert C.EXPORT_STAGE_INSERT in visible


def test_export_stages_follow_active_language():
    from beamo_wipe import lang

    try:
        lang.set_language("de")
        assert C.EXPORT_STAGES[0] == C.EXPORT_STAGE_INSERT
        assert C.EXPORT_STAGE_INSERT.startswith("Stecken")
        assert "(done)" not in C.export_stage_lines("saved")
    finally:
        lang.set_language("en")
    assert C.EXPORT_STAGES[0] == "Insert the report USB"


def test_retry_guidance_matches_save_button_label():
    assert C.BTN_SAVE_REPORT in C.EXPORT_GUIDE_RETRY


def test_gallery_done_card_shows_stages():
    from beamo_wipe.gallery import gallery_html

    html = gallery_html()
    for stage in C.EXPORT_STAGES:
        assert stage in html


def test_export_stage_keys_translated_in_fr_and_de():
    from beamo_wipe.locales import de as de_locale
    from beamo_wipe.locales import fr as fr_locale

    keys = (
        "EXPORT_STAGE_INSERT",
        "EXPORT_STAGE_CHECK",
        "EXPORT_STAGE_SAVE",
        "EXPORT_STAGE_VERIFY",
        "EXPORT_STAGE_REMOVE",
        "EXPORT_GUIDE_WORKING",
        "EXPORT_GUIDE_RETRY",
        "REPORT_HELP_STAGES",
    )
    for key in keys:
        assert key in fr_locale.STRINGS["copy"]
        assert key in de_locale.STRINGS["copy"]
        assert fr_locale.STRINGS["copy"][key] != getattr(C, key)
        assert de_locale.STRINGS["copy"][key] != getattr(C, key)


@pytest.mark.parametrize("name", ["index.html", "fr.html", "de.html"])
def test_helper_explains_export_stages(name):
    from beamo_wipe.gallery import project_root

    text = (project_root() / "helper" / name).read_text(encoding="utf-8")
    assert 'id="saving-report"' in text
    card = text.split('id="saving-report"', 1)[1].split("</div>", 1)[0]
    markers = {
        "index.html": ("Insert", "Check", "Save", "Verify", "removal"),
        "fr.html": ("Insérez", "Vérif", "Enregistr", "Contrôl", "retrait"),
        "de.html": ("Stecken", "Prüf", "Speichern", "Verifizier", "Abziehen"),
    }[name]
    positions = [card.index(marker) for marker in markers]
    assert positions == sorted(positions)
