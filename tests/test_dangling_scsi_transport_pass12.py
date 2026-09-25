"""A vanished sysfs parent cannot prove a disk has a local transport."""

import os
from pathlib import Path

import pytest

from beamo_wipe.safety import SafetyError, assert_local_device_transport


@pytest.mark.parametrize("link_remains", (True, False))
def test_missing_scsi_device_symlink_fails_closed(monkeypatch, tmp_path, link_remains):
    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    parent = tmp_path / "gone-local-pci-device"
    link = tmp_path / "device"
    if link_remains:
        link.symlink_to(parent)
    realpath = os.path.realpath

    def fake_realpath(path):
        if str(path) == "/dev/sdz":
            return "/dev/sdz"
        if str(path) == "/sys/block/sdz/device":
            return str(parent)
        return realpath(path)

    exists = Path.exists
    lexists = os.path.lexists

    def fake_exists(path):
        if str(path) == "/sys/block/sdz/device":
            return exists(link)
        return exists(path)

    def fake_lexists(path):
        if str(path) == "/sys/block/sdz/device":
            return lexists(link)
        return lexists(path)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(os.path, "lexists", fake_lexists)
    with pytest.raises(SafetyError, match="locally attached"):
        assert_local_device_transport("/dev/sdz")
