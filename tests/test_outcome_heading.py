# SPDX-License-Identifier: GPL-3.0-or-later
"""#95: the specific erase outcome is the main heading.

Fake disks and canned evidence only; no subprocess or disk I/O.
"""

from __future__ import annotations

from beamo_wipe import copy as C
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.outcomes import VIEWS


def test_every_outcome_has_unique_message_and_severity():
    messages = [VIEWS[code].message for code in VIEWS]
    assert len(set(messages)) == len(messages)
    for code in VIEWS:
        view = VIEWS[code]
        assert view.tone in {"ok", "warn", "danger"}, code
        assert view.icon, code
        assert view.next_step, code
        assert view.announcement == f"{view.message}. {view.next_step}"


def test_verified_unverified_interrupted_failed_are_distinct():
    assert VIEWS["verified"].message != VIEWS["unverified"].message
    assert VIEWS["verified"].tone == "ok"
    assert VIEWS["unverified"].tone == "warn"
    assert VIEWS["cancelled"].tone == "warn"
    assert VIEWS["engine_failed"].tone == "danger"


def _done_wizard():
    from test_wizard_flow import _wiz

    wiz, _ = _wiz()
    wiz.preview = False
    wiz.screen = Screen.DONE
    wiz.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    return wiz


def test_curses_done_leads_with_outcome(monkeypatch):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.wizard import Wizard
    from test_console_parity import _at_pick, _draw

    for code in ("verified", "unverified", "cancelled", "engine_failed"):
        wiz = _at_pick()
        disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
        wiz.select_disk(disk.path)
        wiz.preview = False
        wiz.screen = Screen.DONE
        wiz.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
        with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
            view.return_value = VIEWS[code]
            shown, packed, term = _draw(monkeypatch, wiz)
        message = VIEWS[code].message
        assert message in shown, code
        assert "Erase status" not in shown, code
        assert shown.index(message) < shown.index(C.REPORT_STATUS_TITLE)
        last = term.frames[-1]
        assert max(last) < 24
        assert all(len(line) < 80 for line in last.values())


def test_plain_done_leads_with_outcome(monkeypatch, capsys):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.ui.console_wizard import _plain_loop
    from beamo_wipe.wizard import Wizard

    wiz = _done_wizard()
    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["engine_failed"]
        monkeypatch.setattr("builtins.input", lambda _: "SHUTDOWN")
        assert _plain_loop(wiz) == 0
    out = capsys.readouterr().out
    message = VIEWS["engine_failed"].message
    assert message in out
    assert "Erase status" not in out
    assert out.index(message) < out.index(C.REPORT_STATUS_TITLE)
    assert VIEWS["engine_failed"].next_step in out


def test_gallery_done_heading_is_outcome():
    from beamo_wipe import gallery

    html = gallery.gallery_html("en")
    assert '<h1 id="erase-status-heading">${result.message}</h1>' in html
    assert "P.eraseStatusTitle" not in html
    done_html = html.split('screen === "done"')[1].split("} else if")[0]
    assert "erase-status-heading" in done_html


def test_result_txt_and_readme_lead_with_specific_outcome():
    import json

    from beamo_wipe.result_summary import build_result_summary
    from beamo_wipe.support_export import _bundle_files
    from test_result_presentations import CASES, case_evidence

    for case in CASES:
        code = case[0]
        _, ev, log = case_evidence(case)
        expected = VIEWS[code]
        txt = build_result_summary(ev)
        assert f"Result: {expected.message}" in txt, code
        assert "Erase status" not in txt, code
        assert "Finished" not in txt, code
        files = _bundle_files(json.dumps(ev).encode(), log.encode(), "complete")
        readme = files["README.txt"].decode()
        assert readme.splitlines()[0] == expected.announcement, code


def test_failure_keeps_detail_and_report_separate():
    from test_result_presentations import CASES, case_evidence

    name = next(c[0] for c in CASES if c[0] == "engine_failed")
    wiz, _, _ = case_evidence(next(c for c in CASES if c[0] == name))
    wiz.report_status = "saved"
    assert wiz.result_view == VIEWS["engine_failed"]
    assert wiz.result_view.message != wiz.report_view.headline
    assert "support" in wiz.result_view.next_step.lower()
