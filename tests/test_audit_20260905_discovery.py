"""Synthetic discovery regressions; no device nodes or subprocesses are opened."""

import importlib

import pytest

from beamo_wipe.discover import discover


def _disk(name, **changes):
    value = {
        "name": name, "path": "/dev/" + name, "type": "disk",
        "size": 32_000_000_000, "model": "Fake disk", "serial": name,
        "tran": "usb", "rota": False, "ro": False,
        "mountpoints": [None], "mountpoint": None,
    }
    value.update(changes)
    return value


def _discover(payload, sources):
    return discover(lsblk_payload=payload, mount_sources=sources, cmdline="", env={})


def test_unresolved_live_source_alongside_resolved_source_fails_closed():
    # Separate mounted live-medium sources can occur in fromiso boot flows;
    # resolving one does not establish the other source's physical owner.
    payload = {"blockdevices": [_disk("sda"), _disk("sdb")]}
    result = _discover(payload, ["/dev/sdb", "UUID=missing-live-medium"])
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_stacked_mounted_volume_excludes_physical_parent():
    # Existing discovery supports flat PKNAME rows. Follow the full chain,
    # including a mounted mapper whose parent is a partition of the disk.
    payload = {"blockdevices": [
        _disk("sda"), _disk("sdb"),
        _disk("sda1", type="part", pkname="sda"),
        _disk("dm-0", type="crypt", pkname="sda1", mountpoints=["/media/data"]),
    ]}
    result = _discover(payload, ["/dev/sdb"])
    assert result.boot_identified
    assert result.selectable == ()


@pytest.mark.parametrize("bad_mounts", [[False], [0]])
def test_production_malformed_mount_entries_fail_closed(monkeypatch, bad_mounts):
    discovery_module = importlib.import_module("beamo_wipe.discover")
    payload = {"blockdevices": [
        _disk("sda", mountpoints=bad_mounts), _disk("sdb"),
    ]}
    monkeypatch.setattr(discovery_module, "run_lsblk", lambda: payload)
    result = discovery_module.discover(
        mount_sources=["/dev/sdb"], cmdline="", env={}
    )
    assert not result.boot_identified
    assert result.selectable == ()


@pytest.mark.parametrize("transport", ["tcp", "rdma"])
def test_fabrics_nvme_not_offered_as_local_wipe_target(transport):
    # The final kernel-backed gate already refuses NVMe fabrics transports.
    # Known fabrics TRAN values should also keep these disks out of the picker.
    payload = {"blockdevices": [_disk("nvme0n1", tran=transport), _disk("sdb")]}
    result = _discover(payload, ["/dev/sdb"])
    assert result.boot_identified
    assert result.selectable == ()


@pytest.mark.parametrize("mounts,selectable", [
    (None, True), ([], True), ([None], True), ([""], True),
    ("", True), ("/media/data", False), (["/media/data", None], False),
])
def test_production_accepted_mount_shapes(monkeypatch, mounts, selectable):
    discovery_module = importlib.import_module("beamo_wipe.discover")
    payload = {"blockdevices": [_disk("sda", mountpoints=mounts), _disk("sdb")]}
    monkeypatch.setattr(discovery_module, "run_lsblk", lambda: payload)
    result = discovery_module.discover(mount_sources=["/dev/sdb"], cmdline="", env={})
    assert result.boot_identified
    assert bool(result.selectable) is selectable


def test_flat_deep_mounted_ancestry_preserves_unrelated_disk():
    payload = {"blockdevices": [
        _disk("sda"), _disk("sdb"), _disk("sdc"),
        _disk("sda1", type="part", pkname="sda"),
        _disk("dm-0", type="crypt", pkname="sda1"),
        _disk("dm-1", type="lvm", pkname="dm-0"),
        _disk("dm-2", type="lvm", pkname="dm-1", mountpoints=["/media/data"]),
    ]}
    result = _discover(payload, ["/dev/sdb"])
    assert [disk.path for disk in result.selectable] == ["/dev/sdc"]


@pytest.mark.parametrize("parent", ["dm-1", "missing"])
def test_flat_mounted_cycle_or_unknown_ancestor_fails_closed(parent):
    payload = {"blockdevices": [
        _disk("sda"), _disk("sdb"),
        _disk("dm-0", type="crypt", pkname=parent),
        _disk("dm-1", type="lvm", pkname="dm-0", mountpoints=["/media/data"]),
    ]}
    result = _discover(payload, ["/dev/sdb"])
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_mounted_duplicate_parent_excludes_each_possible_disk():
    payload = {"blockdevices": [
        _disk("sda"), _disk("sdb"), _disk("sdc"),
        _disk("partition", type="part", pkname="sda"),
        _disk("partition", type="part", pkname="sdc"),
        _disk("dm-0", type="crypt", pkname="partition", mountpoints=["/media/data"]),
    ]}
    result = _discover(payload, ["/dev/sdb"])
    assert result.boot_identified
    assert result.selectable == ()


@pytest.mark.parametrize("unknown", ["UUID=missing", "/dev/sdz", "/dev/loop0"])
@pytest.mark.parametrize("known_first", [True, False])
def test_unknown_second_live_source_is_order_independent(unknown, known_first):
    payload = {"blockdevices": [
        _disk("sda"), _disk("sdb"), _disk("loop0", type="loop"),
    ]}
    sources = ["/dev/sdb", unknown]
    result = _discover(payload, sources if known_first else sources[::-1])
    assert not result.boot_identified
    assert result.selectable == ()


def test_known_live_sources_same_owner_allow_unrelated_loop_device():
    payload = {"blockdevices": [
        _disk("sda"),
        _disk("sdb", children=[_disk("sdb1", type="part")]),
        _disk("loop0", type="loop"),
    ]}
    result = _discover(payload, ["/dev/sdb", "/dev/sdb1", "/dev/sdb1"])
    assert result.boot_identified
    assert [disk.path for disk in result.selectable] == ["/dev/sda"]


@pytest.mark.parametrize("transport", ["nvme", "sata", "usb", "virtio"])
def test_local_transport_eligibility_preserved(transport):
    payload = {"blockdevices": [_disk("sda", tran=transport), _disk("sdb")]}
    result = _discover(payload, ["/dev/sdb"])
    assert [disk.path for disk in result.selectable] == ["/dev/sda"]
