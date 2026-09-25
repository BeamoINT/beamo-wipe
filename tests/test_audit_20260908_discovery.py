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


@pytest.mark.parametrize("kind,member_fs", [("lvm", "LVM2_member"), ("linear", "linux_raid_member")])
def test_mounted_stacked_volume_does_not_leave_another_member_selectable(monkeypatch, kind, member_fs):
    """Reported members do not prove an unmarked disk is outside the stack."""
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[
            disk("sda1", type="part", tran="sata", children=[
                disk("holder0", type=kind, mountpoints=["/mnt/data"]),
            ]),
        ]),
        disk("sdb", tran="sata", children=[
            disk("sdb1", type="part", tran="sata", fstype=member_fs),
        ]),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_lvm_on_multipath_does_not_leave_the_other_leg_selectable(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("sdb", tran="sata"),
        disk("sdc"),
        disk("mpatha", type="mpath", pkname="sda"),
        disk("dm-0", type="lvm", pkname="mpatha", mountpoints=["/"]),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_partition_on_mounted_bcache_holder_refuses_unknown_members(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("bcache0", pkname="sda", tran=None, serial="BCACHE0"),
        disk("bcache0p1", type="part", pkname="bcache0", mountpoints=["/home"], fstype="ext4"),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    # PKNAME identifies one backing device, but cannot prove that sdd is not
    # a cache member whose signature is missing from this lsblk snapshot.
    assert not result.boot_identified
    assert result.selectable == ()


def test_mounted_bcache_refuses_even_when_known_members_are_marked(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[
            disk("sda1", type="part", fstype="bcache", children=[
                disk("bcache0", mountpoints=["/mnt/data"], serial="BCACHE0"),
            ]),
        ]),
        disk("sdb", tran="sata", children=[
            disk("sdb1", type="part", fstype="bcache"),
        ]),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    # Marking two known members does not prove there is no third cache member.
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_mounted_disk_holder_refuses_unknown_bcache_members(monkeypatch):
    """One PKNAME on a mounted bcache row is not a complete member list."""
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("bcache0", pkname="sda", mountpoints=["/mnt/data"], tran=None, serial="BCACHE0"),
        disk("sdd", tran="sata"),
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


def _part(name, pk, **changes):
    return disk(name, type="part", pkname=pk, tran="sata", **changes)


def test_mounted_btrfs_member_blocks_unproven_inventory(monkeypatch):
    """Even a shared UUID does not prove that every member was reported."""
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[
            _part("sda1", "sda", fstype="btrfs", uuid="FS", mountpoints=["/data"]),
        ]),
        disk("sdb", tran="sata", children=[
            _part("sdb1", "sdb", fstype="btrfs", uuid="FS"),
        ]),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_whole_disk_btrfs_mount_blocks_unproven_inventory(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", fstype="btrfs", uuid="FS", mountpoints=["/data"]),
        disk("sdb", tran="sata", fstype="btrfs", uuid="FS"),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_shared_uuid_without_fstype_cannot_prove_btrfs_membership(monkeypatch):
    """A member can show the filesystem UUID before fstype is filled in."""
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[
            _part("sda1", "sda", fstype="btrfs", uuid="FS", mountpoints=["/data"]),
        ]),
        disk("sdb", tran="sata", children=[
            _part("sdb1", "sdb", uuid="FS"),
        ]),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_shared_uuid_with_a_different_fstype_cannot_prove_btrfs_membership(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[
            _part("sda1", "sda", fstype="btrfs", uuid="FS", mountpoints=["/data"]),
        ]),
        disk("sdb", tran="sata", children=[
            _part("sdb1", "sdb", fstype="ext4", uuid="FS"),
        ]),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_different_btrfs_uuid_cannot_prove_membership(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[
            _part("sda1", "sda", fstype="btrfs", uuid="FS", mountpoints=["/data"]),
        ]),
        disk("sdb", tran="sata", children=[
            _part("sdb1", "sdb", fstype="btrfs", uuid="OTHER"),
        ]),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_empty_filesystem_uuid_cannot_prove_btrfs_membership(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", fstype="btrfs", uuid="", mountpoints=["/data"]),
        disk("sdb", tran="sata", fstype="btrfs", uuid=""),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_lvm_members_do_not_prove_complete_membership(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("sdb", tran="sata"),
        disk("sdd", tran="sata"),
        disk("sdc"),
        _part("sda1", "sda", fstype="LVM2_member"),
        _part("sdb1", "sdb", fstype="LVM2_member"),
        disk("vg-lv", type="lvm", pkname="sda1", mountpoints=["/mnt/data"]),
    ], boot="/dev/sdc")
    # A third physical member can have empty or stale LVM metadata.
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_bcache_members_do_not_prove_complete_membership(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("sdb", tran="sata"),
        disk("sdd", tran="sata"),
        disk("sdc"),
        _part("sda1", "sda", fstype="bcache"),
        _part("sdb1", "sdb", fstype="bcache"),
        disk("bcache0", pkname="sda", mountpoints=["/mnt/data"], serial="BCACHE0"),
    ], boot="/dev/sdc")
    # The extra disk may still be an unreported or stale cache member.
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_mount_above_the_volume_does_not_leave_another_member_selectable(monkeypatch):
    """The open filesystem can sit on a device above the LVM or md holder.

    lsblk then puts the mount on that upper device. The other physical
    member still shows only the member filesystem; membership completeness
    remains unknown for any other disk in the inventory.
    """
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("sdb", tran="sata"),
        disk("sdd", tran="sata"),
        disk("sdc"),
        _part("sda1", "sda", fstype="LVM2_member"),
        _part("sdb1", "sdb", fstype="LVM2_member"),
        disk("dm-0", type="lvm", pkname="sda1", serial="LV"),
        disk("dm-1", type="crypt", pkname="dm-0", mountpoints=["/mnt/data"], fstype="ext4", serial="CRYPT"),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_flat_partition_above_linear_refuses_unknown_members(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("sdb", tran="sata"),
        disk("sdd", tran="sata"),
        disk("sdc"),
        _part("sda1", "sda", fstype="linux_raid_member"),
        _part("sdb1", "sdb", fstype="linux_raid_member"),
        disk("md0", type="linear", pkname="sda1", serial="MD"),
        _part("md0p1", "md0", fstype="ext4", mountpoints=["/mnt/data"]),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()


def test_single_disk_luks_does_not_consume_an_unrelated_member(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[
            _part("sda1", "sda", fstype="crypto_LUKS", children=[
                disk("dm-0", type="crypt", mountpoints=["/mnt/data"], fstype="ext4", serial="CRYPT"),
            ]),
        ]),
        disk("sdb", tran="sata", children=[
            _part("sdb1", "sdb", fstype="LVM2_member"),
        ]),
        disk("sdd", tran="sata"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sdb", "/dev/sdd"]


def test_filesystem_on_bcache_disk_keeps_the_os_warning(monkeypatch):
    """bcache is a type=disk holder. Its filesystem is the backing disk's contents."""
    result = probe(monkeypatch, [
        disk("sda", tran="sata"),
        disk("sdc"),
        _part("sda1", "sda", fstype="vfat", label="EFI", parttypename="EFI System",
              parttype="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"),
        _part("sda2", "sda", fstype="bcache"),
        disk("bcache0", pkname="sda", fstype="ext4", label="root", serial="BC0", tran=None),
    ], boot="/dev/sdc")
    assert result.boot_identified
    backing = next(item for item in result.disks if item.path == "/dev/sda")
    assert backing.contents == "system"
    assert "/dev/bcache0" not in [target.path for target in result.selectable]


def test_mounted_wwn_alias_is_not_selectable(monkeypatch):
    """Another path with the mounted disk's WWN is the same LUN.

    The mount is recorded on one path. The other path must not be erased.
    """
    result = probe(monkeypatch, [
        disk("sda", tran="sata", wwn="Same-LUN", serial="PATH-A", children=[
            _part("sda1", "sda", fstype="ext4", mountpoints=["/data"]),
        ]),
        disk("sdb", tran="sata", wwn="same-lun", serial="PATH-B"),
        disk("sdd", tran="sata", wwn="other-lun", serial="OTHER"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sdd"]


def test_unmounted_duplicate_wwn_stays_selectable(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", wwn="same-lun", serial="PATH-A"),
        disk("sdb", tran="sata", wwn="same-lun", serial="PATH-B"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sda", "/dev/sdb"]


def test_blank_wwn_does_not_glue_a_mounted_disk(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", wwn="0x0000", serial="PATH-A", children=[
            _part("sda1", "sda", fstype="ext4", mountpoints=["/data"]),
        ]),
        disk("sdb", tran="sata", wwn="0x0000", serial="PATH-B"),
        disk("sdd", tran="sata", wwn="", serial="PLAIN"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sdb", "/dev/sdd"]


def test_same_serial_different_wwn_stays_selectable_when_one_is_mounted(monkeypatch):
    result = probe(monkeypatch, [
        disk("sda", tran="sata", wwn="wwn-a", serial="SAME-SERIAL", children=[
            _part("sda1", "sda", fstype="ext4", mountpoints=["/data"]),
        ]),
        disk("sdb", tran="sata", wwn="wwn-b", serial="SAME-SERIAL"),
        disk("sdc"),
    ], boot="/dev/sdc")
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sdb"]


@pytest.mark.parametrize("kind", ["dmraid", "faulty", "multipath"])
def test_mounted_hidden_member_holder_fails_closed(monkeypatch, kind):
    """Bookworm lsblk types that do not start with ``raid`` still hide a leg."""
    result = probe(monkeypatch, [
        disk("sda", tran="sata", children=[_part("sda1", "sda")]),
        disk("sdb", tran="sata", children=[_part("sdb1", "sdb")]),
        disk("sdd", tran="sata"),
        disk("sdc"),
        disk("holder0", type=kind, pkname="sda1", mountpoints=["/data"]),
    ], boot="/dev/sdc")
    assert not result.boot_identified
    assert result.selectable == ()
