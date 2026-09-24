"""Unowned flat partitions must not disappear from disk guidance."""

from __future__ import annotations

import pytest

from beamo_wipe.discover import discover, parse_lsblk_json
from beamo_wipe.models import CONTENTS_WINDOWS


SIZE = 100_000_000_000


def _disk(name: str, tran: str) -> dict:
    return {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "size": SIZE,
        "tran": tran,
        "ro": 0,
        "mountpoints": [None],
    }


def _payload(*, partition_parent: str | None) -> dict:
    partition = {
        "name": "sda1",
        "path": "/dev/sda1",
        "type": "part",
        "size": SIZE,
        "fstype": "ntfs",
        "partlabel": "Windows Recovery",
        "mountpoints": [None],
    }
    if partition_parent is not None:
        partition["pkname"] = partition_parent
    return {
        "blockdevices": [
            _disk("sda", "sata"),
            _disk("sdb", "usb"),
            partition,
        ]
    }


def test_orphan_flat_windows_partition_refuses_unsafe_inventory() -> None:
    payload = _payload(partition_parent=None)
    with pytest.raises(ValueError, match="partition ancestry"):
        parse_lsblk_json(payload, boot_path="/dev/sdb")

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sdb",
        mount_sources=["/dev/sdb"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert not result.selectable


def test_flat_windows_partition_with_proven_parent_remains_attributed() -> None:
    result = parse_lsblk_json(_payload(partition_parent="sda"), boot_path="/dev/sdb")
    assert result.boot_identified
    target = next(d for d in result.selectable if d.path == "/dev/sda")
    assert target.contents == CONTENTS_WINDOWS
    assert target.layout_id
