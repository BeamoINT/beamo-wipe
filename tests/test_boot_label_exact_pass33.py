"""A lookalike filesystem label cannot identify the live USB."""

import json
from pathlib import Path

import pytest

from beamo_wipe.discover import discover, identify_boot_path


FIXTURE = Path(__file__).parent / "fixtures" / "lsblk_same_size.json"


@pytest.mark.parametrize(
    "label",
    ["BEAMO?WIPE", "BEAMO💾WIPE", "BEAMO__WIPE", "BEAMO\n_WIPE", " BEAMO_WIPE "],
)
def test_lookalike_label_does_not_prove_boot_identity(label):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["blockdevices"] = payload["blockdevices"][:1]
    payload["blockdevices"][0]["children"][0]["label"] = label
    assert identify_boot_path(payload["blockdevices"], mount_sources=[], cmdline="") is None
    found = discover(
        lsblk_payload=payload, mount_sources=[], cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not found.boot_identified
    assert found.selectable == ()


@pytest.mark.parametrize("label", ["BEAMO_WIPE", "BEAMO-WIPE", "BEAMOWIPE", "beamo_wipe"])
def test_known_boot_label_variants_remain_recognized(label):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["blockdevices"] = payload["blockdevices"][:1]
    payload["blockdevices"][0]["children"][0]["label"] = label
    found = discover(
        lsblk_payload=payload, mount_sources=[], cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert found.boot_identified
    assert found.boot is not None and found.boot.path == "/dev/sdb"
