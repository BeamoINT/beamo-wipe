"""A stale internal label cannot make a live USB selectable."""

import pytest

from beamo_wipe.discover import discover, parse_lsblk_json
from beamo_wipe.identity import present_disk
from beamo_wipe.models import Disk, DiskKind
from beamo_wipe.safety import SafetyError, assert_boot_excluded, confirm_spec


def test_small_internal_cmdline_label_does_not_expose_unidentified_usb():
    payload = {
        "blockdevices": [
            {
                "name": "sda", "path": "/dev/sda", "type": "disk",
                "size": 64_000_000_000, "tran": "sata", "model": "Internal",
                "serial": "INT", "children": [
                    {"name": "sda1", "path": "/dev/sda1", "type": "part", "label": "BEAMO_WIPE"},
                ],
            },
            {
                "name": "sdb", "path": "/dev/sdb", "type": "disk",
                "size": 16_000_000_000, "tran": "usb", "model": "USB", "serial": "USB",
            },
        ],
    }
    result = discover(
        lsblk_payload=payload,
        mount_sources=[],
        cmdline="boot=live bootfrom=LABEL=BEAMO_WIPE",
        env={},
    )
    assert not result.boot_identified
    assert result.selectable == ()


def test_small_internal_cmdline_label_does_not_expose_sata_usb_bridge():
    payload = {
        "blockdevices": [
            {
                "name": "sda", "path": "/dev/sda", "type": "disk",
                "size": 64_000_000_000, "tran": "sata", "model": "Internal",
                "serial": "INT", "children": [
                    {"name": "sda1", "path": "/dev/sda1", "type": "part", "label": "BEAMO_WIPE"},
                ],
            },
            {
                "name": "sdb", "path": "/dev/sdb", "type": "disk",
                "size": 16_000_000_000, "tran": "sata", "model": "USB bridge",
                "serial": "USB",
            },
        ],
    }
    result = discover(
        lsblk_payload=payload,
        mount_sources=[],
        cmdline="boot=live bootfrom=LABEL=BEAMO_WIPE",
        env={},
    )
    assert not result.boot_identified
    assert result.selectable == ()


def test_resolved_live_mount_allows_small_fixed_target_with_sata_bridge():
    payload = {
        "blockdevices": [
            {
                "name": "sda", "path": "/dev/sda", "type": "disk",
                "size": 16_000_000_000, "tran": "sata", "rm": True,
                "hotplug": True, "serial": "BOOT", "children": [
                    {"name": "sda1", "path": "/dev/sda1", "type": "part", "label": "BEAMO_WIPE"},
                ],
            },
            {
                "name": "sdb", "path": "/dev/sdb", "type": "disk",
                "size": 64_000_000_000, "tran": "sata", "serial": "TARGET",
            },
        ],
    }
    uncertain = discover(
        lsblk_payload=payload,
        mount_sources=[],
        cmdline="boot=live bootfrom=/dev/sda1",
        env={},
    )
    assert not uncertain.boot_identified and uncertain.selectable == ()
    result = discover(
        lsblk_payload=payload,
        mount_sources=["/dev/sda1"],
        cmdline="boot=live bootfrom=/dev/sda1",
        env={},
    )
    assert result.boot_identified
    assert result.boot is not None and result.boot.path == "/dev/sda"
    assert [disk.path for disk in result.selectable] == ["/dev/sdb"]


@pytest.mark.parametrize("cmdline", ["boot=live", "boot=live bootfrom=/dev/sda1"])
def test_stale_label_cannot_expose_large_usb_sata_live_disk(cmdline):
    payload = {
        "blockdevices": [
            {
                "name": "sda", "path": "/dev/sda", "type": "disk",
                "size": 16_000_000_000, "tran": "usb", "serial": "STALE",
                "children": [
                    {"name": "sda1", "path": "/dev/sda1", "type": "part", "label": "BEAMO_WIPE"},
                ],
            },
            {
                "name": "sdb", "path": "/dev/sdb", "type": "disk",
                "size": 256_000_000_000, "tran": "sata", "rm": False,
                "hotplug": False, "serial": "LIVE-BRIDGE",
                "children": [
                    {"name": "sdb1", "path": "/dev/sdb1", "type": "part", "label": "DATA"},
                ],
            },
        ],
    }
    result = discover(
        lsblk_payload=payload,
        mount_sources=[],
        cmdline=cmdline,
        env={},
    )
    assert not result.boot_identified
    assert result.selectable == ()


def test_zero_wwn_padding_does_not_alias_independent_disks():
    payload = {
        "blockdevices": [
            {
                "name": "sdb", "path": "/dev/sdb", "type": "disk",
                "size": 16_000_000_000, "tran": "usb", "serial": "BOOT",
                "wwn": "0x0000000000000000",
            },
            {
                "name": "sda", "path": "/dev/sda", "type": "disk",
                "size": 500_000_000_000, "tran": "sata", "serial": "TARGET",
                "wwn": "0x0000000000000000",
            },
        ],
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    assert result.boot_identified
    assert [disk.path for disk in result.selectable] == ["/dev/sda"]
    assert_boot_excluded(result)


def test_zero_wwn_cannot_disambiguate_duplicate_serials():
    disks = [
        Disk(
            path=path, name=path.rsplit("/", 1)[-1], model="Disk",
            serial="DUP", size_bytes=500_000_000_000, size_gb_label="500",
            kind=DiskKind.HDD, bus="SATA", label="", wwn=wwn,
        )
        for path, wwn in (
            ("/dev/sda", "0x0000000000000000"),
            ("/dev/sdc", ""),
        )
    ]
    with pytest.raises(SafetyError, match="too similar"):
        confirm_spec(disks[0], disks)
    assert not present_disk(disks[0], disks).confirmable


def test_peer_zero_wwn_does_not_claim_a_real_serial_token():
    disks = [
        Disk(
            path=path, name=path.rsplit("/", 1)[-1], model="Disk",
            serial=serial, size_bytes=500_000_000_000, size_gb_label="500",
            kind=DiskKind.HDD, bus="SATA", label="", wwn=wwn,
        )
        for path, serial, wwn in (
            ("/dev/sda", "0000", ""),
            ("/dev/sdc", "BBBB", "0x0000000000000000"),
        )
    ]
    assert confirm_spec(disks[0], disks).token == "0000"
