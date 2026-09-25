"""A bracket inside a device alias is not a findmnt subvolume annotation."""

import os

import pytest

from beamo_wipe.discover import discover, normalize_mount_source


@pytest.mark.parametrize("alias_suffix", ("[rev2]", " "))
def test_by_id_alias_suffix_cannot_select_a_different_boot_disk(
    monkeypatch, alias_suffix
):
    realpath = os.path.realpath
    actual_alias = "/dev/disk/by-id/usb-live" + alias_suffix
    prefix_alias = "/dev/disk/by-id/usb-live"

    def aliases(path):
        if str(path) == actual_alias:
            return "/dev/sdb1"
        if str(path) == prefix_alias:
            return "/dev/sda1"
        return realpath(path)

    monkeypatch.setattr(os.path, "realpath", aliases)
    payload = {
        "blockdevices": [
            {
                "name": name,
                "path": f"/dev/{name}",
                "type": "disk",
                "size": 500_000_000_000 if name == "sda" else 16_000_000_000,
                "tran": bus,
                "serial": name,
                "children": [
                    {
                        "name": f"{name}1",
                        "path": f"/dev/{name}1",
                        "type": "part",
                        "pkname": name,
                    }
                ],
            }
            for name, bus in (("sda", "sata"), ("sdb", "usb"))
        ]
    }

    result = discover(
        lsblk_payload=payload,
        mount_sources=[actual_alias],
        cmdline="boot=live",
        env={},
    )

    assert normalize_mount_source(actual_alias) == actual_alias
    assert normalize_mount_source("/dev/sdb1[data]") == "/dev/sdb1"
    assert result.boot_identified
    assert result.boot is not None and result.boot.path == "/dev/sdb"
    assert {disk.path for disk in result.selectable} == {"/dev/sda"}
