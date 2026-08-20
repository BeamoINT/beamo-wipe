# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from beamo_wipe.discover import discover, load_lsblk_json_text, size_gb_label
from beamo_wipe.models import DiskKind

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return load_lsblk_json_text((FIXTURES / name).read_text(encoding="utf-8"))


def test_size_rounding():
    assert size_gb_label(256060514304) == "256"
    assert size_gb_label(16000000000) == "16"
    assert size_gb_label(10737418240) == "11"


def test_boot_usb_excluded_and_marked():
    result = discover(
        lsblk_payload=_load("lsblk_same_size.json"),
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot_identified
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    assert result.boot.is_boot
    paths = {d.path for d in result.selectable}
    assert "/dev/sdb" not in paths
    assert "/dev/nvme0n1" in paths
    assert "/dev/loop0" not in {d.path for d in result.disks}


def test_identify_from_label_without_override():
    result = discover(
        lsblk_payload=_load("lsblk_same_size.json"),
        boot_path=None,
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"


def test_cannot_identify_boot_refuses_list():
    result = discover(
        lsblk_payload=_load("lsblk_no_boot.json"),
        boot_path=None,
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.error
    assert result.selectable == ()
    assert "Cannot tell which disk is this USB" in result.error


def test_empty_target_disks():
    result = discover(
        lsblk_payload=_load("lsblk_only_boot.json"),
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot_identified
    assert result.selectable == ()


def test_vm_iso_boot_marks_rom_and_lists_virtio():
    result = discover(
        lsblk_payload=_load("lsblk_vm_iso.json"),
        boot_path="/dev/sr0",
        mount_sources=["/dev/sr0"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sr0"
    assert result.boot.is_boot
    assert [d.path for d in result.selectable] == ["/dev/vda"]
    assert result.selectable[0].kind == DiskKind.HDD
    assert result.selectable[0].size_gb_label == "11"


def test_identify_from_live_mount():
    result = discover(
        lsblk_payload=_load("lsblk_vm_iso.json"),
        boot_path=None,
        mount_sources=["/dev/sr0"],
        cmdline="boot=live components",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sr0"


def test_nvme_and_hdd_kinds():
    result = discover(
        lsblk_payload=_load("lsblk_same_size.json"),
        boot_path="/dev/sdb",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
        mount_sources=[],
        cmdline="",
    )
    kinds = {d.path: d.kind for d in result.selectable}
    assert kinds["/dev/nvme0n1"] == DiskKind.NVME
    assert kinds["/dev/nvme1n1"] == DiskKind.NVME
