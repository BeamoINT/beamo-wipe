# SPDX-License-Identifier: GPL-3.0-or-later
"""An absent by-label device link cannot establish a boot disk."""

import os

import beamo_wipe.discover as discovery
from beamo_wipe.discover import discover


def test_missing_boot_source_link_does_not_protect_matching_stale_label(monkeypatch):
    alias = "/dev/disk/by-label/LIVE"
    original = os.path.realpath
    monkeypatch.setattr(
        os.path,
        "realpath",
        lambda path: alias if str(path) == alias else original(path),
    )
    payload = {
        "blockdevices": [
            {
                "name": "sda", "path": "/dev/sda", "type": "disk",
                "size": 500_000_000_000, "tran": "sata", "serial": "TARGET",
                "ro": 0, "mountpoints": [],
                "children": [{
                    "name": "sda1", "path": "/dev/sda1", "type": "part",
                    "pkname": "sda", "label": "LIVE", "mountpoints": [],
                }],
            },
            {
                "name": "sdb", "path": "/dev/sdb", "type": "disk",
                "size": 16_000_000_000, "tran": "usb", "serial": "ACTUAL-BOOT",
                "ro": 0, "mountpoints": [],
            },
        ]
    }
    monkeypatch.setattr(discovery, "run_lsblk", lambda: payload)

    result = discover(
        mount_sources=[alias],
        cmdline="boot=live",
        env={},
    )

    assert not result.boot_identified
    assert result.selectable == ()
