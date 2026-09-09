"""Discovery audit regressions using synthetic metadata only."""

import importlib

import pytest


discovery = importlib.import_module("beamo_wipe.discover")


def disk(name, **changes):
    row = {
        "name": name, "path": f"/dev/{name}", "type": "disk",
        "size": 32_000_000_000, "model": "Fake disk", "serial": name,
        "tran": "usb", "rota": False, "ro": False,
        "mountpoints": [None], "mountpoint": None,
    }
    row.update(changes)
    return row


def probe(monkeypatch, rows, boot="/dev/sdb"):
    monkeypatch.setattr(discovery, "run_lsblk", lambda: {"blockdevices": rows})
    return discovery.discover(mount_sources=[boot], cmdline="", env={})


@pytest.mark.parametrize("missing_parent", [None, "", "absent"])
@pytest.mark.parametrize("name,kind", [("sda1", "part"), ("dm-0", "crypt"), ("dm-1", "lvm"), ("md0", "raid1"), ("dm-2", "mpath"), ("unknown0", "unknown")])
def test_mounted_flat_child_missing_parent_fails_closed(monkeypatch, missing_parent, name, kind):
    # A detached mounted child whose owner is unknown cannot establish that
    # the separately listed physical disk is unmounted.
    child = disk(name, type=kind, mountpoints=["/media/data"])
    if missing_parent != "absent":
        child["pkname"] = missing_parent
    result = probe(monkeypatch, [disk("sda"), disk("sdb"), child])
    assert not result.boot_identified
    assert result.selectable == ()


def test_missing_parent_retry_with_complete_ancestry_recovers(monkeypatch):
    first = probe(monkeypatch, [disk("sda"), disk("sdb"), disk("sda1", type="part", mountpoints=["/media/data"])])
    assert first.selectable == ()
    second = probe(monkeypatch, [disk("sda"), disk("sdb"), disk("sdc"), disk("sda1", type="part", pkname="sda", mountpoints=["/media/data"])])
    assert second.boot_identified
    assert [target.path for target in second.selectable] == ["/dev/sdc"]


def test_standalone_mounted_optical_and_loop_are_not_unresolved_children(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda"),
        disk("sr0", type="rom", mountpoints=["/run/live/medium"]),
        disk("loop0", type="loop", mountpoints=["/run/live/rootfs/filesystem.squashfs"]),
    ], boot="/dev/sr0")
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sda"]


@pytest.mark.parametrize("kind", ["raid1", "raid0", "mpath"])
def test_mounted_multiparent_volume_does_not_leave_sibling_selectable(monkeypatch, kind):
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("sdb", tran="sata"),
        disk("sdc"),
        disk("sda1", type="part", pkname="sda", tran="sata"),
        disk("sdb1", type="part", pkname="sdb", tran="sata"),
        disk("md0", type=kind, pkname="sda1", mountpoints=["/media/data"]),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


@pytest.mark.parametrize("kind", ["raid1", "raid0", "mpath"])
def test_nested_mounted_multiparent_volume_does_not_leave_sibling_selectable(monkeypatch, kind):
    # Production `lsblk -J` nests the array under one member. The sibling
    # must not remain a normal unmounted disk.
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[
            disk("sda1", type="part", tran="sata", children=[
                disk("md0", type=kind, mountpoints=["/media/data"]),
            ]),
        ]),
        disk("sdb", tran="sata", children=[disk("sdb1", type="part", tran="sata")]),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_nested_mounted_child_without_pkname_uses_tree_parent(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", children=[disk("sda1", type="part", mountpoints=["/media/data"])]),
        disk("sdb"), disk("sdc"),
    ])
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sdc"]
