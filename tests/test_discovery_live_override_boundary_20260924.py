# SPDX-License-Identifier: GPL-3.0-or-later
"""A test-only boot override cannot identify production live media."""

from beamo_wipe.discover import discover
import pytest


def _realistic_inventory():
    return {
        "blockdevices": [
            {
                "name": "sda", "path": "/dev/sda", "type": "disk",
                "tran": "sata", "size": 500_000_000_000,
                "ro": False, "mountpoints": [None],
            },
            {
                "name": "sdb", "path": "/dev/sdb", "type": "disk",
                "tran": "usb", "size": 16_000_000_000,
                "ro": False, "mountpoints": [None],
            },
        ]
    }


@pytest.mark.parametrize("source", ["environment", "argument"])
def test_production_discovery_ignores_test_boot_override_without_mount_proof(
    monkeypatch, source
):
    """An override naming the internal disk must not expose the boot USB."""
    monkeypatch.setattr("beamo_wipe.discover.run_lsblk", _realistic_inventory)
    monkeypatch.setattr("beamo_wipe.discover.read_mount_sources", lambda: [])
    monkeypatch.setattr("beamo_wipe.discover.read_cmdline", lambda: "boot=live")

    env = {"BEAMO_WIPE_BOOT_DEVICE": "/dev/sda"} if source == "environment" else {}
    boot_path = "/dev/sda" if source == "argument" else None
    result = discover(env=env, boot_path=boot_path)

    assert result.boot_identified is False
    assert result.selectable == ()


def test_injected_fixture_keeps_explicit_boot_override_for_preview():
    result = discover(
        lsblk_payload=_realistic_inventory(),
        boot_path="/dev/sdb",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert result.boot_identified is True
    assert result.boot.path == "/dev/sdb"
    assert [disk.path for disk in result.selectable] == ["/dev/sda"]


def test_production_mount_proof_wins_over_test_override(monkeypatch):
    monkeypatch.setattr("beamo_wipe.discover.run_lsblk", _realistic_inventory)
    monkeypatch.setattr("beamo_wipe.discover.read_mount_sources", lambda: ["/dev/sdb"])
    monkeypatch.setattr("beamo_wipe.discover.read_cmdline", lambda: "boot=live")

    result = discover(
        env={"BEAMO_WIPE_BOOT_DEVICE": "/dev/sda"},
        boot_path="/dev/sda",
    )

    assert result.boot_identified is True
    assert result.boot.path == "/dev/sdb"
    assert [disk.path for disk in result.selectable] == ["/dev/sda"]
