"""An abbreviated hardware ID must not become a stable disk identity."""

import pytest

from beamo_wipe.discover import parse_lsblk_json


def _inventory(*, serial=None, wwn=None, child_serial=None):
    return parse_lsblk_json(
        {
            "blockdevices": [
                {
                    "name": "sdb",
                    "path": "/dev/sdb",
                    "type": "disk",
                    "size": 16_000_000_000,
                    "tran": "usb",
                    "model": "Beamo boot",
                    "serial": "BOOT-123",
                },
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 512_000_000_000,
                    "tran": "sata",
                    "model": "Target",
                    "serial": serial,
                    "wwn": wwn,
                    "children": [
                        {
                            "name": "sda1",
                            "path": "/dev/sda1",
                            "type": "part",
                            "pkname": "sda",
                            "size": 500_000_000_000,
                            "serial": child_serial,
                        }
                    ],
                },
            ]
        },
        boot_path="/dev/sdb",
    )


@pytest.mark.parametrize("field", ("serial", "wwn", "child_serial"))
def test_overlong_hardware_id_is_not_a_selectable_identity(field):
    # Before the fix, all three raw values were truncated to the same 128
    # characters. A fake fresh rescan replacing suffix 1 with 2 passed
    # assert_rediscovered_identity even though the hardware ID had changed.
    before = _inventory(**{field: "A" * 128 + "1"})
    after = _inventory(**{field: "A" * 128 + "2"})
    assert before.boot is not None
    assert after.boot is not None
    assert not before.selectable
    assert not after.selectable
