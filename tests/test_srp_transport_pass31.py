"""An SRP SCSI host is remote even under a physical InfiniBand adapter."""

import os
from pathlib import Path

import pytest

from beamo_wipe.models import Disk, DiskKind
from beamo_wipe.safety import SafetyError, assert_local_device_transport, is_wipeable_disk


def test_srp_scsi_host_is_not_a_local_wipe_target(monkeypatch):
    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    realpath = os.path.realpath
    exists = Path.exists

    def fake_realpath(path):
        if str(path) == "/dev/sdz":
            return "/dev/sdz"
        if str(path) == "/sys/block/sdz/device":
            return "/sys/devices/pci0000:00/0000:00:04.0/host7/target7:0:0/7:0:0:0"
        return realpath(path)

    def fake_exists(path):
        if str(path) in {
            "/sys/block/sdz/device",
            "/sys/class/scsi_host/host7/local_ib_device",
        }:
            return True
        return exists(path)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    monkeypatch.setattr(Path, "exists", fake_exists)
    with pytest.raises(SafetyError, match="remote or unknown SCSI"):
        assert_local_device_transport("/dev/sdz")
    disk = Disk(
        path="/dev/sdz", name="sdz", model="Network disk", serial="SRP-1",
        size_bytes=1_000_000_000, size_gb_label="1", kind=DiskKind.SSD,
        bus="sas", label="Network disk",
    )
    assert not is_wipeable_disk(disk)
