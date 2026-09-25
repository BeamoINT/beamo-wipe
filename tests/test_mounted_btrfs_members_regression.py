"""Mounted multi-device Btrfs membership cannot be inferred from lsblk UUIDs."""

import pytest

from beamo_wipe.discover import discover, parse_lsblk_json


def _disk(name, *, children=None, tran="sata"):
    row = {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "size": 16_000_000_000 if name == "sdc" else 500_000_000_000,
        "tran": tran,
        "serial": name.upper(),
        "ro": False,
        "mountpoints": [None],
    }
    if children is not None:
        row["children"] = children
    return row


def _part(name, *, fstype, uuid, mounted=False):
    return {
        "name": name,
        "path": f"/dev/{name}",
        "type": "part",
        "fstype": fstype,
        "uuid": uuid,
        "mountpoints": ["/mnt/data"] if mounted else [None],
    }


@pytest.mark.parametrize(
    "second_fstype,second_uuid",
    [("btrfs", None), ("btrfs", "STALE-OTHER"), (None, None)],
)
def test_mounted_btrfs_refuses_unproven_members(second_fstype, second_uuid):
    rows = [
        _disk(
            "sda", children=[_part("sda1", fstype="btrfs", uuid="FS-A", mounted=True)]
        ),
        _disk("sdb", children=[_part("sdb1", fstype=second_fstype, uuid=second_uuid)]),
        _disk("sdc", tran="usb"),
    ]
    payload = {"blockdevices": rows}
    with pytest.raises(ValueError, match="Btrfs membership"):
        parse_lsblk_json(payload, boot_path="/dev/sdc")
    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sdc",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified and result.selectable == ()


def test_mounted_ext4_keeps_unrelated_unmounted_disk_selectable():
    rows = [
        _disk(
            "sda", children=[_part("sda1", fstype="ext4", uuid="FS-A", mounted=True)]
        ),
        _disk("sdb", children=[_part("sdb1", fstype="ext4", uuid="FS-B")]),
        _disk("sdc", tran="usb"),
    ]
    result = parse_lsblk_json({"blockdevices": rows}, boot_path="/dev/sdc")
    assert [disk.path for disk in result.selectable] == ["/dev/sdb"]
