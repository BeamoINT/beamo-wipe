"""A virtual SCSI ancestry cannot prove that a disk is locally attached."""

import os
from pathlib import Path

import pytest

from beamo_wipe.safety import SafetyError, assert_local_device_transport


def test_virtual_scsi_device_is_not_proven_local(monkeypatch):
    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    realpath = os.path.realpath
    exists = Path.exists

    def fake_realpath(path):
        if str(path) == "/dev/sdz":
            return "/dev/sdz"
        if str(path) == "/sys/block/sdz/device":
            return "/sys/devices/virtual/scsi_host/host7/target7:0:0/7:0:0:0"
        return realpath(path)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: True if str(path) == "/sys/block/sdz/device" else exists(path),
    )
    with pytest.raises(SafetyError, match="remote or unknown SCSI"):
        assert_local_device_transport("/dev/sdz")
