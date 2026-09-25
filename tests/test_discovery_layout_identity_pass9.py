"""Final rediscovery must see every field used as identity or OS evidence."""

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
        "serial": "BOOT-123",
    }
    part = {
        "name": "sda1",
        "path": "/dev/sda1",
        "type": "part",
        "pkname": "sda",
        "size": 500_000_000_000,
        "fstype": "ext4",
        "uuid": "base-uuid",
    }
    target = {
        "name": "sda",
        "path": "/dev/sda",
        "type": "disk",
        "size": 512_000_000_000,
        "tran": "sata",
        "serial": "TARGET-123",
        "model": "Target",
        "vendor": "Vendor",
        "children": [part],
    }
    (target if field in {"model", "vendor"} else part)[field] = value
    result = parse_lsblk_json({"blockdevices": [boot, target]}, boot_path="/dev/sdb")
    return result.selectable[0] if result.selectable else None


@pytest.mark.parametrize(
    "field", ("model", "vendor", "uuid", "partuuid", "label", "fstype", "partlabel")
)
def test_overlong_identity_and_layout_fields_cannot_collide(field):
    before = _scan(field, "A" * 128 + "1")
    after = _scan(field, "A" * 128 + "2")
    assert (
        before is None or after is None or disk_identity(before) != disk_identity(after)
    )


@pytest.mark.parametrize(
    ("field", "before", "after"),
    (
        ("partlabel", "Data", "Windows Recovery"),
        ("parttypename", "Linux filesystem", "Windows Recovery"),
        (
            "parttype",
            "0fc63daf-8483-4772-8e79-3d69d8477de4",
            "de94bba4-06d1-4d40-a16a-bfd50179d6ac",
        ),
    ),
)
def test_partition_os_evidence_change_alters_confirmed_identity(field, before, after):
    old = _scan(field, before)
    new = _scan(field, after)
    assert old is not None and new is not None
    assert old.contents != new.contents
    assert disk_identity(old) != disk_identity(new)


@pytest.mark.parametrize("field", ("fstype", "uuid", "partuuid", "parttype"))
def test_control_character_cannot_merge_distinct_storage_identifiers(field):
    malformed = _scan(field, "AB\nCD")
    clean = _scan(field, "ABCD")
    assert (
        malformed is None
        or clean is None
        or disk_identity(malformed) != disk_identity(clean)
    )


@pytest.mark.parametrize("field", ("label", "partlabel"))
def test_case_sensitive_volume_names_keep_distinct_layout_identity(field):
    upper = _scan(field, "OwnerData")
    lower = _scan(field, "ownerdata")
    assert upper is not None and lower is not None
    assert disk_identity(upper) != disk_identity(lower)


def test_layout_fields_cannot_collide_at_row_delimiters():
    from beamo_wipe.discover import parse_lsblk_json

    def scan(uuid, partuuid):
        payload = {
            "blockdevices": [
                {
                    "name": "sdb",
                    "path": "/dev/sdb",
                    "type": "disk",
                    "size": 16_000_000_000,
                    "tran": "usb",
                    "serial": "BOOT",
                },
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 512_000_000_000,
                    "tran": "sata",
                    "serial": "TARGET",
                    "children": [
                        {
                            "name": "sda1",
                            "path": "/dev/sda1",
                            "type": "part",
                            "pkname": "sda",
                            "size": 500_000_000_000,
                            "fstype": "ext4",
                            "uuid": uuid,
                            "partuuid": partuuid,
                        }
                    ],
                },
            ]
        }
        result = parse_lsblk_json(payload, boot_path="/dev/sdb")
        return result.selectable[0] if result.selectable else None

    first = scan("x|y", "z")
    second = scan("x", "y|z")
    assert (
        first is None or second is None or disk_identity(first) != disk_identity(second)
    )


def test_swapped_equal_size_partition_uuids_change_layout_identity():
    def scan(first_uuid, second_uuid):
        target = {
            "name": "sda",
            "path": "/dev/sda",
            "type": "disk",
            "size": 1_000_000_000_000,
            "tran": "sata",
            "serial": "TARGET",
            "children": [
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "pkname": "sda",
                    "size": 500_000_000_000,
                    "fstype": "ext4",
                    "uuid": first_uuid,
                },
                {
                    "name": "sda2",
                    "path": "/dev/sda2",
                    "type": "part",
                    "pkname": "sda",
                    "size": 500_000_000_000,
                    "fstype": "ext4",
                    "uuid": second_uuid,
                },
            ],
        }
        boot = {
            "name": "sdb",
            "path": "/dev/sdb",
            "type": "disk",
            "size": 16_000_000_000,
            "tran": "usb",
            "serial": "BOOT",
        }
        result = parse_lsblk_json(
            {"blockdevices": [boot, target]}, boot_path="/dev/sdb"
        )
        assert result.selectable
        return result.selectable[0]

    old = scan("UUID-A", "UUID-B")
    new = scan("UUID-B", "UUID-A")
    assert disk_identity(old) != disk_identity(new)
