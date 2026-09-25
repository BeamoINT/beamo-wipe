"""An unreadable SCSI sysfs link cannot prove local storage."""

import os
from pathlib import Path

import pytest

from beamo_wipe.models import Disk, DiskKind
from beamo_wipe.safety import SafetyError, assert_local_device_transport, is_wipeable_disk


def test_unreadable_scsi_device_sysfs_is_a_closed_selection(monkeypatch):
    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    realpath = os.path.realpath
    exists = Path.exists

    def fake_realpath(path):
        value = str(path)
        if value == "/dev/sdz":
            return value
        if value == "/sys/block/sdz/device":
            return "/sys/devices/pci0000:00/host7/target7:0:0/7:0:0:0"
        return realpath(value)

    def fake_exists(path):
        if str(path) == "/sys/block/sdz/device":
            raise PermissionError("sysfs unavailable")
        return exists(path)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    monkeypatch.setattr(Path, "exists", fake_exists)
    with pytest.raises(SafetyError, match="Cannot prove the disk is locally attached"):
        assert_local_device_transport("/dev/sdz")
    disk = Disk(
        path="/dev/sdz", name="sdz", model="SSD", serial="S1",
        size_bytes=1_000_000_000, size_gb_label="1", kind=DiskKind.SSD,
        bus="sas", label="SSD",
    )
    assert not is_wipeable_disk(disk)
