# SPDX-License-Identifier: GPL-3.0-or-later
"""Erase outcomes and report transport have independent customer meanings."""
import copy
import json
from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.evidence import write_evidence_atomic
from beamo_wipe.outcomes import VIEWS
from beamo_wipe.support_export import _bundle_files
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import ReportView
from test_result_presentations import CASES, case_evidence
from test_usb_report_workflow import _success_receipt

REPORT_STATES = ["idle", "saving", "saved", "error"]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("status", REPORT_STATES)
def test_report_state_never_changes_erase_or_receipt(case, status, monkeypatch, capsys):
    w, ev, log = case_evidence(case)
    before = copy.deepcopy(ev)
    w.report_status = status
    w.report_message = "Report copy detail."
    expected = VIEWS[case[0]]
    assert w.result_view == expected
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(w)
    output = capsys.readouterr().out
    assert output.index("Erase status") < output.index("Report status")
    assert w.report_view.tone == ("warn" if status == "error" else "info")
    assert w.report_view.headline in output
    assert C.REPORT_STATUS_NOTICE in output
    assert expected.message in output
    files = _bundle_files(json.dumps(ev).encode(), log.encode(), "complete")
    assert expected.announcement in files["README.txt"].decode()
    assert ev == before


@pytest.mark.parametrize("code", VIEWS)
@pytest.mark.parametrize("status", REPORT_STATES)
def test_all_result_vocabulary_and_report_styles_are_independent(code, status):
    erase = VIEWS[code]
    report = ReportView(0, status, "", "", status == "saving", False, None)
    assert report.tone in {"info", "warn"}
    assert report.headline.startswith("Report") or report.headline.startswith("Saving")
    assert erase == VIEWS[code]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("failure", ["copy", "check", "unmount", "checksum"])
def test_export_failure_then_retry_preserves_erase(case, failure, tmp_path):
    w, ev, _ = case_evidence(case)
    path = write_evidence_atomic(ev, log_dir=tmp_path)
    w.evidence_path = str(path)
    w.evidence = json.loads(path.read_text())
    w.evidence["provenance"]["verified"] = True
    w._evidence_written_for = w._result_evidence_key(w.wipe_result)
    before = w.result_view
    def exporter(**kwargs):
        receipt = _success_receipt(**kwargs)
        return {
            "copy": replace(receipt, ok=False),
            "check": replace(receipt, code="verification_failed"),
            "unmount": replace(receipt, safe_to_remove=False),
            "checksum": replace(receipt, evidence_sha256="0" * 64),
        }[failure]
    w._report_exporter = exporter
    w.save_report_to_usb()
    assert w.report_status == "error" and w.can_save_report
    assert w.result_view == before
    assert "safe to remove" not in w.report_message
    w._report_exporter = _success_receipt
    w.save_report_to_usb()
    assert w.report_status == "saved" and not w.can_save_report
    assert w.result_view == before
    assert "does not confirm erase success" in w.report_message


@pytest.mark.parametrize("status", REPORT_STATES)
@pytest.mark.parametrize("saving", [False, True])
def test_evidence_problem_has_report_specific_priority(status, saving):
    report = ReportView(0, status, "", "", False, False, "Cannot check evidence.", saving)
    assert report.headline == ("Preparing the report" if saving else "Report preparation could not be confirmed")
    assert report.tone == "warn"


def test_evidence_failure_headline_does_not_mix_in_report_save_status():
    w, _, _ = case_evidence(CASES[0])
    w.evidence_error = "Cannot save evidence."
    assert not w.result_view.success
    assert "report" not in w.result_view.message.replace("reported", "")
    assert "could not be confirmed" in w.result_view.message


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("status", REPORT_STATES)
@pytest.mark.parametrize("saving", [False, True])
def test_evidence_save_check_failure_stays_conservative(case, status, saving):
    w, _, _ = case_evidence(case)
    w.evidence_error = "Report evidence did not pass validation."
    w._evidence_saving = saving
    w.report_status = status
    assert not w.result_view.success
    assert not w.can_save_report
    assert w.report_view.headline == ("Preparing the report" if saving else "Report preparation could not be confirmed")
    assert w.report_view.tone == "warn"


def test_browser_preview_exposes_two_named_status_sections():
    from beamo_wipe.gallery import gallery_html
    html = gallery_html()
    assert '<section aria-labelledby="erase-status-heading">' in html
    assert '<h1 id="erase-status-heading">${P.eraseStatusTitle}</h1>' in html
    assert '<section aria-labelledby="report-status-heading">' in html
    assert '<h2 id="report-status-heading">${P.reportStatusTitle}</h2>' in html
    assert C.REPORT_PREVIEW in html
