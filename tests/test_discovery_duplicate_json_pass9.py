"""A contradictory lsblk JSON field cannot erase safety evidence."""

import pytest

from beamo_wipe.discover import load_lsblk_json_text, parse_lsblk_json


def test_duplicate_mountpoint_key_cannot_make_mounted_target_selectable():
    raw = """{"blockdevices": [
      {"name":"sdb","path":"/dev/sdb","type":"disk","size":16000000000,
       "tran":"usb","mountpoints":["/run/live/medium"]},
      {"name":"sda","path":"/dev/sda","type":"disk","size":512000000000,
       "tran":"sata","mountpoints":["/home"],"mountpoints":[]}
    ]}"""
    with pytest.raises(ValueError, match="duplicate"):
        payload = load_lsblk_json_text(raw)
        # Before the fix, the second mountpoints value won and this returned
        # /dev/sda as a selectable wipe target.
        parse_lsblk_json(payload, boot_path="/dev/sdb")


def test_duplicate_root_key_is_rejected_before_inventory():
    with pytest.raises(ValueError, match="duplicate"):
        load_lsblk_json_text('{"blockdevices":[],"blockdevices":[]}')
