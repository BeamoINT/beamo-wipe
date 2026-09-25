"""A fake saved success record cannot outrun its contradictory log snapshot."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from beamo_wipe import support_export as export
from beamo_wipe.models import MethodId
from beamo_wipe.safety import SafetyError
from test_result_presentations import ERASED, STATUS, case_evidence


@pytest.mark.parametrize(
    ("snapshot", "status", "allowed"),
    [
        (b"nwipe exited without a result\n", "complete", False),
        (b"", "unavailable", False),
        (None, "complete", True),
    ],
)
def test_success_export_refuses_log_that_cannot_corroborate_result(
    monkeypatch, snapshot, status, allowed
):
    _, claim, authentic_log = case_evidence(
        ("verified", MethodId.EVERYDAY, 0, STATUS + ERASED, False, False)
    )
    if snapshot is None:
        snapshot = authentic_log.encode()
    data = json.dumps(claim).encode()
    evidence = export.VerifiedEvidence(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        outcome="verified",
        logfile="/tmp/fake-nwipe.log",
        log_sha256=claim["log_checksum_sha256"],
        log_size_bytes=claim["log_snapshot_size_bytes"],
    )
    parent = export.DeviceFingerprint("/dev/sdc", 32_000_000, "Report USB", "R-1", "r-wwn", 11)
    volume = export.ExportVolume(parent, "/dev/sdc1", 31_000_000, "vfat", "FAT32", "A1B2", 12)
    monkeypatch.setattr(export, "select_export_volume", lambda *_: volume)
    monkeypatch.setattr(export, "_baseline_with_rdev", lambda *_: ())
    monkeypatch.setattr(export, "_protected_rdevs", lambda *_: ())
    monkeypatch.setattr(export, "_volume_with_rdev", lambda *_: volume)
    monkeypatch.setattr(export, "read_export_log", lambda *_args, **_kwargs: (snapshot, status))
    worker = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, json.dumps(asdict(export.ExportReceipt(False, False, "export_failed")))
        )
    )

    if allowed:
        assert export._export_prepared(evidence, (), scan=lambda: {}, run=worker) == export.ExportReceipt(
            False, False, "export_failed"
        )
        worker.assert_called_once()
    else:
        with pytest.raises(SafetyError, match="log metadata"):
            export._export_prepared(evidence, (), scan=lambda: {}, run=worker)
        worker.assert_not_called()
