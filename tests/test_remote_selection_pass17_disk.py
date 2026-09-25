# SPDX-License-Identifier: GPL-3.0-or-later
"""A remote NVMe namespace must be excluded before the owner can choose it."""

from dataclasses import replace
from pathlib import Path

from beamo_wipe.inventory import REASON_UNPROVEN_TRANSPORT, excluded_device
from beamo_wipe.models import Disk, DiskKind, DiscoveryResult
from beamo_wipe.safety import is_wipeable_disk, selectable_disks


def _nvme_disk() -> Disk:
    return Disk(
        path="/dev/nvme0n1",
        name="nvme0n1",
        model="Remote namespace",
        serial="NS-1",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.NVME,
        bus="NVMe",
        label="",
    )


def test_remote_nvme_is_not_selectable_on_live(monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    original = Path.read_text

    def transport(path, *args, **kwargs):
        if str(path) == "/sys/class/nvme/nvme0/transport":
            return "tcp\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transport)
    assert is_wipeable_disk(_nvme_disk()) is False
    boot = replace(_nvme_disk(), path="/dev/nvme1n1", name="nvme1n1", is_boot=True)
    listed = DiscoveryResult(
        disks=(boot, _nvme_disk()),
        selectable=(_nvme_disk(),),
        boot=boot,
        boot_identified=True,
    )
    assert selectable_disks(listed) == ()
    assert REASON_UNPROVEN_TRANSPORT in excluded_device(_nvme_disk()).reasons


def test_local_nvme_remains_selectable_on_live(monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    original = Path.read_text

    def transport(path, *args, **kwargs):
        if str(path) == "/sys/class/nvme/nvme0/transport":
            return "pcie\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transport)
    assert is_wipeable_disk(_nvme_disk()) is True
