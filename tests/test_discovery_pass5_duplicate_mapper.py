"""A repeated mounted device-mapper node cannot leave one member wipeable."""

from beamo_wipe.discover import discover


def _disk(name: str, child: dict) -> dict:
    return {
        "name": name,
        "path": f"/dev/{name}",
        "size": 256_000_000_000,
        "type": "disk",
        "tran": "sata",
        "serial": f"SERIAL-{name}",
        "model": "Example disk",
        "ro": False,
        "mountpoints": [None],
        "children": [child],
    }


def _part(name: str, child: dict) -> dict:
    return {
        "name": name,
        "path": f"/dev/{name}",
        "type": "part",
        "pkname": name[:-1],
        "mountpoints": [None],
        "children": [child],
    }


def _mapper(parent: str, mount: str | None) -> dict:
    return {
        "name": "dm-0",
        "path": "/dev/dm-0",
        "type": "crypt",
        "pkname": parent,
        "fstype": "ext4",
        "uuid": "SHARED-MAPPER-UUID" if mount else None,
        "mountpoints": [mount],
    }


def test_repeated_mounted_mapper_with_two_parent_disks_refuses_selection() -> None:
    # lsblk can repeat a dependency node under each of its physical members.
    # Only one copy reports the mount here; /dev/sdb is still backing the
    # mounted /dev/dm-0 and must not be a wipe target.
    payload = {
        "blockdevices": [
            {
                "name": "sr0",
                "path": "/dev/sr0",
                "type": "rom",
                "size": 1_000_000_000,
                "mountpoints": ["/run/live/medium"],
            },
            _disk("sda", _part("sda1", _mapper("sda1", "/mnt/data"))),
            _disk("sdb", _part("sdb1", _mapper("sdb1", None))),
        ]
    }

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=["/dev/sr0"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert result.selectable == ()


def test_repeated_mapper_with_stale_pkname_cannot_expose_tree_member() -> None:
    # The second lsblk copy omits the mount and filesystem fields and repeats
    # a stale PKNAME. Its tree still places that same mapper below /dev/sdb.
    stale = _mapper("sda1", None)
    stale["fstype"] = None
    payload = {
        "blockdevices": [
            {
                "name": "sr0",
                "path": "/dev/sr0",
                "type": "rom",
                "size": 1_000_000_000,
                "mountpoints": ["/run/live/medium"],
            },
            _disk("sda", _part("sda1", _mapper("sda1", "/mnt/data"))),
            _disk("sdb", _part("sdb1", stale)),
        ]
    }

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=["/dev/sr0"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert result.selectable == ()


def test_repeated_mapper_on_one_disk_keeps_unrelated_target() -> None:
    same_owner = _part("sda1", _mapper("sda1", "/mnt/data"))
    same_owner["children"].append(_mapper("sda1", None))
    payload = {
        "blockdevices": [
            {
                "name": "sr0",
                "path": "/dev/sr0",
                "type": "rom",
                "size": 1_000_000_000,
                "mountpoints": ["/run/live/medium"],
            },
            _disk("sda", same_owner),
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 256_000_000_000,
                "type": "disk",
                "tran": "sata",
                "serial": "SERIAL-sdb",
                "model": "Example disk",
                "ro": False,
                "mountpoints": [None],
            },
        ]
    }

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=["/dev/sr0"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert [disk.path for disk in result.selectable] == ["/dev/sdb"]


def test_unmounted_shared_mapper_without_content_stays_wipeable() -> None:
    # An unopened, unmounted mapping has no mount or filesystem claims to
    # misassign. Keep the existing ability to erase its physical members.
    empty_a = _mapper("sda1", None)
    empty_b = _mapper("sdb1", None)
    for node in (empty_a, empty_b):
        node["fstype"] = None
        node["uuid"] = None
    payload = {
        "blockdevices": [
            {
                "name": "sr0",
                "path": "/dev/sr0",
                "type": "rom",
                "size": 1_000_000_000,
                "mountpoints": ["/run/live/medium"],
            },
            _disk("sda", _part("sda1", empty_a)),
            _disk("sdb", _part("sdb1", empty_b)),
        ]
    }

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=["/dev/sr0"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert [disk.path for disk in result.selectable] == ["/dev/sda", "/dev/sdb"]


def test_mounted_mapper_path_cannot_alias_another_physical_disk() -> None:
    # A malformed/stale lsblk inventory assigns /dev/sdb to both a mounted
    # mapper and a physical disk. The shared path cannot be a wipe target.
    mapper = _mapper("sda1", "/mnt/data")
    mapper["path"] = "/dev/sdb"
    payload = {
        "blockdevices": [
            {
                "name": "sr0",
                "path": "/dev/sr0",
                "type": "rom",
                "size": 1_000_000_000,
                "mountpoints": ["/run/live/medium"],
            },
            _disk("sda", _part("sda1", mapper)),
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 256_000_000_000,
                "type": "disk",
                "tran": "sata",
                "serial": "SERIAL-sdb",
                "model": "Example disk",
                "ro": False,
                "mountpoints": [None],
            },
        ]
    }

    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=["/dev/sr0"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )

    assert result.selectable == ()
