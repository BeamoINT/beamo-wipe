"""An unresolved preview boot override cannot be ignored when mounts exist."""

import json
from pathlib import Path

import pytest

from beamo_wipe.discover import discover


@pytest.mark.parametrize("override", ["/dev/does-not-exist", "LABEL=NOT-ON-USB"])
def test_unresolved_boot_override_with_valid_live_mount_fails_closed(override):
    payload = json.loads(
        (Path(__file__).parent / "fixtures/lsblk_same_size.json").read_text()
    )

    result = discover(
        lsblk_payload=payload,
        boot_path=override,
        mount_sources=["/dev/sdb1"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert not result.boot_identified
    assert result.selectable == ()


def test_matching_boot_override_and_live_mount_remain_usable():
    payload = json.loads(
        (Path(__file__).parent / "fixtures/lsblk_same_size.json").read_text()
    )

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sdb",
        mount_sources=["/dev/sdb1"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert result.boot_identified
    assert result.boot is not None and result.boot.path == "/dev/sdb"
    assert "/dev/sdb" not in {disk.path for disk in result.selectable}
