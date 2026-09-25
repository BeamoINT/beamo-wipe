"""Filesystem label whitespace is part of final rediscovery identity."""

import pytest

from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.safety import disk_identity


def _target(field: str, value: str):
    boot = {
        "name": "sdb",
        "path": "/dev/sdb",
        "type": "disk",
        "size": 16_000_000_000,
        "tran": "usb",
        "serial": "BOOT",
    }
    partition = {
        "name": "sda1",
        "path": "/dev/sda1",
        "type": "part",
        "pkname": "sda",
        "size": 500_000_000_000,
        "fstype": "ext4",
        "uuid": "FS-UUID",
        field: value,
    }
    target = {
        "name": "sda",
        "path": "/dev/sda",
        "type": "disk",
        "size": 512_000_000_000,
        "tran": "sata",
        "serial": "TARGET",
        "model": "Target",
        "children": [partition],
    }
    result = parse_lsblk_json({"blockdevices": [boot, target]}, boot_path="/dev/sdb")
    assert len(result.selectable) == 1
    return result.selectable[0]


@pytest.mark.parametrize("field", ("label", "partlabel"))
@pytest.mark.parametrize("altered", (" Owner Data", "Owner Data "))
def test_whitespace_change_in_volume_label_changes_layout_identity(field, altered):
    plain = _target(field, "Owner Data")
    spaced = _target(field, altered)
    assert disk_identity(plain) != disk_identity(spaced)
