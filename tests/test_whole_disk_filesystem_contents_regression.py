"""A filesystem directly on a whole disk is data evidence."""

from __future__ import annotations

from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.models import CONTENTS_DATA, CONTENTS_UNKNOWN, CONTENTS_WINDOWS


SIZE = 100_000_000_000


def _disk(
    name: str, *, filesystem: bool = False, children: list[dict] | None = None
) -> dict:
    row = {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "size": SIZE,
        "tran": "usb" if name == "sdb" else "sata",
        "ro": 0,
        "mountpoints": [None],
    }
    if filesystem:
        row.update(fstype="ntfs", uuid="BACKUP-FS", label="BACKUP")
    if children is not None:
        row["children"] = children
    return row


def _target(*, filesystem: bool = False, children: list[dict] | None = None):
    result = parse_lsblk_json(
        {
            "blockdevices": [
                _disk("sda", filesystem=filesystem, children=children),
                _disk("sdb"),
            ]
        },
        boot_path="/dev/sdb",
    )
    assert result.boot_identified
    return next(d for d in result.selectable if d.path == "/dev/sda")


def test_unmounted_whole_disk_ntfs_is_data_content() -> None:
    target = _target(filesystem=True)
    assert target.contents == CONTENTS_DATA
    assert target.layout_id


def test_whole_disk_without_filesystem_stays_unknown() -> None:
    assert _target().contents == CONTENTS_UNKNOWN


def test_partition_windows_evidence_still_takes_precedence() -> None:
    recovery = {
        "name": "sda1",
        "path": "/dev/sda1",
        "type": "part",
        "pkname": "sda",
        "size": SIZE,
        "fstype": "ntfs",
        "partlabel": "Windows Recovery",
        "mountpoints": [None],
    }
    assert _target(children=[recovery]).contents == CONTENTS_WINDOWS
