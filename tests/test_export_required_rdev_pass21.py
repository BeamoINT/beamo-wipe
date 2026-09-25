"""An export must keep the boot and target kernel nodes pinned after erasure."""

import json
import subprocess

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import export_to_new_usb
from test_usb_report_workflow import (
    _discovery,
    _payload,
    _terminal_evidence,
    _worker_success_stdout,
)


@pytest.mark.parametrize(
    ("changed", "target_rdev", "boot_rdev"),
    (
        ("/dev/nvme0n1", 202, 201),
        ("/dev/sdb", 202, 201),
    ),
)
def test_required_disk_kernel_identity_change_refuses_export(
    tmp_path, monkeypatch, changed, target_rdev, boot_rdev
):
    evidence_path = _terminal_evidence(tmp_path)
    payload, baseline_disks = _payload()
    discovery = _discovery(baseline_disks)
    rdevs = {
        "/dev/sdb": 201,
        "/dev/nvme0n1": 202,
        "/dev/sdc": 301,
        "/dev/sdc1": 302,
    }
    rdevs[changed] += 1000
    monkeypatch.setattr(
        "beamo_wipe.support_export._block_rdev", lambda path: rdevs[path]
    )

    def unexpected_worker(command, **kwargs):
        request = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            command, 0, stdout=_worker_success_stdout(request), stderr=""
        )

    with pytest.raises(SafetyError, match="identity changed"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            target_rdev=target_rdev,
            boot_rdev=boot_rdev,
            scan=lambda: payload,
            run=unexpected_worker,
        )


def test_matching_required_kernel_identities_still_export(tmp_path, monkeypatch):
    evidence_path = _terminal_evidence(tmp_path)
    payload, baseline_disks = _payload()
    monkeypatch.setattr(
        "beamo_wipe.support_export._block_rdev",
        lambda path: {
            "/dev/sdb": 201,
            "/dev/nvme0n1": 202,
            "/dev/sdc": 301,
            "/dev/sdc1": 302,
        }[path],
    )

    def fake_worker(command, **kwargs):
        request = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            command, 0, stdout=_worker_success_stdout(request), stderr=""
        )

    receipt = export_to_new_usb(
        evidence_path=evidence_path,
        discovery=_discovery(baseline_disks),
        target_path="/dev/nvme0n1",
        target_rdev=202,
        boot_rdev=201,
        scan=lambda: payload,
        run=fake_worker,
    )
    assert receipt.ok and receipt.safe_to_remove
