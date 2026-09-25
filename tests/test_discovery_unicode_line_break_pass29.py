"""A drive cannot add a new visual line to its owner-facing identity."""

import copy
from pathlib import Path

import pytest

from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.identity import present_disk


FIXTURE = Path(__file__).parent / "fixtures" / "lsblk_vm_iso.json"


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
@pytest.mark.parametrize("field", ["model", "serial", "wwn"])
def test_drive_identity_line_separator_cannot_spoof_picker_identity(field, separator):
    payload = copy.deepcopy(load_lsblk_json_text(FIXTURE.read_text()))
    target = next(node for node in payload["blockdevices"] if node["path"] == "/dev/vda")
    target[field] = f"Data SSD{separator}Beamo boot USB"

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=["/dev/sr0"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert result.boot_identified and result.boot.path == "/dev/sr0"
    assert not any(d.path == "/dev/vda" for d in result.selectable)
    assert all(separator not in present_disk(d, result.disks).announcement for d in result.disks)
