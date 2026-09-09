# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared disk identity. Fake lsblk only; kernel names are not stable IDs."""

from pathlib import Path

import pytest

from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.identity import (
    AMBIGUOUS_IDENTITY,
    SERIAL_NOT_REPORTED,
    UNKNOWN_MODEL,
    display_title,
    present_disk,
)
from beamo_wipe.models import Disk, DiskKind, Screen
from beamo_wipe.safety import SafetyError, confirm_spec, listed_disks, selectable_disks
from beamo_wipe.wizard import Wizard
from beamo_wipe.nwipe_runner import DryRunRunner

FIXTURES = Path(__file__).parent / "fixtures"


def _disc(name: str, boot: str = "/dev/sdb"):
    payload = load_lsblk_json_text((FIXTURES / name).read_text(encoding="utf-8"))
    return discover(
        lsblk_payload=payload,
        boot_path=boot,
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )


def test_identity_never_uses_kernel_name():
    disk = Disk(
        path="/dev/sda",
        name="sda",
        model="",
        serial="",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    view = present_disk(disk)
    assert view.title == UNKNOWN_MODEL
    assert display_title(disk) != "sda"
    assert "sda" not in view.announcement
    assert "/dev/" not in view.announcement
    assert view.id_value == SERIAL_NOT_REPORTED
    assert "did not report a serial" in view.missing_note
    assert view.connection == "SATA"


def test_serial_is_stronger_than_wwn_and_path():
    disk = Disk(
        path="/dev/nvme0n1",
        name="nvme0n1",
        model="Samsung SSD 970 EVO",
        serial="S4EVNX0N123456",
        size_bytes=256_000_000_000,
        size_gb_label="256",
        kind=DiskKind.NVME,
        bus="NVMe",
        label="",
        wwn="0x5002538e00000001",
    )
    view = present_disk(disk)
    assert view.id_label == "Serial"
    assert view.id_value == "S4EVNX0N123456"
    assert view.connection == "NVMe"
    assert "/dev/" not in view.compact_line


def test_missing_serial_uses_unique_wwn_not_kernel_name():
    result = _disc("lsblk_missing_serial_unique_wwn.json")
    disks = selectable_disks(result)
    listed = listed_disks(result)
    assert len(disks) == 2
    spec_a = confirm_spec(disks[0], listed)
    spec_b = confirm_spec(disks[1], listed)
    assert spec_a.token != spec_b.token
    assert spec_a.token not in {"sda", "sdc"}
    views = [present_disk(disk, listed) for disk in disks]
    assert all(view.id_label == "Hardware ID" for view in views)
    assert all(view.confirmable for view in views)


def test_identical_missing_serials_fail_closed():
    result = _disc("lsblk_identical_missing_serial.json")
    disks = selectable_disks(result)
    listed = listed_disks(result)
    assert len(disks) == 2
    with pytest.raises(SafetyError, match="too similar"):
        confirm_spec(disks[0], listed)
    view = present_disk(disks[0], listed)
    assert not view.confirmable
    assert view.ambiguous_note == AMBIGUOUS_IDENTITY
    assert "/dev/" not in view.announcement


def test_duplicate_serials_are_highlighted():
    result = _disc("lsblk_duplicate_serial.json")
    disks = selectable_disks(result)
    listed = listed_disks(result)
    views = [present_disk(disk, listed) for disk in disks]
    assert all(view.duplicate_note for view in views)
    # Different sizes still confirm by size.
    assert all(view.confirmable for view in views)
    assert confirm_spec(disks[0], listed).token == disks[0].size_gb_label


def test_long_unicode_identity_is_preserved():
    result = _disc("lsblk_long_unicode.json")
    disk = selectable_disks(result)[0]
    view = present_disk(disk, listed_disks(result))
    assert "삼성" in view.title
    assert view.id_value
    assert "/dev/" not in view.announcement
    assert confirm_spec(disk, listed_disks(result)).token == disk.size_gb_label


def test_usb_bridge_and_nvme_keep_connection_labels():
    result = _disc("lsblk_sata_bridge.json")
    listed = listed_disks(result)
    by_path = {disk.path: present_disk(disk, listed) for disk in selectable_disks(result)}
    if "/dev/nvme0n1" in by_path:
        assert by_path["/dev/nvme0n1"].connection == "NVMe"
    for view in by_path.values():
        assert "/dev/" not in view.announcement


def test_hotplug_rename_does_not_change_human_identity():
    first = Disk(
        path="/dev/sda",
        name="sda",
        model="ST500DM002",
        serial="WD-WCC6Y1234567",
        size_bytes=500_107_862_016,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    renamed = Disk(
        path="/dev/sdb",
        name="sdb",
        model="ST500DM002",
        serial="WD-WCC6Y1234567",
        size_bytes=500_107_862_016,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    a, b = present_disk(first), present_disk(renamed)
    assert a.title == b.title
    assert a.id_value == b.id_value
    assert a.capacity == b.capacity
    assert a.announcement == b.announcement


def test_malformed_control_serial_is_stripped_not_used_as_name():
    result = _disc("lsblk_adversarial_udev_encoded.json") if (
        FIXTURES / "lsblk_adversarial_udev_encoded.json"
    ).exists() else _disc("lsblk_missing_metadata.json")
    for disk in selectable_disks(result):
        view = present_disk(disk, listed_disks(result))
        assert view.title != disk.name
        assert "/dev/" not in view.announcement


def test_wizard_blocks_confirm_when_identity_is_ambiguous():
    result = _disc("lsblk_identical_missing_serial.json")
    wiz = Wizard(result, DryRunRunner(duration_s=0.5), dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    target = wiz.selectable[0]
    wiz.select_disk(target.path)
    wiz.continue_pick()
    assert wiz.screen == Screen.PICK
    assert wiz.error == AMBIGUOUS_IDENTITY
    assert wiz.confirm is None


def test_evidence_carries_the_same_presentation():
    from beamo_wipe.evidence import build_evidence
    from beamo_wipe.models import MethodId, WipeResult

    result = _disc("lsblk_vm_iso.json", "/dev/sr0")
    disk = selectable_disks(result)[0]
    view = present_disk(disk, listed_disks(result))
    ev = build_evidence(
        disk=disk,
        discovery=result,
        method=MethodId.EVERYDAY,
        request=None,
        result=WipeResult(False, 1, "nwipe exited 1", "fake-log"),
        started_at_wall="",
        ended_at_wall="",
        started_mono=0,
        ended_mono=1,
        argv=[],
        log_text="",
    )
    shown = ev["device_presentation"]
    assert shown["announcement"] == view.announcement
    assert "/dev/" not in shown["announcement"]
    assert ev["device"]["path"] == disk.path
