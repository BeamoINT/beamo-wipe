"""A mounted mapper's explicit parent must agree with its lsblk tree."""

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


def _part(name: str, *, children: list[dict] | None = None) -> dict:
    row = {
        "name": name,
        "path": f"/dev/{name}",
        "type": "part",
        "pkname": name[:-1],
        "size": SIZE,
        "mountpoints": [None],
    }
    if children is not None:
        row["children"] = children
    return row


def _payload(mapper_parent: str) -> dict:
    mapper = {
        "name": "dm-0",
        "path": "/dev/dm-0",
        "type": "crypt",
        "pkname": mapper_parent,
        "size": SIZE,
        "fstype": "ext4",
        "mountpoints": ["/mnt/data"],
    }
    return {
        "blockdevices": [
            _disk("sda", children=[_part("sda1", children=[mapper])]),
            _disk("sdb", children=[_part("sdb1")]),
            _disk("sdc"),
        ]
    }


def test_mounted_mapper_conflicting_tree_and_pkname_refuses_inventory() -> None:
    payload = _payload("sdb1")
    with pytest.raises(ValueError, match="mounted ancestry"):
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


def test_mounted_mapper_consistent_tree_and_pkname_keeps_unrelated_disk() -> None:
    result = parse_lsblk_json(_payload("sda1"), boot_path="/dev/sdc")
    assert result.boot_identified
    assert [(d.path, d.mountpoints) for d in result.disks] == [
        ("/dev/sda", ("/mnt/data",)),
        ("/dev/sdb", ()),
        ("/dev/sdc", ()),
    ]
    assert [d.path for d in result.selectable] == ["/dev/sdb"]


def _flat_mapper_payload(*, wrong_tree: bool) -> dict:
    # The partition has no mountpoint of its own. A flat mounted mapper names
    # it through PKNAME, so the ancestry walk still has to validate the tree.
    part = {
        "name": "sda1",
        "path": "/dev/sda1",
        "type": "part",
        "size": SIZE,
        "mountpoints": [None],
    }
    mapper = {
        "name": "dm-0",
        "path": "/dev/dm-0",
        "type": "crypt",
        "pkname": "sda1",
        "size": SIZE,
        "fstype": "ext4",
        "mountpoints": ["/mnt/data"],
    }
    a = _disk("sda", children=[] if wrong_tree else [part])
    b = _disk("sdb", children=[part] if wrong_tree else [])
    return {"blockdevices": [a, b, _disk("sdc"), mapper]}


def test_flat_mounted_mapper_rejects_wrong_unmounted_partition_ancestor() -> None:
    payload = _flat_mapper_payload(wrong_tree=True)
    with pytest.raises(ValueError, match="partition ancestry"):
        parse_lsblk_json(payload, boot_path="/dev/sdc")


def test_flat_mounted_mapper_accepts_consistent_partition_ancestor() -> None:
    result = parse_lsblk_json(
        _flat_mapper_payload(wrong_tree=False), boot_path="/dev/sdc"
    )
    assert [(d.path, d.mountpoints) for d in result.disks] == [
        ("/dev/sda", ("/mnt/data",)),
        ("/dev/sdb", ()),
        ("/dev/sdc", ()),
    ]
    assert [d.path for d in result.selectable] == ["/dev/sdb"]


def test_unmounted_flat_partition_cannot_move_windows_evidence_to_wrong_disk() -> None:
    partition = {
        "name": "sda1",
        "path": "/dev/sda1",
        "type": "part",
        "pkname": "sdb",
        "size": SIZE,
        "fstype": "ntfs",
        "partlabel": "Windows Recovery",
        "mountpoints": [None],
    }
    payload = {"blockdevices": [_disk("sda"), _disk("sdb"), _disk("sdc"), partition]}
    with pytest.raises(ValueError, match="partition ancestry"):
        parse_lsblk_json(payload, boot_path="/dev/sdc")


def _two_mapper_payload(*, intermediate_parent: str) -> dict:
    intermediate = {
        "name": "dm-0",
        "path": "/dev/dm-0",
        "type": "crypt",
        "pkname": intermediate_parent,
        "size": SIZE,
        "mountpoints": [None],
    }
    mounted = {
        "name": "dm-1",
        "path": "/dev/dm-1",
        "type": "crypt",
        "pkname": "dm-0",
        "size": SIZE,
        "fstype": "ext4",
        "mountpoints": ["/mnt/data"],
    }
    return {
        "blockdevices": [
            _disk("sda", children=[_part("sda1", children=[intermediate])]),
            _disk("sdb", children=[_part("sdb1")]),
            _disk("sdc"),
            mounted,
        ]
    }


def test_flat_mounted_mapper_checks_unmounted_intermediate_mapper_parent() -> None:
    payload = _two_mapper_payload(intermediate_parent="sdb1")
    with pytest.raises(ValueError, match="mounted ancestry"):
        parse_lsblk_json(payload, boot_path="/dev/sdc")


def test_flat_mounted_mapper_accepts_consistent_intermediate_mapper_parent() -> None:
    result = parse_lsblk_json(
        _two_mapper_payload(intermediate_parent="sda1"), boot_path="/dev/sdc"
    )
    assert [(d.path, d.mountpoints) for d in result.disks] == [
        ("/dev/sda", ("/mnt/data",)),
        ("/dev/sdb", ()),
        ("/dev/sdc", ()),
    ]
    assert [d.path for d in result.selectable] == ["/dev/sdb"]


def _unmounted_nested_mapper_payload(*, mapper_parent: str) -> dict:
    mapper = {
        "name": "dm-0",
        "path": "/dev/dm-0",
        "type": "crypt",
        "pkname": mapper_parent,
        "size": SIZE,
        "fstype": "ntfs",
        "label": "Windows",
        "mountpoints": [None],
    }
    return {
        "blockdevices": [
            _disk("sda", children=[_part("sda1", children=[mapper])]),
            _disk("sdb", children=[_part("sdb1")]),
            _disk("sdc"),
        ]
    }


def test_unmounted_nested_mapper_filesystem_rejects_conflicting_parent() -> None:
    payload = _unmounted_nested_mapper_payload(mapper_parent="sdb1")
    with pytest.raises(ValueError, match="filesystem ancestry"):
        parse_lsblk_json(payload, boot_path="/dev/sdc")


def test_unmounted_nested_mapper_filesystem_accepts_consistent_parent() -> None:
    result = parse_lsblk_json(
        _unmounted_nested_mapper_payload(mapper_parent="sda1"),
        boot_path="/dev/sdc",
    )
    assert result.boot_identified
    assert [d.path for d in result.selectable] == ["/dev/sda", "/dev/sdb"]
    assert result.disks[0].contents == "windows"
    assert result.disks[1].contents == "unknown"
