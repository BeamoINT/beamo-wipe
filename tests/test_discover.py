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
    assert "cannot tell which disk is this usb" in result.error.lower()


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


def test_read_only_disk_is_not_selectable():
    """A write-protected disk (lsblk RO=1) must be excluded up front.

    nwipe cannot erase it; listing it invites a late, confusing failure.
    Missing RO (older payloads) still means writable — exclude only an
    explicit read-only flag, never on unknown.
    """
    payload = _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
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
                "size": 32000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "ro": "1",
                "model": "Locked Stick",
                "serial": "LOCKED001",
            },
            {
                "name": "sdc",
                "path": "/dev/sdc",
                "size": 64000000000,
                "type": "disk",
                "tran": "sata",
                "rota": True,
                "ro": "0",
                "model": "Data Disk",
                "serial": "DATA001",
            },
        ]
    )
    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sda",
        mount_sources=[],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert [d.path for d in result.selectable] == ["/dev/sdc"]
    by_path = {d.path: d for d in result.disks}
    assert by_path["/dev/sdb"].read_only is True
    assert by_path["/dev/sdc"].read_only is False


def test_duplicate_beamo_wipe_labels_fail_closed():
    """Two USB sticks labeled BEAMO_WIPE: cannot tell which we booted. List nothing."""
    payload = _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": "Other Stick",
                "serial": "OTHERUSB01",
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


def test_stale_internal_beamo_wipe_label_without_mounts_fails_closed():
    """Leftover BEAMO_WIPE on SATA must not mark the internal disk as the USB."""
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
                        "label": "DATA",
                    }
                ],
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


def test_env_boot_disagreeing_with_mount_fails_closed():
    result = discover(
        lsblk_payload=_load("lsblk_same_size.json"),
        boot_path="/dev/nvme0n1",
        mount_sources=["/dev/sdb1"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.selectable == ()
    assert result.error


def test_bare_kernel_name_mount_source_identifies_usb():
    from beamo_wipe.discover import normalize_mount_source

    assert normalize_mount_source("sdb1") == "/dev/sdb1"
    assert normalize_mount_source("/dev/sdb1[data]") == "/dev/sdb1"
    assert normalize_mount_source("overlay") == "overlay"
    result = discover(
        lsblk_payload=_load("lsblk_same_size.json"),
        boot_path=None,
        mount_sources=["sdb1"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    assert "/dev/sdb" not in {d.path for d in result.selectable}


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


def test_label_mount_source_identifies_usb():
    result = discover(
        lsblk_payload=_load("lsblk_same_size.json"),
        boot_path=None,
        mount_sources=["LABEL=BEAMO_WIPE"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    assert "/dev/sdb" not in {d.path for d in result.selectable}


def test_unresolvable_mount_source_does_not_fall_through_to_label():
    """findmnt returned something we cannot map. Guessing via labels can pick
    the wrong USB and leave the live medium selectable."""
    payload = _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": "Leftover stick",
                "serial": "OTHERUSB01",
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
                "tran": "sata",
                "rota": True,
                "model": "Actual live USB via SATA bridge",
                "serial": "BEAMOUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "DEBIAN",
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
        mount_sources=["LABEL=DEBIAN_LIVE"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.selectable == ()
    assert result.error


def test_uuid_mount_source_identifies_disk():
    payload = _payload(
        [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                        "uuid": "11111111-2222-3333-4444-555555555555",
                    }
                ],
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "model": "ST500",
                "serial": "Z9A12345",
            },
        ]
    )
    result = discover(
        lsblk_payload=payload,
        boot_path=None,
        mount_sources=["UUID=11111111-2222-3333-4444-555555555555"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    assert "/dev/sdb" not in {d.path for d in result.selectable}


def test_mountinfo_parser_reads_live_medium():
    from beamo_wipe.discover import parse_mountinfo, read_mountinfo_sources

    text = (
        "22 1 0:21 / /run rw - tmpfs tmpfs rw\n"
        "25 22 8:17 / /run/live/medium ro,relatime - iso9660 /dev/sr0 ro\n"
        "26 22 0:24 / /run/user/0 rw - tmpfs tmpfs rw\n"
    )
    pairs = parse_mountinfo(text)
    assert ("/dev/sr0", "/run/live/medium") in pairs
    sources = read_mountinfo_sources(text=text)
    assert sources == ["/dev/sr0"]


def test_lsblk_command_requests_identity_fields():
    from beamo_wipe import discover

    assert "UUID" in discover.LSBLK_COLUMNS
    assert "WWN" in discover.LSBLK_COLUMNS
    assert "PARTUUID" in discover.LSBLK_COLUMNS
    assert "FSVER" in discover.LSBLK_COLUMNS


def _leftover_usb_and_sata_bridge():
    """Leftover USB labeled BEAMO_WIPE plus the real live stick behind a SATA bridge."""
    return _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": "Leftover stick",
                "serial": "OTHERUSB01",
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
                "tran": "sata",
                "rota": True,
                "model": "Actual live USB via SATA bridge",
                "serial": "BEAMOUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "DEBIAN",
                        "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
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


def test_unresolved_cmdline_does_not_fall_through_to_stale_label():
    """bootfrom=/live-media= that we cannot map must not pick a leftover USB."""
    payload = _leftover_usb_and_sata_bridge()
    for cmdline in (
        "boot=live live-media=removable-usb",
        "boot=live bootfrom=/dev/disk/by-label/DEBIAN_LIVE",
        "boot=live img_dev=/dev/does-not-exist",
    ):
        result = discover(
            lsblk_payload=payload,
            boot_path=None,
            mount_sources=[],
            cmdline=cmdline,
            env={"BEAMO_WIPE_DRY_RUN": "1"},
        )
        assert not result.boot_identified, cmdline
        assert result.selectable == ()
        assert result.error


def test_unresolved_env_boot_does_not_fall_through_to_stale_label():
    result = discover(
        lsblk_payload=_leftover_usb_and_sata_bridge(),
        boot_path="/dev/disk/by-label/DEBIAN_LIVE",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.selectable == ()
    assert result.error


def test_duplicate_beamo_wipe_on_usb_and_sata_fails_closed():
    """USB leftover + SATA-bridge live stick, both labeled BEAMO_WIPE."""
    payload = _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "rota": True,
                "model": "Leftover stick",
                "serial": "OTHERUSB01",
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
                "tran": "sata",
                "rota": True,
                "model": "Live stick via SATA bridge",
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
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.selectable == ()
    assert result.error


def test_mmcblk_boot_and_rpmb_are_hidden():
    payload = _payload(
        [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
            },
            {
                "name": "mmcblk0",
                "path": "/dev/mmcblk0",
                "size": 31268536320,
                "type": "disk",
                "tran": "mmc",
                "model": "eMMC",
                "serial": "MMC0",
            },
            {
                "name": "mmcblk0boot0",
                "path": "/dev/mmcblk0boot0",
                "size": 4194304,
                "type": "disk",
                "model": "eMMC boot0",
                "serial": "MMC0",
            },
            {
                "name": "mmcblk0boot1",
                "path": "/dev/mmcblk0boot1",
                "size": 4194304,
                "type": "disk",
                "model": "eMMC boot1",
                "serial": "MMC0",
            },
            {
                "name": "mmcblk0rpmb",
                "path": "/dev/mmcblk0rpmb",
                "size": 4194304,
                "type": "disk",
                "model": "eMMC rpmb",
                "serial": "MMC0",
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
    paths = {d.path for d in result.selectable}
    assert paths == {"/dev/mmcblk0"}
    assert "/dev/mmcblk0boot0" not in {d.path for d in result.disks}
    assert "/dev/mmcblk0rpmb" not in {d.path for d in result.disks}


def test_discovery_boot_is_the_identified_usb_not_a_protected_mount():
    """Internal disk mounted at / must not steal discovery.boot / --exclude."""
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.models import MethodId, WipeRequest
    from beamo_wipe.nwipe_runner import build_nwipe_argv
    from beamo_wipe.safety import selectable_disks

    payload = _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "model": "ST500",
                "serial": "Z9A",
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "mountpoint": "/",
                    }
                ],
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
            },
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "size": 256060514304,
                "type": "disk",
                "tran": "nvme",
                "model": "SSD",
                "serial": "N1",
            },
        ]
    )
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    paths = {d.path for d in selectable_disks(result)}
    assert "/dev/sdb" not in paths
    assert "/dev/sda" not in paths
    assert "/dev/nvme0n1" in paths
    req = WipeRequest(
        device="/dev/nvme0n1",
        method=MethodId.EVERYDAY,
        boot_device=result.boot.path,
        logfile="/tmp/beamo-wipe/nwipe-nvme0n1.log",
    )
    argv = build_nwipe_argv(req)
    assert "--exclude=/dev/sdb" in argv
    assert "--exclude=/dev/sda" not in argv


def test_malformed_lsblk_json_fails_closed():
    for payload in (
        {"blockdevices": "nope"},
        {"blockdevices": [{"name": "sda", "type": "disk"}, "bad"]},
        {"blockdevices": {"name": "sda"}},
    ):
        result = discover(
            lsblk_payload=payload,
            boot_path="/dev/sda",
            mount_sources=[],
            cmdline="",
            env={"BEAMO_WIPE_DRY_RUN": "1"},
        )
        assert not result.boot_identified
        assert result.selectable == ()
        assert result.error


def test_efi_partition_is_not_the_display_name_when_a_volume_label_exists():
    from beamo_wipe.discover import parse_lsblk_json

    payload = _payload(
        [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
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
                        "label": "EFI",
                        "size": 100000000,
                    },
                    {
                        "name": "sda2",
                        "path": "/dev/sda2",
                        "type": "part",
                        "label": "WINDOWS",
                        "size": 499000000000,
                    },
                ],
            },
        ]
    )
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    windows = next(d for d in result.selectable if d.path == "/dev/sda")
    assert windows.display_name == "WINDOWS"


def test_serial_is_inherited_from_child_when_disk_serial_is_empty():
    from beamo_wipe.discover import parse_lsblk_json

    payload = _payload(
        [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "model": "Generic USB bridge",
                "serial": None,
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "serial": "REALSERIAL01",
                    }
                ],
            },
        ]
    )
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    disk = next(d for d in result.selectable if d.path == "/dev/sda")
    assert disk.serial == "REALSERIAL01"


def test_udev_by_label_path_identifies_usb():
    result = discover(
        lsblk_payload=_load("lsblk_same_size.json"),
        boot_path=None,
        mount_sources=[],
        cmdline="boot=live bootfrom=/dev/disk/by-label/BEAMO_WIPE",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot is not None
    assert result.boot.path == "/dev/sdb"
    assert "/dev/sdb" not in {d.path for d in result.selectable}


def test_unmatched_boot_path_does_not_fall_through_to_protected_mount():
    """A stale boot_path must fail closed, not pick the internal disk with /."""
    from beamo_wipe.discover import parse_lsblk_json

    payload = _payload(
        [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "model": "ST500",
                "serial": "Z9A",
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "mountpoint": "/",
                    }
                ],
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
            },
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "size": 256060514304,
                "type": "disk",
                "tran": "nvme",
                "model": "SSD",
                "serial": "N1",
            },
        ]
    )
    result = parse_lsblk_json(payload, boot_path="/dev/sdz")
    assert not result.boot_identified
    assert result.selectable == ()
    assert result.boot is None


def test_pick_list_omits_nodes_nwipe_would_reject():
    """type=disk nbd/zvol/pmem/controller nodes must not be wipe targets."""
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.safety import selectable_disks

    extras = [
        ("nbd0", "/dev/nbd0"),
        ("md1", "/dev/md1"),
        ("dm-1", "/dev/dm-1"),
        ("zd0", "/dev/zd0"),
        ("pmem0", "/dev/pmem0"),
        ("nvme0c0n1", "/dev/nvme0c0n1"),
    ]
    nodes = [
        {
            "name": "sdb",
            "path": "/dev/sdb",
            "size": 16000000000,
            "type": "disk",
            "tran": "usb",
            "model": "Beamo",
            "serial": "BOOT1",
        },
        {
            "name": "sda",
            "path": "/dev/sda",
            "size": 500107862016,
            "type": "disk",
            "tran": "sata",
            "model": "ST500",
            "serial": "Z9A",
        },
    ]
    for name, path in extras:
        nodes.append(
            {
                "name": name,
                "path": path,
                "size": 10000000000,
                "type": "disk",
                "model": name,
                "serial": "X",
            }
        )
    result = parse_lsblk_json(_payload(nodes), boot_path="/dev/sdb")
    paths = {d.path for d in result.selectable}
    assert paths == {"/dev/sda"}
    assert {d.path for d in selectable_disks(result)} == {"/dev/sda"}


def test_node_to_disk_rejects_empty_path():
    """Malformed lsblk nodes must never become Disk(path='/dev/')."""
    import pytest

    from beamo_wipe.discover import node_to_disk

    for node in (
        {"name": "", "path": ""},
        {"name": "   ", "path": "   "},
        {"name": "", "path": None},
        {"name": None, "path": ""},
        {"type": "disk"},
    ):
        with pytest.raises(ValueError, match="no usable device path"):
            node_to_disk(node, is_boot=False)


def test_parse_skips_pathless_node_keeps_sibling():
    """One malformed node is skipped per-node; the valid sibling still lists."""
    from beamo_wipe.discover import parse_lsblk_json

    payload = _payload(
        [
            {"name": "", "path": "", "size": 8000000000, "type": "disk"},
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "rota": True,
                "model": "ST500",
                "serial": "Z9A",
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "BootStick",
                "serial": "USB1",
            },
        ]
    )
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    assert result.boot_identified
    assert "/dev/" not in {d.path for d in result.disks}
    assert "/dev/sda" in {d.path for d in result.selectable}


def test_classify_bus_strips_padding():
    from beamo_wipe.discover import classify_bus

    assert classify_bus(" usb ") == "USB"
    assert classify_bus("SATA ") == "SATA"
    assert classify_bus("  Nvme\t") == "NVMe"
    assert classify_bus("   ") == "other"
    assert classify_bus(" mystery ") == "MYSTERY"
    assert classify_bus("usb") == "USB"
    assert classify_bus(None) == "other"
    assert classify_bus("") == "other"
