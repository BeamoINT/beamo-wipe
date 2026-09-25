"""Typed live mount sources must not be repaired into another disk's metadata."""

import pytest

from beamo_wipe.discover import discover


@pytest.mark.parametrize(
    ("source", "field", "reported"),
    (
        ("LABEL=BEAMO_WIPE", "label", "BEAMO_\nWIPE"),
        ("LABEL=BEAMO_WIPE", "label", "beamo_wipe"),
        ('LABEL=" BEAMO_WIPE"', "label", "BEAMO_WIPE"),
        ("LABEL=BEAMO_WIPE ", "label", "BEAMO_WIPE"),
        (" LABEL=BEAMO_WIPE", "label", "BEAMO_WIPE"),
        ("LABEL=BEAMO_WIPE[other]", "label", "BEAMO_WIPE"),
        ("/dev/disk/by-label/BEAMO_WIPE ", "label", "BEAMO_WIPE"),
        ("UUID=" + "A" * 128, "uuid", "A" * 128 + "Z"),
        ("UUID=BOOT-ID", "uuid", " BOOT-ID"),
        ("UUID=BOOT-ID ", "uuid", "BOOT-ID"),
        ("PARTLABEL=BEAMO_WIPE", "partlabel", "BEAMO_\nWIPE"),
        ("PARTLABEL=BEAMO_WIPE", "partlabel", "beamo_wipe"),
    ),
)
def test_malformed_or_nonmatching_typed_source_cannot_identify_wrong_boot_disk(
    source, field, reported
):
    # /dev/sdb is the actual live USB, but the only lsblk value remotely
    # resembling the mount source belongs to the internal /dev/sda target.
    result = discover(
        lsblk_payload={
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 512_000_000_000,
                    "tran": "sata",
                    "serial": "TARGET-123",
                    "children": [
                        {
                            "name": "sda1",
                            "path": "/dev/sda1",
                            "type": "part",
                            "pkname": "sda",
                            field: reported,
                        }
                    ],
                },
                {
                    "name": "sdb",
                    "path": "/dev/sdb",
                    "type": "disk",
                    "size": 16_000_000_000,
                    "tran": "usb",
                    "serial": "BOOT-123",
                },
            ]
        },
        mount_sources=[source],
        cmdline="boot=live",
        env={},
    )

    assert not result.boot_identified
    assert not result.selectable


@pytest.mark.parametrize(
    "source", ('LABEL=" BEAMO_WIPE"', r"/dev/disk/by-label/\x20BEAMO_WIPE")
)
def test_exact_space_bearing_boot_label_still_identifies_live_usb(source):
    result = discover(
        lsblk_payload={
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 512_000_000_000,
                    "tran": "sata",
                    "serial": "TARGET-123",
                    "children": [
                        {
                            "name": "sda1",
                            "path": "/dev/sda1",
                            "type": "part",
                            "pkname": "sda",
                            "label": "BEAMO_WIPE",
                        }
                    ],
                },
                {
                    "name": "sdb",
                    "path": "/dev/sdb",
                    "type": "disk",
                    "size": 16_000_000_000,
                    "tran": "usb",
                    "serial": "BOOT-123",
                    "children": [
                        {
                            "name": "sdb1",
                            "path": "/dev/sdb1",
                            "type": "part",
                            "pkname": "sdb",
                            "label": " BEAMO_WIPE",
                        }
                    ],
                },
            ]
        },
        mount_sources=[source],
        cmdline="boot=live",
        env={},
    )

    assert result.boot_identified
    assert result.boot is not None and result.boot.path == "/dev/sdb"
    assert {disk.path for disk in result.selectable} == {"/dev/sda"}
