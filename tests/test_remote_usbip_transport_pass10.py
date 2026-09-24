"""USB/IP block devices must not pass the final local-transport gate."""

import os
from pathlib import Path

import pytest

from beamo_wipe.safety import SafetyError, assert_local_device_transport


def test_usbip_virtual_host_controller_is_remote(monkeypatch):
    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    realpath = os.path.realpath

    def fake_realpath(path):
        value = str(path)
        if value == "/dev/sdz":
            return value
        if value == "/sys/block/sdz/device":
            return (
                "/sys/devices/platform/vhci_hcd.0/usb1/1-1/1-1:1.0/"
                "host7/target7:0:0/7:0:0:0"
            )
        return realpath(value)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: True if str(path) == "/sys/block/sdz/device" else exists(path),
    )
    with pytest.raises(SafetyError, match="remote or unknown SCSI"):
        assert_local_device_transport("/dev/sdz")


def test_physical_usb_host_controller_remains_local(monkeypatch):
    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    realpath = os.path.realpath

    def fake_realpath(path):
        value = str(path)
        if value == "/dev/sdz":
            return value
        if value == "/sys/block/sdz/device":
            return (
                "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-1/1-1:1.0/"
                "host7/target7:0:0/7:0:0:0"
            )
        return realpath(value)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: True if str(path) == "/sys/block/sdz/device" else exists(path),
    )
    assert_local_device_transport("/dev/sdz")
