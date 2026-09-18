# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #106: on-screen support code + build id when export cannot proceed.

Fake devices only. Never exec nwipe on a host disk.
"""

from __future__ import annotations

import pytest

from beamo_wipe import copy as C
from beamo_wipe import diagnostic_report as D
from beamo_wipe import lang
from beamo_wipe import support_export as E
from beamo_wipe import wizard as W
from beamo_wipe.models import DiscoveryResult, Screen, WipeResult
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.outcomes import VIEWS
from beamo_wipe.support_code import (
    BUILD_UNAVAILABLE,
    CODE_RE,
    EVIDENCE_TOKENS,
    OUTCOME_TOKENS,
    PHONE_ALPHABET,
    STARTUP_TOKENS,
    SupportIdentity,
    UNKNOWN,
    all_codes,
    code_for_evidence,
    code_for_export_detail,
    code_for_outcome,
    code_for_startup,
    contains_secrets,
    display_code,
    identity_for_wizard,
    is_progress_message,
    public_build_id,
    record_identity,
)
from beamo_wipe.wizard import Wizard
from test_rejection_next_steps import ALL_REFUSALS
from test_tk_runtime import descendants, ui  # noqa: F401

WIZARD_EXPORT_DETAILS = (
    W.NO_FINISHED_REPORT,
    W.EVIDENCE_UNREADABLE,
    W.REPORT_CHANGED_BEFORE_SAVE,
    W.EXPORT_FAILED,
    W.REPORT_NOT_SAVED,
    W.REPORT_CHANGED_DURING_SAVE,
    W.EXPORT_NO_START,
    W.DIAG_NO_PREVIEW,
    W.DIAG_NOT_SAVED,
    W.DIAG_CONTEXT_CHANGED,
    W.DIAG_FAILED,
    W.DIAG_NO_START,
    W.NO_EXPORT_EVIDENCE,
)

PRODUCTION_BUILD = "12345678-1234-1234-1234-123456789abc"


def _wizard(**kwargs) -> Wizard:
    discovery = kwargs.pop(
        "discovery",
        DiscoveryResult(
            error="We cannot tell which disk is this USB.",
            boot_identified=False,
            error_code=kwargs.pop("error_code", "boot_unidentified"),
            diagnostic="SERIAL_PRIVATE /dev/secret",
        ),
    )
    wiz = Wizard(discovery, DryRunRunner(), dry_run=True)
    wiz.preview = kwargs.pop("preview", False)
    for name, value in kwargs.items():
        setattr(wiz, name, value)
    return wiz


def test_codes_use_phone_safe_alphabet_and_stable_shape():
    forbidden = set("01IOL")
    codes = all_codes()
    assert UNKNOWN in codes
    assert len(codes) > 80
    for code in codes:
        assert CODE_RE.fullmatch(code), code
        body = code.split("-", 2)[2]
        assert not (set(body) & forbidden), code
        assert all(ch in PHONE_ALPHABET for ch in body), code
    assert display_code("") == UNKNOWN
    assert display_code("not-a-code") == UNKNOWN
    assert display_code("X-FAT") == "BW-X-FAT"


def test_assigned_codes_are_unique():
    from beamo_wipe import support_code as SC

    raw = (
        list(STARTUP_TOKENS.values())
        + list(OUTCOME_TOKENS.values())
        + list(EVIDENCE_TOKENS.values())
        + [token for _message, token in SC._export_pairs()]
    )
    displayed = [display_code(token) for token in raw]
    assert len(displayed) == len(set(displayed))
    assert UNKNOWN not in displayed
    assert all_codes() == frozenset(displayed) | {UNKNOWN}
    refusal_codes = [code_for_export_detail(detail) for detail in ALL_REFUSALS]
    assert len(refusal_codes) == len(set(refusal_codes))


def test_startup_outcome_and_evidence_vocabularies_are_closed():
    assert set(STARTUP_TOKENS) == set(D.CODES)
    assert set(OUTCOME_TOKENS) == set(VIEWS) - {"verified"}
    assert set(EVIDENCE_TOKENS) == {
        "permissions",
        "storage_full",
        "finalization",
        "invalid_data",
        "transient_io",
        "io",
    }
    for code in D.CODES:
        assert code_for_startup(code) != UNKNOWN
    for code in VIEWS:
        if code == "verified":
            assert code_for_outcome(code) == UNKNOWN
        else:
            assert code_for_outcome(code) != UNKNOWN
    for code in EVIDENCE_TOKENS:
        assert code_for_evidence(code) != UNKNOWN


@pytest.mark.parametrize("detail", ALL_REFUSALS)
def test_every_export_refusal_maps_to_a_distinct_code(detail):
    code = code_for_export_detail(detail)
    assert code != UNKNOWN, detail
    assert CODE_RE.fullmatch(code)
    assert not contains_secrets(code)


@pytest.mark.parametrize("detail", WIZARD_EXPORT_DETAILS)
def test_every_wizard_export_failure_maps(detail):
    assert code_for_export_detail(detail) != UNKNOWN


def test_progress_messages_are_not_refusals():
    assert is_progress_message(W.DIAG_CHECKING)
    assert is_progress_message(W.DIAG_VERIFYING)
    assert is_progress_message(W.REPORT_SAVING)
    ready = W.DIAG_BASELINE_READY.format(action=C.SAVE_DIAGNOSTIC_REPORT)
    assert is_progress_message(ready)
    assert code_for_export_detail(W.DIAG_CHECKING) == UNKNOWN
    assert not is_progress_message(E.USB_FAT32_ONLY)


def test_lookup_follows_current_language_constants_not_english_words():
    english = E.USB_FAT32_ONLY
    try:
        lang.set_language("fr")
        french = E.USB_FAT32_ONLY
        assert french != english
        assert code_for_export_detail(french) == "BW-X-FAT"
        assert code_for_export_detail(english) == UNKNOWN
        lang.set_language("de")
        german = E.USB_FAT32_ONLY
        assert german not in {english, french}
        assert code_for_export_detail(german) == "BW-X-FAT"
        assert C.SUPPORT_CODE_LABEL != "Support code"
        assert "BW-X-FAT" not in C.SUPPORT_CODE_LABEL
    finally:
        lang.set_language("en")
    assert code_for_export_detail(english) == "BW-X-FAT"
    assert C.SUPPORT_CODE_LABEL == "Support code"


def test_labels_translate_codes_and_build_id_do_not():
    ident = SupportIdentity(code="BW-X-FAT", build_id=PRODUCTION_BUILD, extra_code="BW-S-DSCV")
    english = ident.lines()
    try:
        lang.set_language("fr")
        french = ident.lines()
        lang.set_language("de")
        german = ident.lines()
    finally:
        lang.set_language("en")
    for blob in (english, french, german):
        assert "BW-X-FAT" in blob
        assert "BW-S-DSCV" in blob
        assert PRODUCTION_BUILD in blob
        assert not contains_secrets(blob)
    assert english != french != german
    assert ident.spoken_groups() == ("BW", "X", "FAT")


def test_redaction_never_embeds_disk_identity():
    ident = SupportIdentity(code="BW-S-DSCV", build_id=BUILD_UNAVAILABLE)
    text = C.support_identity_text(ident)
    secrets = ("SERIAL_PRIVATE", "/dev/secret", "password=secret")
    assert not contains_secrets(text, secrets)
    assert contains_secrets("see /dev/sda")
    assert contains_secrets("SERIAL_PRIVATE leaked", secrets)
    for code in all_codes():
        assert not contains_secrets(code, secrets)
    wiz = _wizard(screen=Screen.PICK_BLOCKED)
    blob = C.support_identity_text(identity_for_wizard(wiz))
    assert not contains_secrets(blob, secrets)


def test_build_id_comes_from_injection_not_env(monkeypatch):
    monkeypatch.setenv("BUILD_ID", "secret-from-env")
    monkeypatch.setattr(
        "beamo_wipe.build_identity.evidence_identity",
        lambda: {"build_id": "", "build_status": "unavailable"},
    )
    assert public_build_id() == BUILD_UNAVAILABLE
    monkeypatch.setattr(
        "beamo_wipe.build_identity.evidence_identity",
        lambda: {"build_id": PRODUCTION_BUILD, "build_status": "production"},
    )
    assert public_build_id() == PRODUCTION_BUILD
    ident = identity_for_wizard(_wizard(screen=Screen.PICK_BLOCKED))
    assert ident is not None
    assert ident.build_id == PRODUCTION_BUILD
    assert "secret-from-env" not in ident.lines()


def test_diagnostic_fat32_failure_shows_startup_and_save_codes(monkeypatch):
    """Regression: blocked diagnostic export used to show translated text only."""
    monkeypatch.setattr(
        "beamo_wipe.build_identity.evidence_identity",
        lambda: {"build_id": PRODUCTION_BUILD},
    )
    wiz = _wizard(
        screen=Screen.DIAGNOSTIC,
        startup_error_code="discovery_failed",
        diagnostic_message=E.USB_FAT32_ONLY,
        _diagnostic_from=Screen.PICK_BLOCKED,
    )
    ident = wiz.support_identity
    assert ident is not None
    assert ident.code == "BW-S-DSCV"
    assert ident.extra_code == "BW-X-FAT"
    assert ident.build_id == PRODUCTION_BUILD
    blob = C.support_identity_text(ident)
    assert "BW-S-DSCV" in blob and "BW-X-FAT" in blob
    assert PRODUCTION_BUILD in blob
    assert C.SUPPORT_CODE_HINT in blob
    assert E.USB_FAT32_ONLY not in ident.code
    assert "SERIAL_PRIVATE" not in blob


def test_progress_and_success_receipt_do_not_invent_a_save_code(monkeypatch):
    monkeypatch.setattr(
        "beamo_wipe.build_identity.evidence_identity",
        lambda: {"build_id": PRODUCTION_BUILD},
    )
    wiz = _wizard(
        screen=Screen.DIAGNOSTIC,
        startup_error_code="no_eligible_disks",
        diagnostic_message=W.DIAG_CHECKING,
        _diagnostic_from=Screen.PICK_EMPTY,
    )
    ident = identity_for_wizard(wiz)
    assert ident is not None
    assert ident.code == "BW-S-EMPTY"
    assert ident.extra_code == ""
    wiz.diagnostic_message = "Diagnostic report saved and verified on the report USB."
    ident = identity_for_wizard(wiz)
    assert ident is not None
    assert ident.extra_code == ""


def test_blocked_empty_what_and_done_visibility(monkeypatch):
    monkeypatch.setattr(
        "beamo_wipe.build_identity.evidence_identity",
        lambda: {"build_id": PRODUCTION_BUILD},
    )
    blocked = _wizard(screen=Screen.PICK_BLOCKED, startup_error_code="boot_unidentified")
    assert identity_for_wizard(blocked).code == "BW-S-BUND"
    empty = _wizard(
        screen=Screen.PICK_EMPTY,
        startup_error_code="",
        discovery=DiscoveryResult(boot_identified=True, error_code=""),
        error_code="",
    )
    assert identity_for_wizard(empty).code == "BW-S-EMPTY"
    what = _wizard(screen=Screen.WHAT, startup_error_code="graphical_unavailable")
    assert identity_for_wizard(what).code == "BW-S-GRAF"
    assert identity_for_wizard(_wizard(screen=Screen.WHAT, startup_error_code="")) is None
    done = _wizard(
        screen=Screen.DONE,
        preview=False,
        wipe_result=WipeResult(False, 1, "failed", "/tmp/beamo-wipe/nwipe.log"),
        report_status="error",
        report_message=E.USB_FAT32_ONLY,
    )
    ident = identity_for_wizard(done)
    assert ident is not None
    assert ident.code == "BW-X-FAT"
    preview = _wizard(screen=Screen.DONE, preview=True, report_status="error", report_message=E.USB_FAT32_ONLY)
    assert identity_for_wizard(preview) is None
    saved = _wizard(
        screen=Screen.DONE,
        preview=False,
        wipe_result=WipeResult(True, 0, "ok", "/tmp/beamo-wipe/nwipe.log"),
        report_status="saved",
        report_message="saved",
    )
    assert identity_for_wizard(saved) is None


def test_unretryable_evidence_failure_uses_family_e(monkeypatch):
    monkeypatch.setattr(
        "beamo_wipe.build_identity.evidence_identity",
        lambda: {"build_id": PRODUCTION_BUILD},
    )
    wiz = _wizard(
        screen=Screen.DONE,
        preview=False,
        wipe_result=WipeResult(False, 1, "failed", "/tmp/beamo-wipe/nwipe.log"),
        evidence_error=W.EVIDENCE_INVALID,
        evidence_error_code="invalid_data",
        report_status="idle",
    )
    ident = identity_for_wizard(wiz)
    assert ident is not None
    assert ident.code == "BW-E-DATA"


def test_log_correlation_records_code_and_serial_marker(monkeypatch):
    seen = []
    markers = []

    def fake_log(area, code, detail="", extra=None, **_kwargs):
        seen.append((area, code, detail, extra))
        return True

    monkeypatch.setattr("beamo_wipe.diagnostics.log_diag", fake_log)
    monkeypatch.setattr("beamo_wipe.diagnostics.emit_serial_marker", markers.append)
    ident = SupportIdentity(code="BW-X-FAT", build_id=PRODUCTION_BUILD, extra_code="BW-S-DSCV")
    record_identity(ident)
    assert seen == [
        ("support", "BW-X-FAT", PRODUCTION_BUILD, {"build": PRODUCTION_BUILD, "save": "BW-S-DSCV"})
    ]
    assert "BEAMO_WIPE_SUPPORT_X_FAT" in markers
    assert "BEAMO_WIPE_SUPPORT_S_DSCV" in markers


def test_gallery_and_helper_teach_the_on_screen_lines():
    from beamo_wipe.gallery import gallery_html, project_root

    html = gallery_html("en")
    assert "BW-S-BUND" in html
    assert "BW-S-EMPTY" in html
    assert C.SUPPORT_CODE_LABEL in html
    assert C.SUPPORT_BUILD_LABEL in html
    helper = (project_root() / "helper" / "index.html").read_text(encoding="utf-8")
    card = helper.split('id="saving-report"', 1)[1].split("</div>", 1)[0]
    assert "Support code" in card and "Build" in card
    assert "serials" in card.lower()


def test_tk_diagnostic_rejection_renders_code_and_build(ui):
    from test_tk_runtime import descendants
    import tkinter as tk

    _, app = ui()
    wiz = _wizard(
        screen=Screen.DIAGNOSTIC,
        startup_error_code="discovery_failed",
        diagnostic_message=E.USB_FAT32_ONLY,
        _diagnostic_from=Screen.PICK_BLOCKED,
    )
    app.w = wiz
    app._draw()
    app.root.update()
    labels = {w.cget("text") for w in descendants(app.root) if isinstance(w, tk.Label)}
    assert "BW-S-DSCV" in labels
    assert "BW-X-FAT" in labels
    assert C.SUPPORT_CODE_LABEL in labels
    assert C.SUPPORT_BUILD_LABEL in labels
    assert C.SUPPORT_CODE_HINT in labels
    assert E.USB_FAT32_ONLY in labels


def test_console_blocked_prints_support_code(monkeypatch, capsys):
    from beamo_wipe.ui import console_wizard as console

    wiz = _wizard(screen=Screen.PICK_BLOCKED, startup_error_code="boot_unidentified")
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    out = capsys.readouterr().out
    assert "BW-S-BUND" in out
    assert C.SUPPORT_CODE_LABEL in out
    assert C.SUPPORT_BUILD_LABEL in out
