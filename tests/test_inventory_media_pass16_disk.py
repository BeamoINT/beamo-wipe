"""The protected boot medium is named from its device, not lsblk TRAN."""

import pytest

from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.inventory import count_summary
from test_excluded_inventory import node


@pytest.mark.parametrize("transport", ("ata", "sata", ""))
def test_usb_bridge_boot_disk_is_not_called_an_optical_disc(transport):
    result = parse_lsblk_json(
        {"blockdevices": [
            node("sda", tran="sata"),
            node("sdb", tran=transport, mountpoints=["/run/live/medium"]),
        ]},
        boot_path="/dev/sdb",
    )

    assert result.boot is not None and result.boot.path == "/dev/sdb"
    assert result.selectable[0].path == "/dev/sda"
    assert "Beamo USB protected" in count_summary(result)
    assert "boot disc" not in count_summary(result)


def test_optical_boot_device_is_called_disc():
    result = parse_lsblk_json(
        {"blockdevices": [
            node("sda", tran="sata"),
            node("sr0", type="rom", tran="ata", mountpoints=["/run/live/medium"]),
        ]},
        boot_path="/dev/sr0",
    )

    assert result.boot is not None and result.boot.path == "/dev/sr0"
    assert "Beamo boot disc protected" in count_summary(result)
