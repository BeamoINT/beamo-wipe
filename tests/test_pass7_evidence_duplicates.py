"""Recovery and export must read one unambiguous authenticated result."""

from __future__ import annotations

import hashlib

import pytest

from beamo_wipe.evidence import build_evidence, recover_result, write_evidence_atomic
from beamo_wipe.models import MethodId, WipeResult
from beamo_wipe.safety import SafetyError
from beamo_wipe import support_export as export
from beamo_wipe.support_export import EVIDENCE_LOG_META, prepare_terminal_evidence
from test_result_presentations import ERASED, STATUS, case_evidence
from test_usb_report_workflow import _discovery, _payload


def test_recover_result_rejects_duplicate_claims_with_valid_log(tmp_path):
    logfile = tmp_path / "nwipe.log"
    _, record, log = case_evidence(
        ("verified", MethodId.EVERYDAY, 0, STATUS + ERASED, False, False),
        str(logfile),
    )
    logfile.write_text(log)
    path = write_evidence_atomic(
        record, log_dir=tmp_path, device_path=record["device"]["path"]
    )
    assert recover_result(path).code == "verified"

    raw = path.read_bytes().replace(b'"outcome":', b'"outcome":"failed","outcome":', 1)
    path.write_bytes(raw)
    path.with_name(path.name + ".sha256").write_text(
        f"{hashlib.sha256(raw).hexdigest()}  {path.name}\n"
    )
    assert recover_result(path).code == "indeterminate"


@pytest.mark.parametrize(
    "code,template",
    [
        ("occupied", "{path} is reported as IN USE"),
        ("open_failed", "Unable to open device '{path}'."),
        ("geometry_unusable", "No sane device geometry for '{path}'."),
    ],
)
def test_recovered_nothing_erased_claim_requires_unchanged_log(
    tmp_path, code, template
):
    logfile = tmp_path / "nwipe.log"
    _, record, log = case_evidence(
        (code, MethodId.EVERYDAY, 0, template, False, False), str(logfile)
    )
    logfile.write_text(log)
    path = write_evidence_atomic(
        record, log_dir=tmp_path, device_path=record["device"]["path"]
    )
    assert recover_result(path).code == code
    assert prepare_terminal_evidence(path, record["device"]["path"]).outcome == "failed"

    logfile.write_text("later log content with unknown disk outcome\n")
    assert recover_result(path).code == "indeterminate"
    with pytest.raises(SafetyError, match=EVIDENCE_LOG_META):
        prepare_terminal_evidence(path, record["device"]["path"])


def test_uncertain_failure_remains_exportable_without_mutable_log(tmp_path):
    logfile = tmp_path / "nwipe.log"
    _, record, log = case_evidence(
        ("process_failed", MethodId.EVERYDAY, 2, "", False, False), str(logfile)
    )
    logfile.write_text(log)
    path = write_evidence_atomic(
        record, log_dir=tmp_path, device_path=record["device"]["path"]
    )
    logfile.unlink()
    assert recover_result(path).code == "process_failed"
    assert prepare_terminal_evidence(path, record["device"]["path"]).outcome == "failed"


def test_log_change_after_preparation_blocks_nothing_erased_report(
    tmp_path, monkeypatch
):
    inventory, disks = _payload()
    discovery = _discovery(disks)
    target = discovery.selectable[0]
    logfile = tmp_path / "nwipe.log"
    log = f"{target.path} is reported as IN USE\n"
    logfile.write_text(log)
    record = build_evidence(
        disk=target,
        discovery=discovery,
        method=MethodId.EVERYDAY,
        request=None,
        result=WipeResult(False, 0, "busy", str(logfile), "occupied"),
        started_at_wall="",
        ended_at_wall="",
        started_mono=0,
        ended_mono=1,
        argv=[],
        log_text=log,
    )
    path = write_evidence_atomic(record, log_dir=tmp_path, device_path=target.path)
    assert prepare_terminal_evidence(path, target.path).outcome == "failed"
    rdevs = {"/dev/sdb": 201, target.path: 202, "/dev/sdc": 301, "/dev/sdc1": 302}
    monkeypatch.setattr(export, "_block_rdev", lambda device: rdevs[device])
    original_select = export.select_export_volume
    selections = 0

    def select_then_change_log(payload, baseline):
        nonlocal selections
        selected = original_select(payload, baseline)
        selections += 1
        if selections == 1:
            logfile.write_text("later log content with unknown disk outcome\n")
        return selected

    monkeypatch.setattr(export, "select_export_volume", select_then_change_log)

    def worker_must_not_start(*_args, **_kwargs):
        raise AssertionError("changed log reached report worker")

    with pytest.raises(SafetyError, match=EVIDENCE_LOG_META):
        export.export_to_new_usb(
            evidence_path=path,
            discovery=discovery,
            target_path=target.path,
            scan=lambda: inventory,
            run=worker_must_not_start,
        )
    assert selections == 2
