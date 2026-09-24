"""A mounted partition cannot hide its physical disk behind false ancestry."""

import pytest

from beamo_wipe.discover import discover, parse_lsblk_json


def _disk(name, *, tran="sata", children=None):
    row = {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "size": 500_000_000_000,
        "tran": tran,
        "serial": name.upper(),
        "ro": False,
        "mountpoints": [None],
    }
    if children is not None:
        row["children"] = children
    return row


def _mounted_partition(*, pkname=None):
    row = {
        "name": "sdb1",
        "path": "/dev/sdb1",
        "type": "part",
        "size": 499_000_000_000,
        "fstype": "ext4",
        "mountpoints": ["/mnt/data"],
    }
    if pkname is not None:
        row["pkname"] = pkname
    return row


@pytest.mark.parametrize("shape", ["flat", "nested"])
def test_contradictory_mounted_partition_never_exposes_actual_disk(shape):
    if shape == "flat":
        rows = [
            _disk("sda"),
            _disk("sdb"),
            _disk("sdc", tran="usb"),
            _mounted_partition(pkname="sda"),
        ]
    else:
        rows = [
            _disk("sda", children=[_mounted_partition()]),
            _disk("sdb"),
            _disk("sdc", tran="usb"),
        ]
    payload = {"blockdevices": rows}
    with pytest.raises(ValueError, match="mounted ancestry"):
        parse_lsblk_json(payload, boot_path="/dev/sdc")
    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sdc",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified and result.selectable == ()


@pytest.mark.parametrize("shape", ["flat", "nested"])
def test_consistent_mounted_partition_keeps_only_other_disk_selectable(shape):
    if shape == "flat":
        rows = [
            _disk("sda"),
            _disk("sdb"),
            _disk("sdc", tran="usb"),
            _mounted_partition(pkname="sdb"),
        ]
    else:
        rows = [
            _disk("sda"),
            _disk("sdb", children=[_mounted_partition()]),
            _disk("sdc", tran="usb"),
        ]
    result = parse_lsblk_json({"blockdevices": rows}, boot_path="/dev/sdc")
    assert result.boot_identified
    assert [disk.path for disk in result.selectable] == ["/dev/sda"]
    assert next(
        disk for disk in result.disks if disk.path == "/dev/sdb"
    ).mountpoints == ("/mnt/data",)
