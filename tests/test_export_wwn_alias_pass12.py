"""Report USB selection must recognize lsblk's optional WWN prefix."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import (
    DeviceFingerprint,
    ExportVolume,
    _same_device,
    _same_volume,
    baseline_fingerprints,
    select_export_volume,
)
from test_usb_report_workflow import _partition, _payload, _root


def test_report_selection_rejects_duplicate_wwn_with_optional_prefix():
    payload, disks = _payload()
    payload["blockdevices"][0]["wwn"] = "0x5000c500aabbccdd"
    payload["blockdevices"][2]["wwn"] = "5000c500aabbccdd"
    baseline = baseline_fingerprints(disks)
    baseline = (replace(baseline[0], wwn="0x5000c500aabbccdd"), *baseline[1:])

    with pytest.raises(SafetyError, match="could not be verified"):
        select_export_volume(payload, baseline)


def test_report_identity_matches_renamed_device_with_optional_wwn_prefix():
    old = DeviceFingerprint("/dev/sdc", 32_000_000, "Other USB", "", "0x5000c500aabbccdd")
    renamed = DeviceFingerprint("/dev/sdd", 32_000_000, "Other USB", "", "5000c500aabbccdd")

    assert _same_device(old, renamed)


def test_required_boot_identity_accepts_only_wwn_prefix_format_change():
    payload, disks = _payload()
    payload["blockdevices"][0]["wwn"] = "5000c500aabbccdd"
    baseline = baseline_fingerprints(disks)
    baseline = (replace(baseline[0], wwn="0x5000c500aabbccdd"), *baseline[1:])

    assert select_export_volume(payload, baseline).path == "/dev/sdc1"


def test_two_report_scans_accept_only_wwn_prefix_format_change():
    old = DeviceFingerprint("/dev/sdc", 32_000_000, "Report USB", "SERIAL", "0x5000c500aabbccdd")
    first = ExportVolume(old, "/dev/sdc1", 32_000_000, "vfat", "FAT32", "ABCD-1234")
    second = replace(first, parent=replace(old, wwn="5000c500aabbccdd"))

    assert _same_volume(first, second, include_rdev=False)
    assert _same_volume(first, second, include_rdev=True)
    assert not _same_volume(first, replace(second, rdev=42), include_rdev=True)


def test_distinct_wwns_disambiguate_reused_serials():
    old = DeviceFingerprint("/dev/sda", 32_000_000, "Twin USB", "DUP", "5000c500aabbcc01")
    inserted = DeviceFingerprint("/dev/sdd", 32_000_000, "Twin USB", "DUP", "5000c500aabbcc02")

    assert not _same_device(old, inserted)


def test_same_kernel_path_does_not_hide_changed_hardware_wwn():
    old = DeviceFingerprint("/dev/sda", 32_000_000, "Twin USB", "DUP", "5000c500aabbcc01")
    replacement = replace(old, wwn="5000c500aabbcc02")

    assert not _same_device(old, replacement)


def test_same_kernel_path_does_not_hide_changed_serial_without_wwn():
    old = DeviceFingerprint("/dev/sda", 32_000_000, "Twin USB", "OLD", "")
    replacement = replace(old, serial="NEW")

    assert not _same_device(old, replacement)


def test_two_new_report_sticks_with_reused_serials_are_rejected():
    payload, disks = _payload()
    old = _root(
        "/dev/sda", size=32_000_000, tran="usb", model="Twin USB",
        serial="DUP", wwn="5000c500aabbcc01", rm=1, hotplug=1,
    )
    inserted = _root(
        "/dev/sdd", size=32_000_000, tran="usb", model="Twin USB",
        serial="DUP", wwn="5000c500aabbcc02", rm=1, hotplug=1,
        children=[_partition("/dev/sdd1", pkname="sdd", uuid="DDDD-2222")],
    )
    payload["blockdevices"].extend((old, inserted))
    baseline = baseline_fingerprints(
        (*disks, SimpleNamespace(path="/dev/sda", size_bytes=32_000_000,
                                 model="Twin USB", serial="DUP", wwn="5000c500aabbcc01"))
    )

    with pytest.raises(SafetyError, match="exactly one"):
        select_export_volume(payload, baseline)


def test_reused_kernel_path_cannot_hide_second_new_report_stick():
    payload, disks = _payload()
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Twin USB",
        serial="DUP", wwn="5000c500aabbcc01",
    )
    replacement = _root(
        "/dev/sda", size=32_000_000, tran="usb", model="Twin USB",
        serial="DUP", wwn="5000c500aabbcc02", rm=1, hotplug=1,
        children=[_partition("/dev/sda1", pkname="sda", uuid="DDDD-2222")],
    )
    payload["blockdevices"].append(replacement)
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    with pytest.raises(SafetyError, match="identity could not be verified"):
        select_export_volume(payload, baseline)


def test_reused_kernel_path_with_changed_serial_cannot_hide_new_stick():
    payload, disks = _payload()
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Twin USB",
        serial="OLD", wwn="",
    )
    replacement = _root(
        "/dev/sda", size=32_000_000, tran="usb", model="Twin USB",
        serial="NEW", rm=1, hotplug=1,
        children=[_partition("/dev/sda1", pkname="sda", uuid="DDDD-2222")],
    )
    payload["blockdevices"].append(replacement)
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    with pytest.raises(SafetyError, match="identity could not be verified"):
        select_export_volume(payload, baseline)
