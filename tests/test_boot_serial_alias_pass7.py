# SPDX-License-Identifier: GPL-3.0-or-later
"""A boot or mounted disk alias with only a serial cannot become a target."""

from dataclasses import replace

import pytest

from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.safety import SafetyError, assert_boot_excluded
from test_excluded_inventory import node


def test_boot_serial_alias_is_never_selectable_without_wwn() -> None:
    result = parse_lsblk_json(
        {"blockdevices": [
            node("sda", serial="TARGET-1"),
            node("sdb", tran="usb", serial="BOOT-ALIAS-1", mountpoints=["/run/live/medium"]),
            node("sdc", tran="usb", serial="boot-alias-1"),
        ]},
        boot_path="/dev/sdb",
    )
    assert result.boot_identified
    assert [disk.path for disk in result.selectable] == ["/dev/sda"]
    assert next(disk for disk in result.disks if disk.path == "/dev/sdc").is_boot


def test_constructed_discovery_rejects_boot_serial_alias() -> None:
    result = parse_lsblk_json(
        {"blockdevices": [
            node("sdb", tran="usb", serial="BOOT-ALIAS-1", mountpoints=["/run/live/medium"]),
            node("sdc", tran="usb", serial="TARGET-1"),
        ]},
        boot_path="/dev/sdb",
    )
    alias = replace(result.selectable[0], serial="BOOT-ALIAS-1")
    injected = replace(result, disks=(*result.disks, alias), selectable=(alias,))
    with pytest.raises(SafetyError, match="Boot USB appeared"):
        assert_boot_excluded(injected)


def test_mounted_serial_alias_stays_unselectable() -> None:
    result = parse_lsblk_json(
        {"blockdevices": [
            node("sda", serial="MOUNTED-LUN-1", mountpoints=["/media/data"]),
            node("sdb", tran="usb", serial="BOOT-1", mountpoints=["/run/live/medium"]),
            node("sdc", serial="mounted-lun-1"),
        ]},
        boot_path="/dev/sdb",
    )
    assert result.boot_identified
    assert not any(disk.path == "/dev/sdc" for disk in result.selectable)


def test_distinct_wwns_disambiguate_a_reused_serial() -> None:
    result = parse_lsblk_json(
        {"blockdevices": [
            node("sdb", tran="usb", serial="REUSED", wwn="boot-wwn",
                 mountpoints=["/run/live/medium"]),
            node("sdc", serial="REUSED", wwn="target-wwn"),
        ]},
        boot_path="/dev/sdb",
    )
    assert [disk.path for disk in result.selectable] == ["/dev/sdc"]
    assert not next(disk for disk in result.disks if disk.path == "/dev/sdc").is_boot
    assert_boot_excluded(result)


@pytest.mark.parametrize("placeholder", ["00000000", "UNKNOWN", "N/A"])
def test_missing_boot_serial_does_not_hide_an_unrelated_disk(placeholder: str) -> None:
    result = parse_lsblk_json(
        {"blockdevices": [
            node("sdb", tran="usb", serial=placeholder, mountpoints=["/run/live/medium"]),
            node("sdc", serial=placeholder),
        ]},
        boot_path="/dev/sdb",
    )
    assert [disk.path for disk in result.selectable] == ["/dev/sdc"]
