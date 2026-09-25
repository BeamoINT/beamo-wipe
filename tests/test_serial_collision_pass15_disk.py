"""A cloned serial cannot make a second new USB disappear from export selection."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import baseline_fingerprints, select_export_volume
from test_usb_report_workflow import _partition, _payload, _root


def test_second_new_usb_matching_optional_baseline_serial_is_ambiguous():
    payload, disks = _payload()
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Twin USB",
        serial="DUP", wwn="",
    )
    payload["blockdevices"].append(
        _root(
            "/dev/sda", size=32_000_000, tran="usb", model="Twin USB",
            serial="DUP", rm=1, hotplug=1,
        )
    )
    payload["blockdevices"].append(
        _root(
            "/dev/sdd", size=32_000_000, tran="usb", model="Twin USB",
            serial="DUP", rm=1, hotplug=1,
            children=[_partition("/dev/sdd1", pkname="sdd", uuid="DDDD-2222")],
        )
    )
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    with pytest.raises(SafetyError, match="could not be verified"):
        select_export_volume(payload, baseline)


def test_distinct_wwns_keep_reused_serials_separable():
    payload, disks = _payload()
    payload["blockdevices"][0]["serial"] = "DUP"
    payload["blockdevices"][2]["serial"] = "DUP"
    baseline = baseline_fingerprints(disks)
    baseline = (replace(baseline[0], serial="DUP"), baseline[1])

    assert select_export_volume(payload, baseline).path == "/dev/sdc1"


def test_report_partition_cannot_exceed_parent_capacity():
    payload, disks = _payload()
    payload["blockdevices"][2]["children"][0]["size"] = 40_000_000

    with pytest.raises(SafetyError, match="layout"):
        select_export_volume(payload, baseline_fingerprints(disks))


def test_relocated_serial_only_baseline_cannot_hide_second_new_usb():
    payload, disks = _payload()
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Twin USB",
        serial="DUP", wwn="",
    )
    payload["blockdevices"].append(
        _root(
            "/dev/sdd", size=32_000_000, tran="usb", model="Twin USB",
            serial="DUP", rm=1, hotplug=1,
            children=[_partition("/dev/sdd1", pkname="sdd", uuid="DDDD-2222")],
        )
    )
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    with pytest.raises(SafetyError, match="could not be verified"):
        select_export_volume(payload, baseline)


def test_relocated_optional_baseline_with_same_wwn_remains_identified():
    payload, disks = _payload()
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Twin USB",
        serial="DUP", wwn="0x5000c500aabbccdd",
    )
    payload["blockdevices"].append(
        _root(
            "/dev/sdd", size=32_000_000, tran="usb", model="Twin USB",
            serial="DUP", wwn="5000c500aabbccdd", rm=1, hotplug=1,
        )
    )
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    assert select_export_volume(payload, baseline).path == "/dev/sdc1"


def test_changed_optional_baseline_capacity_cannot_hide_new_usb_at_same_path():
    payload, disks = _payload()
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Twin USB",
        serial="DUP", wwn="",
    )
    payload["blockdevices"].append(
        _root(
            "/dev/sda", size=64_000_000, tran="usb", model="Twin USB",
            serial="DUP", rm=1, hotplug=1,
            children=[_partition("/dev/sda1", pkname="sda", uuid="AAAA-2222")],
        )
    )
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    with pytest.raises(SafetyError, match="could not be verified"):
        select_export_volume(payload, baseline)


def test_gained_optional_baseline_wwn_cannot_hide_replacement_usb():
    payload, disks = _payload()
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Twin USB",
        serial="DUP", wwn="",
    )
    payload["blockdevices"].append(
        _root(
            "/dev/sda", size=32_000_000, tran="usb", model="Twin USB",
            serial="DUP", wwn="5000c500aabbccdd", rm=1, hotplug=1,
        )
    )
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    with pytest.raises(SafetyError, match="could not be verified"):
        select_export_volume(payload, baseline)
