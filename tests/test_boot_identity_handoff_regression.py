"""The live medium must remain the same disk through both launch rescans."""

from dataclasses import replace

import pytest

from beamo_wipe.models import DiscoveryResult, Disk, DiskKind, MethodId, Screen, WipeRequest
from beamo_wipe.safety import SafetyError, assert_rediscovered_identity, disk_identity
from test_refresh_disks import authorized


def _disks():
    boot = Disk(
        "/dev/sdb", "sdb", "USB", "BOOT-OLD", 16_000_000_000, "16",
        DiskKind.SSD, "USB", "", is_boot=True, wwn="WWN-OLD",
    )
    target = Disk(
        "/dev/sda", "sda", "SSD", "TARGET", 500_000_000_000, "500",
        DiskKind.SSD, "SATA", "", wwn="WWN-TARGET",
    )
    return boot, target


@pytest.mark.parametrize(
    "changes",
    [
        {"serial": "BOOT-NEW"},
        {"wwn": "WWN-NEW"},
        {"size_bytes": 32_000_000_000, "size_gb_label": "32"},
    ],
)
def test_runner_rescan_rejects_boot_media_reused_at_same_path(changes):
    boot, target = _disks()
    request = WipeRequest(
        target.path, MethodId.EVERYDAY, boot.path, "/tmp/fake.log",
        device_identity=disk_identity(target), boot_rdev=8,
        boot_identity=disk_identity(boot),
    )
    fresh_boot = replace(boot, **changes)
    fresh = DiscoveryResult(
        disks=(fresh_boot, target), selectable=(target,),
        boot=fresh_boot, boot_identified=True,
    )
    with pytest.raises(SafetyError, match="Boot device identity changed"):
        assert_rediscovered_identity(request, fresh)


def test_runner_rescan_requires_boot_snapshot_and_accepts_unchanged_media():
    boot, target = _disks()
    request = WipeRequest(
        target.path, MethodId.EVERYDAY, boot.path, "/tmp/fake.log",
        device_identity=disk_identity(target), boot_rdev=8,
        boot_identity=disk_identity(boot),
    )
    fresh = DiscoveryResult(
        disks=(boot, target), selectable=(target,),
        boot=boot, boot_identified=True,
    )
    assert_rediscovered_identity(request, fresh)
    with pytest.raises(SafetyError, match="Boot device identity changed"):
        assert_rediscovered_identity(replace(request, boot_identity=()), fresh)


def test_wizard_rescan_rejects_boot_swap_before_request(monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    wizard = authorized()
    wizard.dry_run = False
    wizard.preview = False
    original_boot = wizard.discovery.boot
    assert original_boot is not None
    swapped_boot = replace(
        original_boot, serial="BOOT-NEW", wwn="WWN-NEW",
        size_bytes=original_boot.size_bytes + 16_000_000_000,
    )
    fresh = replace(
        wizard.discovery,
        boot=swapped_boot,
        disks=tuple(
            swapped_boot if disk.path == original_boot.path else disk
            for disk in wizard.discovery.disks
        ),
    )
    wizard._rediscover = lambda: fresh
    wizard.confirm_erase()
    assert wizard.screen == Screen.LAST_CHANCE
    assert wizard.startup_error_code == "identity_rejected"
    assert not wizard.runner.started
