"""Mounted LVM and linear volume membership is not complete in lsblk."""

from __future__ import annotations

import pytest

from beamo_wipe.discover import discover, parse_lsblk_json


SIZE = 100_000_000_000


def _disk(name: str, *, children: list[dict] | None = None) -> dict:
    row = {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "size": SIZE,
        "tran": "usb" if name == "sdc" else "sata",
        "ro": 0,
        "mountpoints": [None],
    }
    if children is not None:
        row["children"] = children
    return row


def _payload(kind: str, *, mounted: bool) -> dict:
    name, path = (
        ("vg-lv", "/dev/mapper/vg-lv") if kind == "lvm" else ("md0", "/dev/md0")
    )
    volume = {
        "name": name,
        "path": path,
        "type": kind,
        "pkname": "sda1",
        "size": SIZE,
        "fstype": "ext4",
        "mountpoints": ["/mnt/data"] if mounted else [None],
    }
    partition = {
        "name": "sda1",
        "path": "/dev/sda1",
        "type": "part",
        "pkname": "sda",
        "size": SIZE,
        "fstype": "lvm2_member" if kind == "lvm" else "linux_raid_member",
        "mountpoints": [None],
        "children": [volume],
    }
    return {
        "blockdevices": [
            _disk("sda", children=[partition]),
            _disk("sdb"),  # A second member may have stale/empty metadata.
            _disk("sdc"),
        ]
    }


@pytest.mark.parametrize("kind", ["lvm", "linear"])
def test_mounted_stack_refuses_unproven_physical_member(kind: str) -> None:
    payload = _payload(kind, mounted=True)
    with pytest.raises(ValueError, match="mounted.*membership"):
        parse_lsblk_json(payload, boot_path="/dev/sdc")

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sdc",
        mount_sources=["/dev/sdc"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert not result.selectable


@pytest.mark.parametrize("kind", ["lvm", "linear"])
def test_unmounted_stack_keeps_other_disk_available(kind: str) -> None:
    result = parse_lsblk_json(_payload(kind, mounted=False), boot_path="/dev/sdc")
    assert result.boot_identified
    assert "/dev/sdb" in [d.path for d in result.selectable]


def test_direct_mounted_ext4_disk_keeps_other_disk_available() -> None:
    mounted = _disk("sda")
    mounted.update(fstype="ext4", mountpoints=["/mnt/data"])
    result = parse_lsblk_json(
        {"blockdevices": [mounted, _disk("sdb"), _disk("sdc")]},
        boot_path="/dev/sdc",
    )
    assert result.boot_identified
    assert [d.path for d in result.selectable] == ["/dev/sdb"]


def test_duplicate_flat_lvm_ancestor_cannot_expose_third_disk() -> None:
    def partition(name: str, parent: str) -> dict:
        return {
            "name": name,
            "path": f"/dev/{name}",
            "type": "part",
            "pkname": parent,
            "size": SIZE,
            "mountpoints": [None],
        }

    def lvm(parent: str) -> dict:
        return {
            "name": "dm-0",
            "path": "/dev/dm-0",
            "type": "lvm",
            "pkname": parent,
            "size": SIZE,
            "mountpoints": [None],
        }

    mounted = {
        "name": "dm-1",
        "path": "/dev/dm-1",
        "type": "crypt",
        "pkname": "dm-0",
        "size": SIZE,
        "mountpoints": ["/mnt/data"],
        # FSTYPE may be absent even though mountpoint was reported.
    }
    payload = {
        "blockdevices": [
            _disk("sda"),
            _disk("sdb"),
            _disk("sdd"),
            _disk("sdc"),
            partition("sda1", "sda"),
            partition("sdb1", "sdb"),
            lvm("sda1"),
            lvm("sdb1"),
            mounted,
        ]
    }
    with pytest.raises(ValueError, match="mounted.*membership"):
        parse_lsblk_json(payload, boot_path="/dev/sdc")
