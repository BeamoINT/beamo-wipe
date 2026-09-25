# SPDX-License-Identifier: GPL-3.0-or-later
"""An old live-medium mount cannot prove the current mounted source."""

from beamo_wipe.discover import live_medium_is_mounted
from beamo_wipe.safety import is_live_environment


def test_overmounted_live_medium_does_not_enable_real_live_gate():
    mountinfo = (
        "36 1 8:1 / /run/live/medium rw - ext4 /dev/sda1 rw\n"
        "37 36 0:48 / /run/live/medium rw - tmpfs tmpfs rw\n"
    )

    assert not live_medium_is_mounted(text=mountinfo)
    assert not is_live_environment(cmdline="boot=live", mountinfo_text=mountinfo)


def test_single_live_medium_mount_still_proves_gate():
    mountinfo = "36 1 8:1 / /run/live/medium rw - ext4 /dev/sda1 rw\n"

    assert live_medium_is_mounted(text=mountinfo)
    assert is_live_environment(cmdline="boot=live", mountinfo_text=mountinfo)


def test_two_distinct_live_mount_paths_still_prove_gate():
    mountinfo = (
        "36 1 8:1 / /run/live/medium rw - ext4 /dev/sda1 rw\n"
        "37 1 8:1 / /lib/live/mount/medium rw - ext4 /dev/sda1 rw\n"
    )

    assert live_medium_is_mounted(text=mountinfo)


def test_duplicate_device_mount_at_same_path_is_ambiguous():
    mountinfo = (
        "36 1 8:1 / /run/live/medium rw - ext4 /dev/sda1 rw\n"
        "37 36 8:2 / /run/live/medium rw - ext4 /dev/sdb1 rw\n"
    )

    assert not live_medium_is_mounted(text=mountinfo)
