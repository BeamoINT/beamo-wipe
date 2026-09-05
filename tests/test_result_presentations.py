# SPDX-License-Identifier: GPL-3.0-or-later
"""One result mapping from fake process output through reports and recovery."""

import copy
import json

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.evidence import build_evidence, recover_result, write_evidence_atomic
from beamo_wipe.models import MethodId, Screen, WipeResult
from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome
from beamo_wipe.outcomes import VIEWS, present_evidence
from beamo_wipe.support_export import _bundle_files
from beamo_wipe.ui import console_wizard as console


CASES = [
    ("verified", MethodId.EVERYDAY, 0, "{name} | Erased |", False, False),
    ("unverified", MethodId.QUICK_ZERO, 0, "{name} | Erased |", False, False),
    ("occupied", MethodId.EVERYDAY, 0, "{path} is reported as IN USE", False, False),
    (
        "open_failed",
        MethodId.EVERYDAY,
        0,
        "Unable to open device '{path}'.",
        False,
        False,
    ),
    (
        "geometry_unusable",
        MethodId.EVERYDAY,
        0,
        "No sane device geometry for '{path}'.",
        False,
        False,
    ),
    ("interrupted", MethodId.EVERYDAY, 143, "", True, False),
    ("cancelled", MethodId.EVERYDAY, 143, "", True, True),
    ("completion_missing", MethodId.EVERYDAY, 0, "", False, False),
    (
        "verification_failed",
        MethodId.EVERYDAY,
        1,
        "Verification mismatch on '{path}' at offset 4096",
        False,
        False,
    ),
    ("process_failed", MethodId.EVERYDAY, 2, "", False, False),
    ("engine_failed", MethodId.EVERYDAY, 0, "{path}: >>> FAILURE! <<<", False, False),
]


def test_every_canonical_result_has_a_supported_consistent_icon():
    for view in VIEWS.values():
        assert view.icon == ("check" if view.tone == "ok" else view.tone)
        assert view.icon in {"check", "info", "warn", "danger"}


def test_recovery_and_export_agree_on_normalized_engine_log(tmp_path):
    from beamo_wipe.support_export import read_export_log

    logfile = tmp_path / "nwipe.log"
    case = ("verified", MethodId.EVERYDAY, 0, "\ufffd\n{name} | Erased |", False, False)
    _, evidence, normalized_log = case_evidence(case, str(logfile))
    logfile.write_bytes(normalized_log.replace("\ufffd", "\xff").encode("latin-1"))
    path = write_evidence_atomic(evidence, log_dir=tmp_path)
    exported, status = read_export_log(
        str(logfile),
        expected_sha256=evidence["log_checksum_sha256"],
        expected_size_bytes=evidence["log_snapshot_size_bytes"],
    )
    assert status == "complete" and exported == normalized_log.encode()
    assert recover_result(path) == VIEWS["verified"]


def test_engine_start_error_keeps_technical_details_out_of_primary_message(
    tmp_path, monkeypatch
):
    from test_refresh_disks import authorized

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz = authorized()
    diagnostics = []
    monkeypatch.setattr(
        "beamo_wipe.diagnostics.log_diag", lambda *args: diagnostics.append(args)
    )

    def fail_start(_request):
        raise OSError(13, "fake low-level launch details")

    wiz.runner.start = fail_start
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE and wiz._wipe_request is None
    assert "fake low-level launch details" not in wiz.error
    assert "The erase could not start" in wiz.error
    assert any(entry[1] == "start_failed" and "13" in entry[2] for entry in diagnostics)


def case_evidence(case, logfile=""):
    code, method, exit_code, template, interrupted, cancelled = case
    wiz = make_demo_wizard()
    disk = wiz.selectable[0]
    log = template.format(name=disk.name, path=disk.path) + "\n"
    ok, detail, reason = evaluate_nwipe_outcome(exit_code, log, disk.path)
    result = WipeResult(ok, exit_code, detail, logfile, reason)
    ev = build_evidence(
        disk=disk,
        discovery=wiz.discovery,
        method=method,
        request=None,
        result=result,
        started_at_wall="",
        ended_at_wall="",
        started_mono=0,
        ended_mono=1,
        argv=[],
        log_text=log,
        interrupted=interrupted,
        cancelled=cancelled,
    )
    wiz.preview = False
    wiz.selected = disk
    wiz.method = method
    wiz.screen = Screen.DONE
    wiz.wipe_result = result
    wiz.evidence = ev
    return wiz, ev, log


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_every_reason_console_report_and_recovery(case, tmp_path, monkeypatch, capsys):
    logfile = tmp_path / "nwipe.log"
    wiz, ev, log = case_evidence(case, str(logfile))
    expected = VIEWS[case[0]]
    assert wiz.result_view == expected
    assert ev["presentation"] == expected.payload()
    assert ev["result_description"] == expected.message
    assert wiz.done_ok == expected.success
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    visible = capsys.readouterr().out
    assert expected.message in visible and expected.next_step in visible
    bundle = _bundle_files(json.dumps(ev).encode(), log.encode(), "complete")
    assert expected.announcement in bundle["README.txt"].decode()
    logfile.write_text(log)
    path = write_evidence_atomic(ev, log_dir=tmp_path)
    assert recover_result(path) == expected
    if expected.success:
        logfile.write_text("changed log")
        assert not recover_result(path).success
    path.write_text("truncated")
    assert recover_result(path).code == "indeterminate"


@pytest.mark.parametrize(
    "bad", [None, [], "verified", True, 0, {}, {"outcome": "verified"}]
)
def test_malformed_records_are_indeterminate(bad):
    assert present_evidence(bad) == VIEWS["indeterminate"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("verification", {"requested": "last", "verified": False}),
        ("completion", {"validated": False, "reason": "completed"}),
        ("exit_evidence", {"exit_code": True, "signal": None}),
        ("interruption", {"interrupted": True, "cancelled": True, "origin": "user"}),
        ("log_checksum_sha256", None),
        ("outcome", "completed"),
        ("method", {"id": "unknown"}),
    ],
)
def test_inconsistent_success_fails_closed(field, value):
    wiz, ev, _ = case_evidence(CASES[0])
    broken = copy.deepcopy(ev)
    broken[field] = value
    wiz.evidence = broken
    assert not wiz.done_ok
    assert wiz.result_view.code == "indeterminate"


def test_missing_saved_evidence_cannot_keep_green_runner_result():
    wiz, _, _ = case_evidence(CASES[0])
    wiz.evidence = None
    assert not wiz.done_ok
    wiz, _, _ = case_evidence(CASES[0])
    wiz.evidence_error = "disk full"
    assert not wiz.done_ok


def test_verification_failure_for_another_disk_is_not_relabelled():
    ok, _, reason = evaluate_nwipe_outcome(
        0, "Verification mismatch on '/dev/sdz' at offset 1\nvda | Erased |", "/dev/vda"
    )
    assert ok and reason == "completed"


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_curses_result_at_80x24(case, monkeypatch):
    wiz, _, _ = case_evidence(case)

    class Terminal:
        def __init__(self):
            self.rows = {}

        def getmaxyx(self):
            return 24, 80

        def addstr(self, y, x, text, attr=0):
            assert 0 <= y < 24 and len(text) < 80
            self.rows[y] = text

        def getch(self):
            wiz.wants_shutdown = True
            return ord("q")

        def __getattr__(self, name):
            return lambda *a: None

    terminal = Terminal()
    monkeypatch.setattr(console.curses, "curs_set", lambda *a: None)
    monkeypatch.setattr(console.curses, "use_default_colors", lambda *a: None)
    console._loop(terminal, wiz)
    text = " ".join(terminal.rows[y] for y in sorted(terminal.rows))
    assert wiz.result_view.message in text
    assert wiz.result_view.next_step in text
