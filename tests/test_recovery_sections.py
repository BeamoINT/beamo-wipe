# SPDX-License-Identifier: GPL-3.0-or-later
"""#107: failures use What happened / meaning / next, with technical separate.

Fails on the original blob layout. Fake devices only; no nwipe.
"""

from __future__ import annotations

from beamo_wipe import copy as C
from beamo_wipe import diagnostic_report as D
from beamo_wipe import recovery as R
from beamo_wipe.outcomes import VIEWS, preview_view
from beamo_wipe.support_export import (
    EXPORT_NEXT_STEPS,
    USB_FAT32_ONLY,
    USB_MUST_BE_WRITABLE,
    EVIDENCE_MALFORMED,
    next_step_for,
)


def test_every_failed_outcome_maps_three_sections():
    missing = []
    for code, view in VIEWS.items():
        sections = R.recovery_for_view(view)
        if view.success:
            assert sections is None, code
            continue
        if sections is None:
            missing.append(code)
            continue
        assert sections.happened == view.message, code
        assert sections.meaning, code
        assert sections.next_step == view.next_step, code
        assert view.code in sections.technical, code
        assert R.RECOVERY_HAPPENED in R.format_recovery_text(sections)
        assert R.RECOVERY_MEANING in R.format_recovery_text(sections)
        assert R.RECOVERY_NEXT in R.format_recovery_text(sections)
        text = R.format_recovery_text(sections, include_technical=True)
        assert R.RECOVERY_TECHNICAL in text
        assert sections.happened in text and sections.meaning in text
        if code in {"start_failed", "open_failed", "geometry_unusable"}:
            assert "unchanged" in sections.meaning.lower()
        if code == "stop_unconfirmed":
            assert "may still be running" in sections.meaning.lower()
            assert "Do not start another erase" in sections.meaning
        if code == "occupied":
            assert "not confirmed erased" in sections.meaning.lower()
    assert missing == []


def test_success_outcomes_do_not_use_recovery_sections():
    assert R.recovery_for_view(VIEWS["verified"]) is None
    assert R.recovery_for_view(VIEWS["unverified"]) is None


def test_nothing_erased_outcomes_never_claim_erasure():
    for code in ("start_failed", "open_failed", "geometry_unusable"):
        meaning = R.recovery_for_outcome(code).meaning.lower()
        assert "unchanged" in meaning
        assert "erased" in meaning
        assert "finished erase" not in meaning


def test_every_export_refusal_maps_and_keeps_detail():
    unmapped = []
    for detail in EXPORT_NEXT_STEPS:
        sections = R.recovery_for_export(detail)
        if not sections.happened:
            unmapped.append(detail)
            continue
        assert sections.happened == detail
        assert "does not change the erase result" in sections.meaning
        step = next_step_for(detail)
        if step:
            assert sections.next_step == step
        assert sections.technical
        assert "BEAMO_WIPE_EXPORT_FAIL_" in sections.technical
    assert unmapped == []
    fat = R.recovery_for_export(USB_FAT32_ONLY)
    assert "different USB stick" in fat.next_step
    support = R.recovery_for_export(EVIDENCE_MALFORMED)
    assert "contact support" in support.next_step.lower()
    diag = R.recovery_for_export(USB_MUST_BE_WRITABLE, diagnostic=True)
    assert "not erase evidence" in diag.meaning.lower()


def test_every_diagnostic_code_has_sections_and_error_code():
    for code in sorted(D.CODES):
        sections = R.recovery_for_diagnostic(code, message="live detail", step="do this")
        assert sections.happened == "live detail"
        assert "not erase evidence" in sections.meaning.lower()
        assert sections.next_step == "do this"
        assert code in sections.technical
    empty = R.recovery_for_diagnostic("discovery_failed")
    assert empty.happened == D.NOTICE
    assert empty.next_step == D.PREPARE


def test_blocked_and_empty_preserve_original_text():
    from beamo_wipe import safety
    from beamo_wipe.app import STARTUP_BLOCKED

    identify = R.recovery_for_blocked(C.IDENTIFY_ERROR)
    assert identify.happened == C.IDENTIFY_ERROR
    assert "protected" in identify.meaning.lower()
    assert "Unplug extra USB" in identify.next_step
    boot = R.recovery_for_blocked(safety.BOOT_APPEARED_SELECTABLE)
    assert boot.happened == safety.BOOT_APPEARED_SELECTABLE
    assert "Do not erase" in boot.next_step
    alias = R.recovery_for_blocked(safety.BOOT_APPEARED_ALIAS)
    assert alias.next_step == boot.next_step
    startup = R.recovery_for_blocked(STARTUP_BLOCKED)
    assert "diagnostic" in startup.next_step.lower()
    refresh = R.recovery_for_blocked(C.REDISCOVER_ERROR)
    assert "did not start" in refresh.next_step
    empty_error = R.recovery_for_blocked("")
    assert empty_error.happened == C.IDENTIFY_ERROR
    unknown = R.recovery_for_blocked("some future failure")
    assert unknown.happened == "some future failure"
    assert unknown.meaning == R.MEANING_BLOCKED
    recovered = R.recovery_for_blocked(C.IDENTIFY_ERROR, recovered=True)
    assert recovered.meaning == R.MEANING_UNCONFIRMED
    empty = R.recovery_for_empty()
    assert empty.happened == C.EMPTY_DISKS
    assert "bypass" in empty.meaning.lower()
    assert "contact support" in empty.next_step.lower()


def test_unknown_error_is_fail_closed_and_keeps_message():
    sections = R.recovery_for_unknown("exact mystery")
    assert sections.happened == "exact mystery"
    assert "did not confirm a finished erase" in sections.meaning.lower()
    assert "bypass" in sections.next_step.lower()
    blank = R.recovery_for_unknown("")
    assert blank.happened == R.MEANING_UNKNOWN


def test_evidence_save_failure_does_not_rewrite_erase_result():
    sections = R.recovery_for_evidence("permissions", "Temporary storage is not writable.")
    assert sections.happened == "Temporary storage is not writable."
    assert "unchanged" in sections.meaning.lower()
    assert "permissions" in sections.technical
    assert "shutdown" in sections.next_step.lower()


def test_screen_reader_order_is_happened_meaning_next_then_technical():
    text = R.format_recovery_text(
        R.recovery_for_outcome("engine_failed"), include_technical=True
    )
    assert text.index(R.RECOVERY_HAPPENED) < text.index(R.RECOVERY_MEANING)
    assert text.index(R.RECOVERY_MEANING) < text.index(R.RECOVERY_NEXT)
    assert text.index(R.RECOVERY_NEXT) < text.index(R.RECOVERY_TECHNICAL)
    customer = R.format_recovery_text(R.recovery_for_outcome("engine_failed"))
    assert R.RECOVERY_TECHNICAL not in customer
    assert "engine_failed" not in customer
    compact = R.format_recovery_text(
        R.recovery_for_outcome("engine_failed"),
        include_technical=True,
        compact=True,
    )
    assert compact.index(R.RECOVERY_HAPPENED) < compact.index(R.RECOVERY_MEANING)
    assert compact.index(R.RECOVERY_MEANING) < compact.index(R.RECOVERY_NEXT)
    assert compact.index(R.RECOVERY_NEXT) < compact.index(R.RECOVERY_TECHNICAL)
    assert "\n\n" not in compact
    assert f"{R.RECOVERY_HAPPENED}: {VIEWS['engine_failed'].message}" in compact


def test_labels_follow_session_language():
    from beamo_wipe import lang

    try:
        lang.set_language("fr")
        assert R.RECOVERY_HAPPENED == "Ce qui s’est passé"
        assert "disque" in R.RECOVERY_MEANING.lower()
        failed = R.recovery_for_outcome("engine_failed")
        assert "fichiers" in failed.meaning.lower()
        lang.set_language("de")
        assert "Datenträger" in R.RECOVERY_MEANING
        assert "Dateien" in R.recovery_for_outcome("engine_failed").meaning
    finally:
        lang.set_language("en")
    assert R.RECOVERY_HAPPENED == "What happened"
    assert R.RECOVERY_NEXT == "What to do next"


def test_console_plain_failure_uses_recovery_sections(monkeypatch, capsys):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.ui.console_wizard import _plain_loop
    from beamo_wipe.wizard import Wizard
    from test_outcome_heading import _done_wizard

    wiz = _done_wizard()
    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["engine_failed"]
        monkeypatch.setattr("builtins.input", lambda _: "SHUTDOWN")
        assert _plain_loop(wiz) == 0
    out = capsys.readouterr().out
    assert R.RECOVERY_HAPPENED in out
    assert R.RECOVERY_MEANING in out
    assert R.RECOVERY_NEXT in out
    assert out.index(R.RECOVERY_HAPPENED) < out.index(R.RECOVERY_MEANING)
    assert VIEWS["engine_failed"].message in out
    assert VIEWS["engine_failed"].next_step in out
    assert "engine_failed" in out


def test_curses_done_failure_keeps_report_status_on_first_page(monkeypatch):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.models import Screen, WipeResult
    from beamo_wipe.wizard import Wizard
    from test_console_parity import _at_pick, _draw

    wiz = _at_pick()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.preview = False
    wiz.screen = Screen.DONE
    wiz.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["engine_failed"]
        shown, _, term = _draw(monkeypatch, wiz)
    message = VIEWS["engine_failed"].message
    assert message in shown
    assert f"{R.RECOVERY_HAPPENED}:" in shown
    assert R.MEANING_MAY_REMAIN in shown
    assert VIEWS["engine_failed"].next_step in shown
    assert C.REPORT_STATUS_TITLE in shown
    assert shown.index(message) < shown.index(C.REPORT_STATUS_TITLE)
    last = term.frames[-1]
    assert max(last) < 24
    assert all(len(line) < 80 for line in last.values())


def test_console_plain_blocked_uses_recovery_sections(monkeypatch, capsys):
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import DiscoveryResult, Screen
    from beamo_wipe.ui import console_wizard as console

    wiz = make_demo_wizard()
    wiz.preview = False
    wiz.discovery = DiscoveryResult(error=C.IDENTIFY_ERROR)
    wiz.error = C.IDENTIFY_ERROR
    wiz.screen = Screen.PICK_BLOCKED
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    assert R.RECOVERY_HAPPENED in text
    assert C.IDENTIFY_ERROR in text
    assert R.MEANING_BLOCKED in text
    assert text.index(C.blocked_heading_for(C.IDENTIFY_ERROR)) < text.index(
        R.RECOVERY_HAPPENED
    )


def test_gallery_payload_includes_recovery_labels():
    import json

    from beamo_wipe import gallery

    html = gallery.gallery_html("en")
    assert json.dumps(R.RECOVERY_HAPPENED) in html
    assert json.dumps(R.RECOVERY_MEANING) in html
    assert json.dumps(R.RECOVERY_NEXT) in html
    assert "function recoveryHtml(" in html
    assert "recoveryHtml(P.blockedRecovery)" in html
    assert "recoveryHtml(P.emptyRecovery)" in html
    failed = R.recovery_for_view(preview_view(False))
    assert json.dumps(failed.meaning) in html
    blocked = R.recovery_for_blocked(C.IDENTIFY_ERROR)
    assert json.dumps(blocked.happened) in html
    assert json.dumps(blocked.meaning) in html
    # Original blob layout: a single unlabeled status paragraph.
    assert '<p class="statustext">${P.identify}</p>' not in html
    assert '<p class="statustext">${P.empty}</p>' not in html


def test_report_aftercare_error_uses_recovery_sections():
    text = C.report_aftercare(
        can_save=False, status="error", message=USB_FAT32_ONLY
    )
    assert R.RECOVERY_HAPPENED in text
    assert USB_FAT32_ONLY in text
    assert R.MEANING_REPORT_ONLY in text
    assert "different USB stick" in text
    assert C.EXPORT_GUIDE_RETRY in text
    assert C.REPORT_VOLATILE in text
    # Failures stay stage-free.
    for stage in C.EXPORT_STAGES:
        assert stage not in text


def test_result_summary_failure_includes_recovery_fields():
    from beamo_wipe.result_summary import build_result_summary
    from test_result_presentations import CASES, case_evidence

    case = next(c for c in CASES if c[0] == "engine_failed")
    _, ev, _ = case_evidence(case)
    text = build_result_summary(ev, evidence_sha256="a" * 64)
    assert f"{R.RECOVERY_HAPPENED}: {VIEWS['engine_failed'].message}" in text
    assert f"{R.RECOVERY_MEANING}: {R.MEANING_MAY_REMAIN}" in text
    assert f"{R.RECOVERY_NEXT}: {VIEWS['engine_failed'].next_step}" in text
    verified = next(c for c in CASES if c[0] == "verified")
    _, ok_ev, _ = case_evidence(verified)
    ok = build_result_summary(ok_ev, evidence_sha256="a" * 64)
    assert f"{R.RECOVERY_HAPPENED}:" not in ok


def test_helper_explains_three_recovery_sections():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    en = (root / "helper/index.html").read_text(encoding="utf-8")
    assert 'id="error-recovery"' in en
    assert R.RECOVERY_HAPPENED in en
    assert R.RECOVERY_MEANING in en
    assert R.RECOVERY_NEXT in en
    assert R.RECOVERY_TECHNICAL in en
    fr = (root / "helper/fr.html").read_text(encoding="utf-8")
    de = (root / "helper/de.html").read_text(encoding="utf-8")
    assert 'id="error-recovery"' in fr and 'id="error-recovery"' in de
    assert "Ce qui s’est passé" in fr
    assert "Was geschehen ist" in de
