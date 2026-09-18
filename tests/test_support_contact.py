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


def _decode_qr_payload(matrix, scale: int) -> str:
    """Independent read-back. Prefer zbar; OpenCV is skipped when it cannot load."""
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode as zbar_decode
    except ImportError:
        zbar_decode = None
        Image = None
    if zbar_decode is not None:
        image = Image.new("L", (len(matrix[0]) * scale, len(matrix) * scale), 255)
        pixels = image.load()
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    for dy in range(scale):
                        for dx in range(scale):
                            pixels[x * scale + dx, y * scale + dy] = 0
        found = [item.data.decode() for item in zbar_decode(image)]
        assert found, "QR did not decode at this scale"
        return found[0]
    try:
        import cv2
        import numpy as np
    except ImportError:
        pytest.skip("no QR decoder (pyzbar/cv2)")
    canvas = np.full((len(matrix) * scale, len(matrix[0]) * scale), 255, dtype=np.uint8)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                canvas[y * scale : (y + 1) * scale, x * scale : (x + 1) * scale] = 0
    decoded = cv2.QRCodeDetector().detectAndDecode(canvas)
    assert decoded[0], "QR did not decode at this scale"
    return decoded[0]


def test_qr_decodes_to_exact_url():
    decoded = _decode_qr_payload(SC.qr_matrix(), 8)
    assert decoded == SC.SUPPORT_URL


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
    assert '<p tabindex="0">${P.supportLead}</p>' in html
    embedded = (
        json.dumps(SC.qr_svg())
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    assert embedded in html
    _, ev, log = case_evidence(next(c for c in CASES if c[0] == "engine_failed"))
    raw = json.dumps(ev).encode()
    files = _bundle_files(raw, log.encode(), "complete")
    assert SC.SUPPORT_SHORT in files["README.txt"].decode()
    assert SC.SUPPORT_SHORT in files["REPORT.html"].decode()


def test_qr_payload_is_https_url_with_no_session_data():
    from urllib.parse import urlparse

    parsed = urlparse(SC.qr_payload())
    assert parsed.scheme == "https"
    assert parsed.netloc == SC.SUPPORT_SHORT
    assert parsed.path in ("", "/")
    assert parsed.params == ""
    assert parsed.query == ""
    assert parsed.fragment == ""
    assert parsed.username is None
    assert parsed.password is None
    for token in ("/dev/", "serial", "session", "token", "log"):
        assert token not in SC.qr_payload()


def test_qr_readable_at_display_scale():
    """Phone-usable size as painted, not a larger test-only canvas."""
    assert SC.QR_DISPLAY_SCALE >= 3
    assert _decode_qr_payload(SC.qr_matrix(), SC.QR_DISPLAY_SCALE) == SC.SUPPORT_URL


def test_helper_and_boot_card_name_destination():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    svg = SC.qr_svg()
    for rel in ("helper/index.html", "helper/fr.html", "helper/de.html"):
        html = (root / rel).read_text(encoding="utf-8")
        assert SC.SUPPORT_SHORT in html, rel
        assert f'href="{SC.SUPPORT_URL}"' in html, rel
        assert svg in html, rel
        assert 'id="beamo-support"' in html, rel
        assert "<script" not in html
    card = (root / "docs/boot-card.md").read_text(encoding="utf-8")
    assert SC.SUPPORT_SHORT in card
    assert "contact support at" in card.lower()


def test_tk_support_text_is_keyboard_reachable():
    import tkinter as tk

    from beamo_wipe.models import Screen
    from beamo_wipe.ui.tk_wizard import TkWizard
    from test_result_presentations import CASES, case_evidence
    from test_tk_runtime import _needs_display

    _needs_display()
    wiz, _, _ = case_evidence(next(c for c in CASES if c[0] == "engine_failed"))
    wiz.preview = False
    wiz.screen = Screen.DONE
    app = TkWizard(wiz)
    try:
        app.root.geometry("1024x740+40+40")
        app._draw()
        app.root.update()
        lead = app._support_lead
        assert lead is not None
        # Visible and copyable, but not a Tab stop: Shut down → Show more
        # → Save report must stay two Tabs (QEMU).
        assert str(lead.cget("takefocus")) in {"", "0", "false"}
        assert SC.SUPPORT_SHORT in str(lead.cget("text"))
        wrap = int(float(lead.cget("wraplength") or 0))
        assert wrap >= 200
        assert wrap <= app.root.winfo_width()
        current = app.root.focus_get()
        for _ in range(2):
            current = current.tk_focusNext()
            assert current is not lead
        try:
            app.root.clipboard_clear()
            app.root.event_generate("<Control-c>")
            app.root.update_idletasks()
            assert app.root.clipboard_get() == SC.SUPPORT_SHORT
        except tk.TclError:
            pytest.skip("clipboard unavailable in this display")
    finally:
        app._teardown()
