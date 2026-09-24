"""Ambiguous helper receipts must not claim a verified removable report."""

import json
import subprocess

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import HELPER_BAD_RECEIPT, export_to_new_usb
from test_usb_report_workflow import (
    _discovery,
    _payload,
    _terminal_evidence,
    _worker_success_stdout,
)


@pytest.mark.parametrize(
    "field,earlier", [("ok", "false"), ("safe_to_remove", "false")]
)
def test_controller_refuses_conflicting_duplicate_helper_receipt(
    tmp_path, monkeypatch, field, earlier
):
    evidence_path = _terminal_evidence(tmp_path)
    payload, disks = _payload()
    monkeypatch.setattr(
        "beamo_wipe.support_export._block_rdev",
        {
            "/dev/sdb": 201,
            "/dev/nvme0n1": 202,
            "/dev/sdc": 301,
            "/dev/sdc1": 302,
        }.__getitem__,
    )

    def fake_run(command, **kwargs):
        valid = _worker_success_stdout(json.loads(kwargs["input"]))
        conflicting = valid.replace("{", '{"' + field + '":' + earlier + ",", 1)
        return subprocess.CompletedProcess(command, 0, stdout=conflicting, stderr="")

    with pytest.raises(SafetyError, match=HELPER_BAD_RECEIPT):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=_discovery(disks),
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=fake_run,
        )
