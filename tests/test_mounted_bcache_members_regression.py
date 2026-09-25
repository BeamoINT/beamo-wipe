"""Mounted bcache membership cannot be proven from one lsblk parent."""

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


def test_mounted_bcache_refuses_unproven_cache_member() -> None:
    holder = {
        "name": "bcache0",
        "path": "/dev/bcache0",
        "type": "disk",
        "pkname": "sda",
        "size": SIZE,
        "fstype": "ext4",
        "mountpoints": ["/mnt/data"],
    }
    payload = {
        "blockdevices": [
            _disk("sda", children=[holder]),
            _disk("sdb"),  # Cache-member FSTYPE may be absent or stale.
            _disk("sdc"),
        ]
    }
    with pytest.raises(ValueError, match="bcache membership"):
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


def test_direct_mounted_ext4_disk_keeps_unrelated_target() -> None:
    mounted = _disk("sda")
    mounted.update(fstype="ext4", mountpoints=["/mnt/data"])
    result = parse_lsblk_json(
        {"blockdevices": [mounted, _disk("sdb"), _disk("sdc")]},
        boot_path="/dev/sdc",
    )
    assert result.boot_identified
    assert [d.path for d in result.selectable] == ["/dev/sdb"]
