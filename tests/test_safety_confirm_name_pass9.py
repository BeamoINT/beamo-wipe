"""Confirmation tokens must not be kernel names shown for any listed disk."""

import pytest

from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.safety import confirm_spec, listed_disks


@pytest.mark.parametrize("target_serial", ("sda", "sdb"))
def test_serial_equal_to_own_or_different_size_peer_name_is_not_token(target_serial):
    result = parse_lsblk_json(
        {
            "blockdevices": [
                {
                    "name": "sr0",
                    "path": "/dev/sr0",
                    "type": "rom",
                    "size": 2_000_000_000,
                    "tran": "sata",
                    "serial": "BOOT",
                },
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 500_000_000_000,
                    "tran": "sata",
                    "serial": target_serial,
                    "wwn": "TARGET-WWN-0001",
                },
                {
                    "name": "sdb",
                    "path": "/dev/sdb",
                    "type": "disk",
                    "size": 64_000_000_000,
                    "tran": "sata",
                    "serial": "DIFFERENT",
                },
                {
                    "name": "sdc",
                    "path": "/dev/sdc",
                    "type": "disk",
                    "size": 500_000_000_000,
                    "tran": "sata",
                    "serial": "PEER-UNIQUE",
                },
            ]
        },
        boot_path="/dev/sr0",
    )

    target = next(disk for disk in result.selectable if disk.path == "/dev/sda")
    spec = confirm_spec(target, listed_disks(result))
    assert spec.token == "0001"
