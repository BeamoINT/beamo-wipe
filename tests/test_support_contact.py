# SPDX-License-Identifier: GPL-3.0-or-later
"""Error screens carry a verified support destination, QR + offline text."""

from __future__ import annotations

import pytest

from beamo_wipe import copy as C
from beamo_wipe import support_contact as SC


def test_destination_single_source():
    from beamo_wipe import lang
    from beamo_wipe.support_export import README_SUPPORT

    assert SC.SUPPORT_SHORT == "beamosupport.com"
    assert SC.SUPPORT_URL == "https://" + SC.SUPPORT_SHORT
    assert SC.qr_payload() == SC.SUPPORT_URL
    assert SC.SUPPORT_SHORT in README_SUPPORT
    assert SC.SUPPORT_SHORT in lang.translated("fr", "support_export", "README_SUPPORT")
    assert SC.SUPPORT_SHORT in lang.translated("de", "support_export", "README_SUPPORT")
    assert SC.SUPPORT_SHORT in C.support_text()
    assert SC.SUPPORT_SHORT in C.support_lead()


def test_qr_matrix_deterministic_and_robust():
    first = SC.qr_matrix()
    assert first == SC.qr_matrix()
    assert first == SC.qr_matrix(SC.SUPPORT_URL)
    size = len(first)
    assert size == len(first[0]) and size >= 21
    # Quiet zone: 4-module light border all around.
    for row in list(range(4)) + list(range(size - 4, size)):
        assert not any(first[row]), row
    for row in first:
        assert not any(row[:4]) and not any(row[-4:])
    assert SC.qr_error_correction() == "H"


def test_qr_decodes_to_exact_url():
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    matrix = SC.qr_matrix()
    scale = 8
    canvas = np.full((len(matrix) * scale, len(matrix[0]) * scale), 255, dtype=np.uint8)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                canvas[y * scale : (y + 1) * scale, x * scale : (x + 1) * scale] = 0
    decoded = cv2.QRCodeDetector().detectAndDecode(canvas)
    assert decoded[0] == SC.SUPPORT_URL


def test_view_support_map():
    from beamo_wipe.outcomes import VIEWS, view_needs_support

    for code in VIEWS:
        if code in ("verified", "unverified"):
            assert not view_needs_support(code), code
        else:
            assert view_needs_support(code), code
    assert not view_needs_support("no_such_code")


def test_trigger_strings_still_say_contact_support():
    from beamo_wipe import outcomes, safety  # noqa: F401 - ownership pins
    from beamo_wipe import wizard as W
    from beamo_wipe.support_export import NEXT_SUPPORT, NEXT_TRY_SUPPORT

    triggers = [
        outcomes.SUPPORT,
        outcomes.NEXT_START_FAILED,
        outcomes.NEXT_STOP_UNCONFIRMED,
        W.RECOVERY_MAY_RUNNING,
        W.KEEP_SESSION_OPEN,
        NEXT_TRY_SUPPORT,
        NEXT_SUPPORT,
        C.ACCESSIBLE_UNCONFIRMED,
        C.EMPTY_DISKS,
    ]
    for text in triggers:
        assert "contact support" in text.lower(), text
    # Occupied refers to support without the literal phrase (documented).
    assert "support" in outcomes.NEXT_OCCUPIED.lower()


def test_aftercare_error_appends_destination_for_support_steps():
    from beamo_wipe.support_export import (
        EVIDENCE_MALFORMED,
        USB_MUST_BE_WRITABLE,
    )

    text = C.report_aftercare(
        can_save=False, status="error", message=EVIDENCE_MALFORMED
    )
    assert SC.SUPPORT_SHORT in text
    assert "contact support" in text.lower()
    plain = C.report_aftercare(
        can_save=False, status="error", message=USB_MUST_BE_WRITABLE
    )
    assert SC.SUPPORT_SHORT not in plain


def test_support_step_detection():
    from beamo_wipe.support_export import (
        EVIDENCE_MALFORMED,
        NEXT_REPLUG,
        NEXT_SUPPORT,
        USB_META_INCOMPLETE,
        USB_MUST_BE_WRITABLE,
        next_step_for,
        next_step_needs_support,
    )

    assert next_step_for(EVIDENCE_MALFORMED) == NEXT_SUPPORT
    assert next_step_needs_support(EVIDENCE_MALFORMED)
    assert next_step_needs_support(USB_META_INCOMPLETE)
    assert next_step_for(USB_MUST_BE_WRITABLE) == NEXT_REPLUG
    assert not next_step_needs_support(USB_MUST_BE_WRITABLE)
    assert not next_step_needs_support("some unknown failure")


def test_diagnostic_step_support_suffix():
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.support_export import EVIDENCE_MALFORMED

    wiz = make_demo_wizard()
    wiz.preview = False
    wiz.diagnostic_message = EVIDENCE_MALFORMED
    assert SC.SUPPORT_SHORT in wiz.diagnostic_step
    wiz.diagnostic_message = "some unknown failure"
    assert wiz.diagnostic_step == ""


def test_console_done_fail_and_empty_show_destination(monkeypatch, capsys):
    from test_console_parity import _draw
    from test_result_presentations import CASES, case_evidence

    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import Screen

    wiz, _, _ = case_evidence(next(c for c in CASES if c[0] == "engine_failed"))
    shown, _, _ = _draw(monkeypatch, wiz)
    assert SC.SUPPORT_SHORT in shown
    empty = make_demo_wizard()
    empty.preview = False
    empty.screen = Screen.PICK_EMPTY
    shown, _, _ = _draw(monkeypatch, empty)
    assert SC.SUPPORT_SHORT in shown


def test_report_html_support_section_only_for_failures():
    from test_result_presentations import CASES, case_evidence

    from beamo_wipe.result_summary import build_result_report_html

    _, failed, _ = case_evidence(next(c for c in CASES if c[0] == "engine_failed"))
    page = build_result_report_html(failed)
    assert SC.SUPPORT_SHORT in page
    assert "<svg" in page
    dark = sum(sum(row) for row in SC.qr_matrix())
    assert page.count("<rect") - 1 == dark
    _, ok, _ = case_evidence(next(c for c in CASES if c[0] == "verified"))
    page = build_result_report_html(ok)
    assert SC.SUPPORT_SHORT not in page
    assert "<svg" not in page


def test_readme_and_gallery_name_destination():
    import json

    from test_result_presentations import CASES, case_evidence

    from beamo_wipe import gallery
    from beamo_wipe.support_export import _bundle_files

    html = gallery.gallery_html("en")
    assert SC.SUPPORT_SHORT in html
    assert "supportQr" in html
    _, ev, log = case_evidence(next(c for c in CASES if c[0] == "engine_failed"))
    raw = json.dumps(ev).encode()
    files = _bundle_files(raw, log.encode(), "complete")
    assert SC.SUPPORT_SHORT in files["README.txt"].decode()
    assert SC.SUPPORT_SHORT in files["REPORT.html"].decode()
