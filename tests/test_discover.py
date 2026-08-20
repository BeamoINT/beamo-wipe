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


def _payload(blockdevices):
    return {"blockdevices": blockdevices}


def test_duplicate_beamo_wipe_labels_fail_closed():
    """Two BEAMO_WIPE labels: cannot tell which stick we booted. List nothing."""
    payload = _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "rota": True,
                "model": "ST500DM002",
                "serial": "INTERNAL01",
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                    }
                ],
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                    }
                ],
            },
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "size": 256060514304,
                "type": "disk",
                "tran": "nvme",
                "rota": False,
                "model": "SSD",
                "serial": "NVMEAAAA1111",
            },
        ]
    )
    result = discover(
        lsblk_payload=payload,
        boot_path=None,
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.selectable == ()
    assert result.error


def test_live_mount_wins_over_stale_beamo_wipe_label():
    """Leftover BEAMO_WIPE on the internal disk must not mark the USB as a target."""
    payload = _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "rota": True,
                "model": "ST500DM002",
                "serial": "INTERNAL01",
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                    }
                ],
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "BEAMO_LIVE",
                    }
                ],
            },
        ]
    )
    result = discover(
        lsblk_payload=payload,
        boot_path=None,
        mount_sources=["/dev/sdb1"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot_identified
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    assert "/dev/sdb" not in {d.path for d in result.selectable}
    assert "/dev/sda" in {d.path for d in result.selectable}


def test_partition_boot_path_marks_parent_not_selectable():
    result = discover(
        lsblk_payload=_load("lsblk_same_size.json"),
        boot_path="/dev/sdb1",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    assert result.boot.is_boot
    assert "/dev/sdb" not in {d.path for d in result.selectable}
    assert "/dev/sdb1" not in {d.path for d in result.selectable}


def test_loop_label_must_not_make_usb_selectable():
    payload = _payload(
        [
            {
                "name": "loop0",
                "path": "/dev/loop0",
                "size": 412000000,
                "type": "loop",
                "label": "BEAMO_WIPE",
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                    }
                ],
            },
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "size": 256060514304,
                "type": "disk",
                "tran": "nvme",
                "rota": False,
                "model": "SSD",
                "serial": "N1",
            },
        ]
    )
    result = discover(
        lsblk_payload=payload,
        boot_path=None,
        mount_sources=["/dev/sdb1"],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    assert "/dev/sdb" not in {d.path for d in result.selectable}
    assert "/dev/nvme0n1" in {d.path for d in result.selectable}


def test_unresolved_cmdline_bootfrom_fails_closed():
    result = discover(
        lsblk_payload=_load("lsblk_no_boot.json"),
        boot_path=None,
        mount_sources=[],
        cmdline="boot=live bootfrom=/dev/disk/by-label/BEAMO_WIPE",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.selectable == ()
    assert result.error


def test_missing_model_falls_back_to_label():
    payload = _payload(
        [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": None,
                "serial": "BEAMOUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                    }
                ],
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "rota": True,
                "model": None,
                "serial": "Z9A12345",
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "label": "WINDOWS",
                    }
                ],
            },
        ]
    )
    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    windows = next(d for d in result.selectable if d.path == "/dev/sda")
    assert windows.display_name == "WINDOWS"


def test_json_float_size_is_not_zero():
    from beamo_wipe.discover import parse_lsblk_json

    payload = _payload(
        [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000.0,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 256060514304.0,
                "type": "disk",
                "tran": "sata",
                "rota": True,
                "model": "ST500",
                "serial": "Z9A12345",
            },
        ]
    )
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    disk = next(d for d in result.selectable if d.path == "/dev/sda")
    assert disk.size_bytes == 256060514304
    assert disk.size_gb_label != "0"


def test_lsblk_failure_fails_closed(monkeypatch):
    import subprocess

    def _boom(*_a, **_k):
        raise subprocess.CalledProcessError(1, "lsblk")

    monkeypatch.setattr("beamo_wipe.discover.subprocess.run", _boom)
    result = discover(
        boot_path=None,
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.selectable == ()
    assert result.error
