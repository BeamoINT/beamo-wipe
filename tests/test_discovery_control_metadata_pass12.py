"""Control characters in confirmed metadata cannot vanish from identity."""

import pytest

from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.safety import disk_identity


def _scan(field: str, value: str):
    boot = {
        "name": "sdb",
        "path": "/dev/sdb",
        "type": "disk",
        "size": 16_000_000_000,
        "tran": "usb",
        "serial": "BOOT",
    }
    part = {
        "name": "sda1",
        "path": "/dev/sda1",
        "type": "part",
        "pkname": "sda",
        "size": 500_000_000_000,
        "fstype": "ext4",
        "uuid": "UUID",
    }
    target = {
        "name": "sda",
        "path": "/dev/sda",
        "type": "disk",
        "size": 512_000_000_000,
        "tran": "sata",
        "serial": "TARGET",
        "model": "Target",
        "vendor": "Vendor",
        "children": [part],
    }
    (target if field in {"model", "vendor"} else part)[field] = value
    result = parse_lsblk_json({"blockdevices": [boot, target]}, boot_path="/dev/sdb")
    return result.selectable[0] if result.selectable else None


@pytest.mark.parametrize(
    "field", ("model", "vendor", "label", "partlabel", "parttypename")
)
@pytest.mark.parametrize("bad", ("AB\nCD", "AB\u202eCD"))
def test_control_character_cannot_merge_distinct_confirmed_metadata(field, bad):
    malformed = _scan(field, bad)
    clean = _scan(field, "ABCD")
    assert clean is not None
    assert malformed is None or disk_identity(malformed) != disk_identity(clean)
