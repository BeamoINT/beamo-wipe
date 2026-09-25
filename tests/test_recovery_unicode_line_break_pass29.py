"""Recovered disk identity must not gain visual lines from a journal record."""

from dataclasses import asdict
from pathlib import Path

import pytest

from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.session_recovery import _disk


FIXTURE = Path(__file__).parent / "fixtures" / "lsblk_vm_iso.json"


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
@pytest.mark.parametrize("field", ["model", "serial", "wwn"])
def test_recovered_disk_identity_rejects_visual_line_separator(field, separator):
    payload = load_lsblk_json_text(FIXTURE.read_text())
    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=["/dev/sr0"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    disk = next(d for d in result.disks if d.path == "/dev/vda")
    raw = asdict(disk)
    raw["mountpoints"] = []
    raw[field] = f"Data SSD{separator}Beamo boot USB"

    with pytest.raises(ValueError, match="Invalid disk text"):
        _disk(raw)
