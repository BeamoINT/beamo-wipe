# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

import pytest

from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.models import MethodId
from beamo_wipe.safety import (
    SafetyError,
    assert_boot_excluded,
    assert_log_not_on_target,
    assert_not_boot,
    assert_ready_to_wipe,
    confirm_spec,
    is_live_environment,
    require_live_or_dry_run,
    selectable_disks,
    token_matches,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _disc(name: str, boot: str | None):
    payload = load_lsblk_json_text((FIXTURES / name).read_text(encoding="utf-8"))
    return discover(
        lsblk_payload=payload,
        boot_path=boot,
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )


def test_boot_never_selectable():
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    assert_boot_excluded(d)
    assert all(not x.is_boot for x in selectable_disks(d))
    assert "/dev/sdb" not in {x.path for x in selectable_disks(d)}


def test_unidentified_boot_raises():
    d = _disc("lsblk_no_boot.json", None)
    with pytest.raises(SafetyError, match="cannot tell which disk"):
        assert_boot_excluded(d)


def test_refuse_wipe_boot_path():
    with pytest.raises(SafetyError):
        assert_not_boot("/dev/sdb", "/dev/sdb")
    with pytest.raises(SafetyError):
        assert_not_boot("/dev/sdb1", "/dev/sdb")
    assert_not_boot("/dev/nvme0n1", "/dev/sdb")


def test_nvme_sibling_namespaces_are_not_treated_as_boot():
    assert_not_boot("/dev/nvme0n11", "/dev/nvme0n1")
    assert_not_boot("/dev/nvme0n1", "/dev/nvme0n11")
    with pytest.raises(SafetyError):
        assert_not_boot("/dev/nvme0n1p1", "/dev/nvme0n1")
    with pytest.raises(SafetyError):
        assert_not_boot("/dev/nvme0n1", "/dev/nvme0n1p1")


def test_logfile_for_is_unique_per_call(tmp_path, monkeypatch):
    from beamo_wipe.safety import logfile_for

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    first = logfile_for("/dev/sda")
    second = logfile_for("/dev/sda")
    assert first != second
    assert str(tmp_path) in first
    assert str(tmp_path) in second


def test_logs_not_on_target_name():
    with pytest.raises(SafetyError):
        assert_log_not_on_target("/mnt/target/log.txt", "/dev/nvme0n1")
    with pytest.raises(SafetyError):
        assert_log_not_on_target("/dev/sda", "/dev/nvme0n1")
    assert_log_not_on_target("/tmp/beamo-wipe/nwipe-nvme0n1.log", "/dev/nvme0n1")


def test_live_markers():
    assert not is_live_environment(env={"BEAMO_WIPE_DRY_RUN": "1"}, paths_exist=[])
    assert not is_live_environment(
        env={"BEAMO_WIPE_LIVE": "1"}, cmdline="", paths_exist=[]
    )
    assert is_live_environment(
        env={}, cmdline="boot=live quiet", live_medium_mounted=True
    )
    assert is_live_environment(
        env={}, cmdline="quiet boot=live components", live_medium_mounted=True
    )
    assert is_live_environment(env={}, cmdline="boot=casper", live_medium_mounted=True)
    assert not is_live_environment(
        env={}, cmdline="boot=live quiet", live_medium_mounted=False
    )
    assert not is_live_environment(env={}, cmdline="boot=live quiet", paths_exist=[])
    assert not is_live_environment(env={}, cmdline="", paths_exist=[])
    assert not is_live_environment(
        env={}, cmdline="", paths_exist=["/run/live", "/lib/live/mount"]
    )
    assert not is_live_environment(env={}, cmdline="debug=boot=live")
    assert not is_live_environment(env={}, cmdline="boot=live-extra")
    require_live_or_dry_run(env={"BEAMO_WIPE_DRY_RUN": "1"}, cmdline="")
    with pytest.raises(SafetyError):
        require_live_or_dry_run(env={}, cmdline="")
    with pytest.raises(SafetyError):
        require_live_or_dry_run(env={"BEAMO_WIPE_LIVE": "1"}, cmdline="")
    require_live_or_dry_run(
        env={}, cmdline="boot=live", live_medium_mounted=True
    )
    with pytest.raises(SafetyError):
        require_live_or_dry_run(
            env={}, cmdline="boot=live", live_medium_mounted=False
        )


def test_owner_and_token_required_before_wipe(monkeypatch, tmp_path):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disk = selectable_disks(d)[0]
    spec = confirm_spec(disk, selectable_disks(d))
    with pytest.raises(SafetyError, match="Owner"):
        assert_ready_to_wipe(
            owner_ok=False,
            disk=disk,
            discovery=d,
            typed_token=spec.token,
            countdown_complete=True,
            method=MethodId.EVERYDAY,
        )
    with pytest.raises(SafetyError, match="token"):
        assert_ready_to_wipe(
            owner_ok=True,
            disk=disk,
            discovery=d,
            typed_token="nope",
            countdown_complete=True,
            method=MethodId.EVERYDAY,
        )
    with pytest.raises(SafetyError, match="delay"):
        assert_ready_to_wipe(
            owner_ok=True,
            disk=disk,
            discovery=d,
            typed_token=spec.token,
            countdown_complete=False,
            method=MethodId.EVERYDAY,
        )
    req = assert_ready_to_wipe(
        owner_ok=True,
        disk=disk,
        discovery=d,
        typed_token=spec.token,
        countdown_complete=True,
        method=MethodId.EVERYDAY,
    )
    assert req.device == disk.path
    assert req.boot_device == "/dev/sdb"
    assert str(tmp_path) in req.logfile


def test_preview_size_check_ignores_host_sysfs(monkeypatch, tmp_path):
    """Fake lsblk JSON reuses /dev names. Host sysfs for that name is another disk."""
    from beamo_wipe.safety import assert_size_unchanged

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr("beamo_wipe.safety.block_size_bytes", lambda _path: 99)
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disk = selectable_disks(d)[0]
    spec = confirm_spec(disk, selectable_disks(d))
    assert_size_unchanged(disk.path, disk.size_bytes)
    req = assert_ready_to_wipe(
        owner_ok=True,
        disk=disk,
        discovery=d,
        typed_token=spec.token,
        countdown_complete=True,
        method=MethodId.EVERYDAY,
    )
    assert req.device == disk.path


def test_live_size_check_still_refuses_sysfs_mismatch(monkeypatch):
    from beamo_wipe.safety import assert_size_unchanged

    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda env=None: False)
    monkeypatch.setattr("beamo_wipe.safety.block_size_bytes", lambda _path: 99)
    with pytest.raises(SafetyError, match="size changed"):
        assert_size_unchanged("/dev/vda", 10_000_000_000)


def test_size_token_cannot_equal_another_disks_serial_suffix():
    """A 1 TB size token must not also confirm a different disk's serial."""
    from beamo_wipe.discover import size_gb_label
    from beamo_wipe.models import Disk, DiskKind

    def make(path, size, serial):
        return Disk(
            path=path,
            name=path.rsplit("/", 1)[-1],
            model="Fake",
            serial=serial,
            size_bytes=size,
            size_gb_label=size_gb_label(size),
            kind=DiskKind.SSD,
            bus="SATA",
            label="",
        )

    one_tb = make("/dev/sda", 1_000_000_000_000, "AAAA1111")
    two_a = make("/dev/sdb", 2_000_000_000_000, "WXYZ1000")
    two_b = make("/dev/sdc", 2_000_000_000_000, "OTHER9999")
    listed = [one_tb, two_a, two_b]
    specs = {disk.path: confirm_spec(disk, listed) for disk in listed}
    assert specs["/dev/sda"].token != specs["/dev/sdb"].token
    assert not (
        token_matches("1000", specs["/dev/sda"])
        and token_matches("1000", specs["/dev/sdb"])
    )


def test_empty_confirm_token_never_matches():
    from beamo_wipe.models import ConfirmSpec

    spec = ConfirmSpec(token="", prompt="x")
    assert not token_matches("", spec)
    assert not token_matches("   ", spec)
    spec_ws = ConfirmSpec(token="  ", prompt="x")
    assert not token_matches("  ", spec_ws)
    assert not token_matches("256", spec_ws)


def test_nbd_is_not_a_wipe_target():
    from beamo_wipe.safety import normalize_whole_disk

    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/nbd0")
    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/nbd1")


def test_wwn_change_is_identity_change(monkeypatch, tmp_path):
    from dataclasses import replace

    from beamo_wipe.safety import assert_disk_identity

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disk = selectable_disks(d)[0]
    swapped = replace(disk, wwn="WWN-CHANGED")
    with pytest.raises(SafetyError, match="identity"):
        assert_disk_identity(swapped, d)


def test_char_device_is_not_a_wipe_target():
    from beamo_wipe.safety import assert_existing_is_block_device

    if not Path("/dev/null").exists():
        pytest.skip("no /dev/null")
    with pytest.raises(SafetyError, match="block device"):
        assert_existing_is_block_device("/dev/null")


def test_blank_disk_partition_change_is_a_different_disk(monkeypatch, tmp_path):
    """Same path, model, and empty serial can still be another physical disk."""
    from beamo_wipe.safety import assert_disk_identity

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)

    def payload(part_uuid: str):
        return {
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 8_000_000_000,
                    "tran": "usb",
                    "model": "USB DISK",
                    "serial": "",
                    "wwn": "",
                    "children": [
                        {
                            "name": "sda1",
                            "path": "/dev/sda1",
                            "type": "part",
                            "fstype": "ntfs",
                            "uuid": part_uuid,
                            "label": "DATA",
                            "size": 7_000_000_000,
                        }
                    ],
                },
                {
                    "name": "sdb",
                    "path": "/dev/sdb",
                    "type": "disk",
                    "size": 16_000_000_000,
                    "tran": "usb",
                    "model": "Beamo",
                    "serial": "BOOT",
                    "wwn": "boot-wwn",
                },
            ]
        }

    def scan(part_uuid: str):
        return discover(
            lsblk_payload=payload(part_uuid),
            boot_path="/dev/sdb",
            mount_sources=[],
            cmdline="",
            env={"BEAMO_WIPE_DRY_RUN": "1"},
        )

    original = scan("AAAA-AAAA")
    disk = next(item for item in original.selectable if item.path == "/dev/sda")
    assert disk.serial == ""
    assert disk.wwn == ""
    assert_disk_identity(disk, scan("AAAA-AAAA"))
    with pytest.raises(SafetyError, match="identity"):
        assert_disk_identity(disk, scan("BBBB-BBBB"))


def test_flat_blank_disk_partition_change_is_a_different_disk(monkeypatch, tmp_path):
    """A partition emitted as its own row still belongs to the disk."""
    from beamo_wipe.safety import assert_disk_identity

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)

    def payload(part_uuid: str):
        return {
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 8_000_000_000,
                    "tran": "usb",
                    "model": "USB DISK",
                    "serial": "",
                    "wwn": "",
                },
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "pkname": "sda",
                    "fstype": "ntfs",
                    "uuid": part_uuid,
                    "label": "DATA",
                    "size": 7_000_000_000,
                },
                {
                    "name": "sdb",
                    "path": "/dev/sdb",
                    "type": "disk",
                    "size": 16_000_000_000,
                    "tran": "usb",
                    "model": "Beamo",
                    "serial": "BOOT",
                    "wwn": "boot-wwn",
                },
            ]
        }

    def scan(part_uuid: str):
        return discover(
            lsblk_payload=payload(part_uuid),
            boot_path="/dev/sdb",
            mount_sources=[],
            cmdline="",
            env={"BEAMO_WIPE_DRY_RUN": "1"},
        )

    original = scan("AAAA-AAAA")
    disk = next(item for item in original.selectable if item.path == "/dev/sda")
    assert_disk_identity(disk, scan("AAAA-AAAA"))
    with pytest.raises(SafetyError, match="identity"):
        assert_disk_identity(disk, scan("BBBB-BBBB"))


def _open_volume_payload(shape: str, inner_uuid: str, *, mapper_name: str = "dm-0"):
    """Blank disk whose real filesystem UUID sits on an open mapper."""
    boot = {
        "name": "sdb",
        "path": "/dev/sdb",
        "type": "disk",
        "size": 16_000_000_000,
        "tran": "usb",
        "model": "Beamo",
        "serial": "BOOT",
        "wwn": "boot-wwn",
    }
    disk = {
        "name": "sda",
        "path": "/dev/sda",
        "type": "disk",
        "size": 8_000_000_000,
        "tran": "usb",
        "model": "USB DISK",
        "serial": "",
        "wwn": "",
    }
    if shape == "nested-luks":
        disk["children"] = [
            {
                "name": "sda1",
                "path": "/dev/sda1",
                "type": "part",
                "fstype": "crypto_LUKS",
                "uuid": "LUKS-SAME",
                "size": 7_000_000_000,
                "children": [
                    {
                        "name": mapper_name,
                        "path": f"/dev/{mapper_name}",
                        "type": "crypt",
                        "fstype": "ext4",
                        "uuid": inner_uuid,
                        "label": "HOME",
                    }
                ],
            }
        ]
        return {"blockdevices": [disk, boot]}
    if shape == "flat-luks":
        return {
            "blockdevices": [
                disk,
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "pkname": "sda",
                    "fstype": "crypto_LUKS",
                    "uuid": "LUKS-SAME",
                    "size": 7_000_000_000,
                },
                {
                    "name": mapper_name,
                    "path": f"/dev/{mapper_name}",
                    "type": "crypt",
                    "pkname": "sda1",
                    "fstype": "ext4",
                    "uuid": inner_uuid,
                    "label": "HOME",
                },
                boot,
            ]
        }
    if shape == "nested-lvm":
        disk["children"] = [
            {
                "name": "sda1",
                "path": "/dev/sda1",
                "type": "part",
                "fstype": "LVM2_member",
                "uuid": "PV-SAME",
                "size": 7_000_000_000,
                "children": [
                    {
                        "name": "dm-1",
                        "path": "/dev/dm-1",
                        "type": "lvm",
                        "fstype": "ext4",
                        "uuid": "STABLE-LV",
                        "label": "ROOT",
                    },
                    {
                        "name": mapper_name,
                        "path": f"/dev/{mapper_name}",
                        "type": "lvm",
                        "fstype": "ext4",
                        "uuid": inner_uuid,
                        "label": "HOME",
                    },
                ],
            }
        ]
        return {"blockdevices": [disk, boot]}
    if shape == "flat-lvm":
        return {
            "blockdevices": [
                disk,
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "pkname": "sda",
                    "fstype": "LVM2_member",
                    "uuid": "PV-SAME",
                    "size": 7_000_000_000,
                },
                {
                    "name": mapper_name,
                    "path": f"/dev/{mapper_name}",
                    "type": "lvm",
                    "pkname": "sda1",
                    "fstype": "ext4",
                    "uuid": inner_uuid,
                    "label": "HOME",
                },
                boot,
            ]
        }
    if shape == "held-luks":
        # bcache is its own type=disk row. The open volume is not a child of sda.
        disk["children"] = [
            {
                "name": "sda1",
                "path": "/dev/sda1",
                "type": "part",
                "pkname": "sda",
                "fstype": "bcache",
                "uuid": "BCACHE-SAME",
                "size": 7_000_000_000,
            }
        ]
        return {
            "blockdevices": [
                disk,
                {
                    "name": "bcache0",
                    "path": "/dev/bcache0",
                    "type": "disk",
                    "pkname": "sda",
                    "size": 7_000_000_000,
                    "children": [
                        {
                            "name": "bcache0p1",
                            "path": "/dev/bcache0p1",
                            "type": "part",
                            "pkname": "bcache0",
                            "fstype": "crypto_LUKS",
                            "uuid": "LUKS-SAME",
                            "size": 6_000_000_000,
                            "children": [
                                {
                                    "name": mapper_name,
                                    "path": f"/dev/{mapper_name}",
                                    "type": "crypt",
                                    "pkname": "bcache0p1",
                                    "fstype": "ext4",
                                    "uuid": inner_uuid,
                                    "label": "HOME",
                                }
                            ],
                        }
                    ],
                },
                boot,
            ]
        }
    raise AssertionError(shape)


@pytest.mark.parametrize(
    "shape",
    ["nested-luks", "flat-luks", "nested-lvm", "flat-lvm", "held-luks"],
)
def test_open_volume_filesystem_change_is_a_different_disk(
    monkeypatch, tmp_path, shape
):
    """A LUKS or LVM filesystem UUID is the disk, even when the header UUID is not."""
    from beamo_wipe.safety import assert_disk_identity

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)

    def scan(inner_uuid: str, mapper_name: str = "dm-0"):
        return discover(
            lsblk_payload=_open_volume_payload(
                shape, inner_uuid, mapper_name=mapper_name
            ),
            boot_path="/dev/sdb",
            mount_sources=[],
            cmdline="",
            env={"BEAMO_WIPE_DRY_RUN": "1"},
        )

    original = scan("AAAA-AAAA")
    disk = next(item for item in original.selectable if item.path == "/dev/sda")
    assert disk.serial == ""
    assert disk.wwn == ""
    assert_disk_identity(disk, scan("aaaa-aaaa"))
    assert_disk_identity(disk, scan("AAAA-AAAA", mapper_name="dm-9"))
    with pytest.raises(SafetyError, match="identity"):
        assert_disk_identity(disk, scan("BBBB-BBBB"))


def test_ambiguous_mapper_parent_lists_no_targets(monkeypatch, tmp_path):
    """A mapper whose parent name is listed twice is not a known disk."""
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    payload = {
        "blockdevices": [
            {
                "name": "sda",
                "path": "/dev/sda",
                "type": "disk",
                "size": 8_000_000_000,
                "tran": "usb",
                "model": "USB DISK",
                "serial": "",
                "wwn": "",
            },
            {
                "name": "sda1",
                "path": "/dev/sda1",
                "type": "part",
                "pkname": "sda",
                "fstype": "crypto_LUKS",
                "uuid": "LUKS-SAME",
                "size": 7_000_000_000,
            },
            {
                "name": "sda1",
                "path": "/dev/sda1",
                "type": "part",
                "pkname": "sda",
                "fstype": "crypto_LUKS",
                "uuid": "LUKS-SAME",
                "size": 7_000_000_000,
            },
            {
                "name": "dm-0",
                "path": "/dev/dm-0",
                "type": "crypt",
                "pkname": "sda1",
                "fstype": "ext4",
                "uuid": "AAAA-AAAA",
                "label": "HOME",
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "type": "disk",
                "size": 16_000_000_000,
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT",
                "wwn": "boot-wwn",
            },
        ]
    }
    found = discover(
        lsblk_payload=payload,
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert found.selectable == ()
    assert not found.boot_identified


def test_identity_change_refuses_wipe(monkeypatch, tmp_path):
    from dataclasses import replace

    from beamo_wipe.safety import assert_disk_identity

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disk = selectable_disks(d)[0]
    swapped = replace(disk, serial="DIFFERENT-SERIAL")
    with pytest.raises(SafetyError, match="identity"):
        assert_disk_identity(swapped, d)
