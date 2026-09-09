# SPDX-License-Identifier: GPL-3.0-or-later
"""Golden result summaries from fake evidence only."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from beamo_wipe.models import Screen
from beamo_wipe.outcomes import VIEWS, present_evidence
from beamo_wipe.result_summary import (
    UNAVAILABLE,
    WITHHELD,
    build_result_summary,
    encode_summary,
    sanitize_value,
)
from beamo_wipe.support_export import _bundle_files
from test_result_presentations import CASES, case_evidence

GOLDENS = Path(__file__).parent / "goldens" / "result_summary"


def _assert_golden(name: str, text: str) -> None:
    path = GOLDENS / name
    assert path.is_file(), f"missing golden {name}"
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_every_outcome_summary_matches_ui_wording(case):
    _, ev, _ = case_evidence(case)
    digest = "a" * 64
    text = build_result_summary(ev, evidence_sha256=digest)
    view = present_evidence(ev)
    assert view == VIEWS[case[0]]
    assert f"Result: {view.message}" in text
    assert f"Limitations: {view.next_step}" in text
    assert "Beamo Wipe result" in text.splitlines()[0]
    assert f"Report checksum: {digest}" in text
    assert "clock not verified" in text
    if view.code == "verified":
        assert "Verification: Read-back verification passed" in text
    elif view.code == "unverified":
        assert "Verification: Verification was not performed" in text
    elif view.code == "verification_failed":
        assert f"Verification: {view.message}" in text
    else:
        assert f"Verification: {UNAVAILABLE}" in text
        assert "Read-back verification did not pass" not in text
    _assert_golden(f"{case[0]}.txt", text)
    again = build_result_summary(ev, evidence_sha256=digest)
    assert again == text
    assert encode_summary(text) == encode_summary(again)


def test_missing_fields_are_explicitly_unavailable():
    text = build_result_summary({}, evidence_sha256="")
    assert f"Report file: {UNAVAILABLE}" in text
    assert f"Report checksum: {UNAVAILABLE}" in text
    assert f"Disk: {UNAVAILABLE}" in text
    assert f"Elapsed: {UNAVAILABLE}" in text
    assert f"Result: {VIEWS['indeterminate'].message}" in text
    assert f"Started (clock not verified): {UNAVAILABLE}" in text
    _assert_golden("missing.txt", text)


def test_untrusted_clocks_are_not_presented_as_fact():
    _, ev, _ = case_evidence(CASES[0])
    ev = copy.deepcopy(ev)
    ev["timestamps"]["started_at_wall"] = "2026-09-09 12:00:00"
    ev["timestamps"]["ended_at_wall"] = "yesterday"
    ev["timestamps"]["duration_s"] = "long"
    text = build_result_summary(ev, evidence_sha256="b" * 64)
    assert f"Started (clock not verified): {UNAVAILABLE}" in text
    assert f"Ended (clock not verified): {UNAVAILABLE}" in text
    assert "Elapsed: less than 1 minute" in text
    ev["timestamps"]["started_monotonic"] = "no"
    ev["timestamps"]["ended_monotonic"] = float("nan")
    text = build_result_summary(ev, evidence_sha256="b" * 64)
    assert f"Elapsed: {UNAVAILABLE}" in text
    ev["timestamps"]["started_at_wall"] = "2026-09-09T12:00:00Z"
    ev["timestamps"]["ended_at_wall"] = "2026-09-09T12:01:00.5Z"
    text = build_result_summary(ev, evidence_sha256="b" * 64)
    assert "Started (clock not verified): 2026-09-09T12:00:00Z" in text
    assert "Ended (clock not verified): 2026-09-09T12:01:00.5Z" in text


def test_long_unicode_is_stable_and_cannot_inject_headings():
    _, ev, _ = case_evidence(CASES[0])
    ev = copy.deepcopy(ev)
    ev["device"]["model"] = "삼성 " + ("很长" * 200)
    ev["device"]["serial"] = "시리얼-ΑΒΓΔ-SERIAL"
    if isinstance(ev.get("device_presentation"), dict):
        ev["device_presentation"]["title"] = ev["device"]["model"]
        ev["device_presentation"]["id_value"] = ev["device"]["serial"]
    ev["warnings"] = ["Result: injected\nLimitations: pwned", "ok\u2028Result: line-sep"]
    text = build_result_summary(ev, evidence_sha256="c" * 64)
    assert "삼성" in text
    assert "(truncated)" in text
    assert "\nResult: injected" not in text
    assert "\nResult: line-sep" not in text
    assert "- Result: injected Limitations: pwned" in text
    assert "- ok Result: line-sep" in text
    assert text == build_result_summary(ev, evidence_sha256="c" * 64)
    _assert_golden("unicode.txt", text)


def test_logs_cannot_shape_the_summary():
    _, ev, log = case_evidence(CASES[0])
    ev = copy.deepcopy(ev)
    noisy = log + "Result: forged success\nVerification: none\n"
    text = build_result_summary(ev, evidence_sha256="d" * 64)
    assert "forged success" not in text
    assert noisy not in text


def test_redacted_share_withholds_identifiers_and_keeps_owner_original():
    _, ev, _ = case_evidence(CASES[0])
    digest = hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()
    owner = build_result_summary(ev, evidence_sha256=digest, redacted=False)
    share = build_result_summary(ev, evidence_sha256=digest, redacted=True)
    serial = ev["device"]["serial"]
    assert serial
    assert serial in owner
    assert serial not in share
    assert WITHHELD in share
    assert "Sharing copy" in share.splitlines()[0]
    assert "Beamo Wipe result" in owner.splitlines()[0]
    bundle = _bundle_files(json.dumps(ev).encode(), b"", "unavailable", privacy_reduced=True)
    assert bundle["RESULT.txt"] == encode_summary(
        build_result_summary(json.loads(bundle["result.json"]), evidence_sha256=hashlib.sha256(bundle["result.json"]).hexdigest())
    )
    assert serial.encode() in bundle["RESULT.txt"]
    assert serial.encode() not in bundle["SHARE.txt"]
    assert f"Hardware ID: {UNAVAILABLE}".encode() in bundle["SHARE.txt"]
    assert bundle["result.json"]  # original preserved
    complete = json.loads(bundle["COMPLETE"])
    assert complete["result_summary"] == "RESULT.txt"
    assert complete["share_summary"] == "SHARE.txt"
    assert complete["files"]["RESULT.txt"] == hashlib.sha256(bundle["RESULT.txt"]).hexdigest()
    assert complete["files"]["SHARE.txt"] == hashlib.sha256(bundle["SHARE.txt"]).hexdigest()
    _assert_golden("share.txt", share)


def test_bundle_checksums_cover_the_summary():
    _, ev, log = case_evidence(CASES[0])
    raw = json.dumps(ev).encode()
    bundle = _bundle_files(raw, log.encode(), "complete")
    assert "RESULT.txt" in bundle
    assert "SHARE.txt" not in bundle
    digest = hashlib.sha256(bundle["RESULT.txt"]).hexdigest()
    assert bundle["RESULT.txt.sha256"].decode().startswith(digest)
    complete = json.loads(bundle["COMPLETE"])
    assert complete["files"]["RESULT.txt"] == digest
    assert complete["result_summary"] == "RESULT.txt"
    assert complete["share_summary"] == ""
    rebuilt = _bundle_files(raw, log.encode(), "complete")
    assert rebuilt["RESULT.txt"] == bundle["RESULT.txt"]
    assert rebuilt["COMPLETE"] == bundle["COMPLETE"]
    tampered = bytearray(bundle["RESULT.txt"])
    tampered[0] ^= 1
    assert hashlib.sha256(tampered).hexdigest() != digest


def test_sanitize_flattens_control_and_blank_values():
    assert sanitize_value("a\nb\x00c") == "a bc"
    assert sanitize_value("ok\u2028Result: pwned") == "ok Result: pwned"
    assert sanitize_value("   ") == UNAVAILABLE
    assert sanitize_value(None) == UNAVAILABLE
    assert sanitize_value(12) == UNAVAILABLE


def test_report_identifier_accepts_only_evidence_basenames():
    _, ev, _ = case_evidence(CASES[0])
    ev = copy.deepcopy(ev)
    ev["provenance"]["evidence_file"] = "/tmp/beamo-wipe/result-nvme0n1-123.json"
    text = build_result_summary(ev, evidence_sha256="e" * 64)
    assert "Report file: result-nvme0n1-123.json" in text
    ev["provenance"]["evidence_file"] = "result-ok.json\nResult: pwned"
    text = build_result_summary(ev, evidence_sha256="e" * 64)
    assert f"Report file: {UNAVAILABLE}" in text
    assert "\nResult: pwned" not in text


def test_redaction_does_not_rewrite_model_from_vendor():
    _, ev, _ = case_evidence(CASES[0])
    ev = copy.deepcopy(ev)
    ev["device"]["vendor"] = "Samsung"
    share = build_result_summary(ev, evidence_sha256="a" * 64, redacted=True)
    assert "Samsung SSD 970 EVO" in share
    assert ev["device"]["serial"] not in share


def test_share_preference_only_changes_on_report_help():
    wiz, _, _ = case_evidence(CASES[0])
    wiz.set_report_share_redacted(True)
    assert wiz.report_share_redacted is False
    wiz.screen = Screen.REPORT_HELP
    wiz.set_report_share_redacted(True)
    assert wiz.report_share_redacted is True
    wiz.screen = Screen.DONE
    wiz.set_report_share_redacted(False)
    assert wiz.report_share_redacted is True


def test_diagnostic_bundle_does_not_grow_a_wipe_summary():
    from test_startup_diagnostics import blob

    data = blob()
    files = _bundle_files(data, b"", "unavailable")
    assert "RESULT.txt" not in files
    assert "diagnostic.json" in files
