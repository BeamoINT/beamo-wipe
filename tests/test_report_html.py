# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline HTML erase report: escaped, accessible, printable, checksum-covered."""

from __future__ import annotations

import hashlib
import html as std_html
import json
from html.parser import HTMLParser

from beamo_wipe.result_summary import build_result_report_html, build_result_summary
from beamo_wipe.support_export import _bundle_files
from test_result_presentations import CASES, case_evidence


class _StrictParser(HTMLParser):
    def error(self, message):  # noqa: D102 - HTMLParser hook
        raise AssertionError(message)


def _bundle(case):
    _, ev, log = case_evidence(case)
    return ev, _bundle_files(json.dumps(ev).encode(), log.encode(), "complete")


def test_bundle_contains_report_html_covered_by_manifest_and_sidecar():
    _, files = _bundle(CASES[0])
    assert "REPORT.html" in files
    page = files["REPORT.html"]
    assert files["REPORT.html.sha256"] == (
        hashlib.sha256(page).hexdigest() + "  REPORT.html\n"
    ).encode("ascii")
    manifest = json.loads(files["COMPLETE"])
    assert manifest["files"]["REPORT.html"] == hashlib.sha256(page).hexdigest()
    assert "REPORT.html" in files["README.txt"].decode("utf-8")


def test_diagnostic_bundle_has_no_report_html():
    from beamo_wipe.diagnostic_report import NOTICE  # noqa: F401 - validates bundle type

    diagnostic = json.dumps(
        {
            "report_type": "startup_diagnostic",
            "title": "Startup diagnostic",
            "notice": "x",
            "checks": [],
            "detail": "x",
        }
    ).encode()
    try:
        files = _bundle_files(diagnostic, b"", "unavailable")
    except Exception:
        # validate_report enforces its own schema; only the file set matters here.
        return
    assert "REPORT.html" not in files


def test_html_matches_txt_values_for_every_outcome():
    for case in CASES:
        code = case[0]
        _, ev, log = case_evidence(case)
        raw = json.dumps(ev).encode()
        digest = hashlib.sha256(raw).hexdigest()
        files = _bundle_files(raw, log.encode(), "complete")
        txt = build_result_summary(ev, evidence_sha256=digest)
        page = files["REPORT.html"].decode("utf-8")
        for line in txt.splitlines()[1:]:
            if ": " not in line or line.startswith("- "):
                continue
            _, value = line.split(": ", 1)
            assert std_html.escape(value, quote=True) in page, (code, line)
        assert "<h1>Beamo Wipe result</h1>" in page, code


def test_hostile_metadata_is_escaped_and_parseable():
    _, ev, log = case_evidence(CASES[0])
    ev["device"]["model"] = '<script>alert("x")</script>'
    ev.setdefault("device_presentation", {})["title"] = "<b>disk & co</b>"
    ev["device"]["serial"] = 'a&b"<>\u2028run'
    ev["warnings"] = ["<img src=x onerror=alert(1)>", "ok & fine"]
    page = build_result_report_html(ev)
    assert "<script>" not in page
    assert "<img" not in page
    assert "<b>" not in page
    assert "&lt;b&gt;disk &amp; co&lt;/b&gt;" in page
    assert "a&amp;b&quot;&lt;&gt;" in page
    assert "ok &amp; fine" in page
    parser = _StrictParser(convert_charrefs=True)
    parser.feed(page)
    parser.close()


def test_missing_fields_render_unavailable_not_blank():
    page = build_result_report_html({})
    for label in ("Disk", "Method", "Elapsed", "Result", "Verification", "Limitations"):
        assert f'<th scope="row">{label}</th>' in page
    assert "unavailable" in page
    assert "<td></td>" not in page
    assert build_result_report_html("not-a-dict") == page


def test_offline_and_accessible_and_printable():
    page = build_result_report_html({})
    lowered = page.casefold()
    for forbidden in (
        "<script",
        "src=",
        "href=",
        "<link",
        "<img",
        "<iframe",
        "http://",
        "https://",
        "url(",
        "@import",
        "javascript:",
    ):
        assert forbidden not in lowered, forbidden
    assert '<html lang="en">' in page
    assert "<title>Beamo Wipe result</title>" in page
    assert "<main>" in page
    assert '<div class="table-wrap">' in page
    assert "@media print" in page


def test_share_warning_names_html_as_identifier_copy():
    from beamo_wipe.support_export import README_SHARE_HOW

    assert "REPORT.html" in README_SHARE_HOW
    assert "copy only SHARE.json and SHARE.txt" in README_SHARE_HOW


def test_html_follows_session_language_like_txt():
    from beamo_wipe import lang

    _, ev, _ = case_evidence(CASES[0])
    try:
        for code, caption in (
            ("fr", "Détails du rapport"),
            ("de", "Berichtsdetails"),
        ):
            lang.set_language(code)
            page = build_result_report_html(ev)
            assert f'<html lang="{code}">' in page, code
            assert std_html.escape(caption, quote=True) in page, code
            txt = build_result_summary(ev)
            assert txt.splitlines()[0] in page, code
    finally:
        lang.set_language("en")
    assert '<html lang="en">' in build_result_report_html(ev)
