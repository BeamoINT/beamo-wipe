"""A missing lsblk NAME cannot bypass the SCSI transport gate."""

from beamo_wipe.discover import parse_lsblk_json


def test_empty_kernel_name_with_scsi_path_and_unknown_transport_is_not_selectable():
    result = parse_lsblk_json(
        {
            "blockdevices": [
                {
                    "name": "sdb",
                    "path": "/dev/sdb",
                    "type": "disk",
                    "size": 16_000_000_000,
                    "tran": "usb",
                    "serial": "BOOT-123",
                },
                {
                    "name": "",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 512_000_000_000,
                    "tran": None,
                    "serial": "TARGET-123",
                },
            ]
        },
        boot_path="/dev/sdb",
    )

    assert result.boot_identified
    assert not result.selectable
