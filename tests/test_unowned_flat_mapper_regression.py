"""An opened volume without a physical owner cannot hide disk contents."""

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


def _payload(*, parent: str | None, filesystem: bool) -> dict:
    mapper = {
        "name": "dm-0",
        "path": "/dev/dm-0",
        "type": "crypt",
        "size": SIZE,
        "mountpoints": [None],
    }
    if parent is not None:
        mapper["pkname"] = parent
    if filesystem:
        mapper.update(fstype="ntfs", uuid="WIN-FS", label="Windows")
    return {"blockdevices": [_disk("sda", "sata"), _disk("sdb", "usb"), mapper]}


def test_unowned_flat_mapper_with_windows_evidence_refuses_inventory() -> None:
    payload = _payload(parent=None, filesystem=True)
    with pytest.raises(ValueError, match="filesystem ancestry"):
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


def test_empty_unowned_mapper_does_not_hide_unrelated_disk() -> None:
    result = parse_lsblk_json(
        _payload(parent=None, filesystem=False), boot_path="/dev/sdb"
    )
    assert result.boot_identified
    assert [d.path for d in result.selectable] == ["/dev/sda"]


def test_flat_mapper_with_proven_parent_attributes_windows_evidence() -> None:
    result = parse_lsblk_json(
        _payload(parent="sda", filesystem=True), boot_path="/dev/sdb"
    )
    target = next(d for d in result.selectable if d.path == "/dev/sda")
    assert target.contents == CONTENTS_WINDOWS
    assert target.layout_id
