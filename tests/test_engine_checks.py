# SPDX-License-Identifier: GPL-3.0-or-later
"""Pinned nwipe v0.42 log checks. Fake devices and recorded logs only."""

from __future__ import annotations

import inspect
from pathlib import Path

from dataclasses import replace

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.engine_checks import (
    CHECK_IDS,
    STATUSES,
    alert_summaries,
    check_payloads,
    evaluate_engine_checks,
)
from beamo_wipe.evidence import build_evidence
from beamo_wipe.models import MethodId, WipeResult
from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome
from beamo_wipe.outcomes import present_evidence

FIXTURES = Path(__file__).parent / "fixtures" / "nwipe_v042"


def _log(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _by_id(checks):
    return {item.id: item for item in checks}


def test_module_does_not_run_host_diagnostics():
    import beamo_wipe.engine_checks as module

    src = inspect.getsource(module)
    assert "import subprocess" not in src
    assert "Popen" not in src
    assert "os.system" not in src
    assert "--security-erase" not in src
    assert "--dco-restore" not in src


def test_hidden_detected_is_warning_not_outcome_rewrite():
    checks = _by_id(evaluate_engine_checks(_log("hidden_detected.log"), "/dev/sda"))
    assert checks["hidden_capacity"].status == "warning"
    assert "hidden storage" in checks["hidden_capacity"].summary
    assert checks["io_media"].status == "pass"
    assert checks["coverage"].status == "warning"
    ok, _, reason = evaluate_nwipe_outcome(0, _log("hidden_detected.log"), "/dev/sda")
    assert ok and reason == "completed"


def test_hidden_none_is_pass():
    checks = _by_id(evaluate_engine_checks(_log("hidden_none.log"), "/dev/sda"))
    assert checks["hidden_capacity"].status == "pass"
    assert checks["io_media"].status == "pass"


def test_indeterminate_unknown_missing_permission_are_unavailable():
    cases = {
        "hidden_indeterminate.log": "HIDDEN SECTORS INDETERMINATE",
        "hidden_unknown_hpa_line.log": "HPA line",
        "hdparm_missing.log": "hdparm command not found",
        "hdparm_permission.log": "Failed to create stream",
        "sg_io_sense.log": "SG_IO",
        "localized_unrelated.log": "versteckte",
        "truncated.log": "HIDDEN SECTORS DETE",
    }
    for name, needle in cases.items():
        text = _log(name)
        assert needle.lower() in text.lower()
        checks = _by_id(evaluate_engine_checks(text, "/dev/sda"))
        assert checks["hidden_capacity"].status == "unavailable", name
        assert "not a pass" in checks["hidden_capacity"].summary


def test_empty_log_is_unavailable_never_pass():
    checks = _by_id(evaluate_engine_checks("", "/dev/sda"))
    assert checks["hidden_capacity"].status == "unavailable"
    assert checks["io_media"].status == "unavailable"
    assert checks["coverage"].status == "warning"


def test_contradictory_hidden_signals_are_unavailable():
    checks = _by_id(evaluate_engine_checks(_log("contradictory_hidden.log"), "/dev/sda"))
    assert checks["hidden_capacity"].status == "unavailable"


def test_foreign_device_lines_do_not_apply():
    checks = _by_id(evaluate_engine_checks(_log("foreign_device.log"), "/dev/sda"))
    assert checks["hidden_capacity"].status == "pass"
    assert checks["io_media"].status == "pass"


def test_io_errors_are_fail_and_keep_engine_failure():
    text = _log("io_errors.log")
    checks = _by_id(evaluate_engine_checks(text, "/dev/sda"))
    assert checks["io_media"].status == "fail"
    assert checks["hidden_capacity"].status == "pass"
    ok, _, reason = evaluate_nwipe_outcome(0, text, "/dev/sda")
    assert not ok and reason == "engine_failed"


def test_malformed_error_summary_is_unavailable():
    checks = _by_id(
        evaluate_engine_checks(_log("error_summary_malformed.log"), "/dev/sda")
    )
    assert checks["io_media"].status == "unavailable"


def test_newer_gui_token_is_not_inferred():
    text = "[HS? YES] sda\n      sda | Erased |\n"
    checks = _by_id(evaluate_engine_checks(text, "/dev/sda"))
    assert checks["hidden_capacity"].status == "unavailable"


def test_alerts_omit_pass_and_coverage():
    checks = evaluate_engine_checks(_log("hidden_none.log"), "/dev/sda")
    assert alert_summaries(checks) == ()
    warned = evaluate_engine_checks(_log("hidden_detected.log"), "/dev/sda")
    alerts = alert_summaries(warned)
    assert alerts and all("hidden storage" in item for item in alerts)


def test_evidence_keeps_verified_when_hidden_capacity_warns():
    wiz = make_demo_wizard()
    disk = replace(wiz.selectable[0], path="/dev/sda", name="sda")
    log = _log("hidden_detected.log")
    ok, detail, reason = evaluate_nwipe_outcome(0, log, disk.path)
    result = WipeResult(ok, 0, detail, "fake-log", reason)
    ev = build_evidence(
        disk=disk,
        discovery=wiz.discovery,
        method=MethodId.EVERYDAY,
        request=None,
        result=result,
        started_at_wall="",
        ended_at_wall="",
        started_mono=0,
        ended_mono=1,
        argv=[],
        log_text=log,
    )
    assert ev["outcome"] == "verified"
    assert present_evidence(ev).code == "verified"
    assert present_evidence(ev).success
    hidden = next(item for item in ev["checks"] if item["id"] == "hidden_capacity")
    assert hidden["status"] == "warning"
    assert hidden["provenance"]["engine_version"] == "0.42"
    assert hidden["provenance"]["engine_commit"].startswith("6082bde")
    assert any("hidden storage" in warn for warn in ev["warnings"])


def test_check_fail_does_not_invent_success():
    wiz = make_demo_wizard()
    disk = replace(wiz.selectable[0], path="/dev/sda", name="sda")
    log = _log("io_errors.log")
    ok, detail, reason = evaluate_nwipe_outcome(0, log, disk.path)
    result = WipeResult(ok, 0, detail, "fake-log", reason)
    ev = build_evidence(
        disk=disk,
        discovery=wiz.discovery,
        method=MethodId.EVERYDAY,
        request=None,
        result=result,
        started_at_wall="",
        ended_at_wall="",
        started_mono=0,
        ended_mono=1,
        argv=[],
        log_text=log,
    )
    assert ev["outcome"] == "failed"
    assert present_evidence(ev).success is False
    io_check = next(item for item in ev["checks"] if item["id"] == "io_media")
    assert io_check["status"] == "fail"


def test_payloads_are_closed_and_complete():
    payloads = check_payloads("", "/dev/sda")
    assert [item["id"] for item in payloads] == list(CHECK_IDS)
    for item in payloads:
        assert item["status"] in STATUSES
        assert item["provenance"]["engine"] == "nwipe"
        assert item["provenance"]["engine_version"] == "0.42"


def test_prefix_devices_cannot_supply_target_checks():
    for foreign in ('/dev/sdab', '/dev/sda1', '/dev/sda-test'):
        text = f'No hidden sectors on {foreign}\n'
        checks = _by_id(evaluate_engine_checks(text, '/dev/sda'))
        assert checks['hidden_capacity'].status == 'unavailable', foreign
        text = _log('hidden_none.log') + f'Verification mismatch on {foreign}\n'
        assert _by_id(evaluate_engine_checks(text, '/dev/sda'))['io_media'].status == 'pass'


def test_conflicting_error_rows_cannot_hide_errors_in_either_order():
    rows = ('! sda | 1 | 0 | 0\n', '  sda | 0 | 0 | 0\n')
    for ordered in (rows, rows[::-1]):
        text = 'Error Summary\n' + ''.join(ordered) + '***\n'
        assert _by_id(evaluate_engine_checks(text, '/dev/sda'))['io_media'].status == 'unavailable'


def test_malformed_error_rows_cannot_keep_a_zero_error_pass():
    text = 'Error Summary\n  sda | 0 | 0 | 0\n  sda | broken | 0 | 0\n***\n'
    assert _by_id(evaluate_engine_checks(text, '/dev/sda'))['io_media'].status == 'unavailable'
