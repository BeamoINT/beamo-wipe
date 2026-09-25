# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparation and aftercare copy from fake disks only."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import textwrap

import pytest

from beamo_wipe import copy as C
from beamo_wipe.discover import classify_contents, node_to_disk
from beamo_wipe.models import CONTENTS_VALUES
from beamo_wipe.outcomes import AFTERCARE_SUCCESS, VIEWS, preview_view
from beamo_wipe.session_recovery import _disk
from beamo_wipe.ui import console_wizard as console
from test_result_presentations import CASES, case_evidence


REPO = Path(__file__).resolve().parents[1]


def _part(path, **fields):
    node = {
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "type": "part",
        "size": 1_000_000_000,
    }
    node.update(fields)
    return node


def _disk_node(path="/dev/nvme0n1", children=None, **fields):
    node = {
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "type": "disk",
        "size": 256_000_000_000,
        "tran": "nvme",
        "rota": False,
        "model": "Fake Disk",
        "serial": "FAKE-SERIAL",
        "children": children or [],
    }
    node.update(fields)
    return node


def test_windows_partitions_are_system_windows():
    node = _disk_node(
        children=[
            _part("/dev/nvme0n1p1", fstype="vfat", label="EFI", parttypename="EFI System"),
            _part("/dev/nvme0n1p2", fstype="ntfs", label="Windows"),
            _part(
                "/dev/nvme0n1p3",
                fstype="ntfs",
                label="Recovery",
                parttype="de94bba4-06d1-4d40-a16a-bfd50179d6ac",
            ),
        ]
    )
    assert classify_contents(node) == "windows"
    disk = node_to_disk(node, False)
    assert disk.contents == "windows"
    text = C.prepare_selected(disk)
    assert text == C.PREPARE_WINDOWS
    assert "Windows" in text
    assert "recovery partitions on this disk" in text
    assert C.confirm_warning(disk).endswith(text)


def test_linux_efi_root_is_system_not_windows():
    node = _disk_node(
        children=[
            _part("/dev/nvme0n1p1", fstype="vfat", label="EFI", parttypename="EFI System"),
            _part("/dev/nvme0n1p2", fstype="ext4", label="root"),
        ]
    )
    assert classify_contents(node) == "system"
    disk = node_to_disk(node, False)
    text = C.prepare_selected(disk)
    assert text == C.PREPARE_SYSTEM
    assert "Windows," not in text
    assert "operating system" in text


def test_data_disk_has_no_os_partitions():
    node = _disk_node(
        path="/dev/sdb",
        children=[_part("/dev/sdb1", fstype="exfat", label="PHOTOS")],
    )
    assert classify_contents(node) == "data"
    disk = node_to_disk(node, False)
    text = C.prepare_selected(disk)
    assert text == C.PREPARE_DATA
    assert "does not show operating-system partitions" in text
    assert "every file on this disk" in text


def test_windows_gpt_names_from_lsblk_partlabel_are_not_called_data():
    """A normal Windows disk exposes OS identity in the GPT partition name.

    Filesystem LABEL is often empty. PARTLABEL is present even when PARTTYPE
    and PARTTYPENAME are absent. Those names must not be described as a data disk.
    """
    node = _disk_node(
        path="/dev/nvme0n1",
        children=[
            _part(
                "/dev/nvme0n1p1",
                fstype="vfat",
                partlabel="EFI system partition",
            ),
            _part(
                "/dev/nvme0n1p2",
                partlabel="Microsoft reserved partition",
            ),
            _part(
                "/dev/nvme0n1p3",
                fstype="ntfs",
                partlabel="Basic data partition",
            ),
        ],
    )
    assert classify_contents(node) == "windows"
    assert C.prepare_selected(node_to_disk(node, False)) == C.PREPARE_WINDOWS
    reserved = _disk_node(
        children=[_part("/dev/nvme0n1p1", partlabel="Microsoft reserved partition")]
    )
    assert classify_contents(reserved) == "windows"


def test_partlabel_ntfs_data_and_linux_root_keep_their_claims():
    photos = _disk_node(
        path="/dev/sdd",
        children=[
            _part(
                "/dev/sdd1",
                fstype="ntfs",
                label="PHOTOS",
                partlabel="Basic data partition",
            )
        ],
    )
    assert classify_contents(photos) == "data"
    linux = _disk_node(
        children=[
            _part("/dev/nvme0n1p1", fstype="vfat", partlabel="EFI system partition"),
            _part("/dev/nvme0n1p2", fstype="ext4", partlabel="root"),
        ]
    )
    assert classify_contents(linux) == "system"
    removable = _disk_node(
        children=[
            _part("/dev/sdb1", fstype="vfat", partlabel="EFI system partition"),
            _part("/dev/sdb2", fstype="vfat", label="DATA"),
        ]
    )
    assert classify_contents(removable) == "data"


def test_windows_partition_type_guid_without_names_is_windows():
    node = _disk_node(
        children=[
            _part(
                "/dev/nvme0n1p1",
                fstype="vfat",
                parttype="c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
            ),
            _part("/dev/nvme0n1p2", fstype="ntfs"),
        ]
    )
    assert classify_contents(node) == "windows"


def test_ntfs_data_without_windows_marks_is_not_a_windows_claim():
    node = _disk_node(
        path="/dev/sdd",
        children=[
            _part(
                "/dev/sdd1",
                fstype="ntfs",
                label="PHOTOS",
                parttypename="Microsoft basic data",
            )
        ],
    )
    assert classify_contents(node) == "data"
    assert "Windows partitions" not in C.prepare_selected(node_to_disk(node, False))


def test_bitlocker_and_msr_are_windows():
    bitlocker = _disk_node(
        children=[
            _part("/dev/nvme0n1p1", fstype="vfat", label="EFI"),
            _part("/dev/nvme0n1p2", fstype="BitLocker", label="Windows"),
        ]
    )
    assert classify_contents(bitlocker) == "windows"
    msr = _disk_node(
        children=[
            _part(
                "/dev/nvme0n1p1",
                parttypename="Microsoft reserved",
                parttype="e3c9e316-0b5c-4db8-817d-f92df00215ae",
            )
        ]
    )
    assert classify_contents(msr) == "windows"


def test_vfat_efi_without_posix_is_data_not_an_os_claim():
    node = _disk_node(
        children=[
            _part("/dev/sdb1", fstype="vfat", label="EFI", parttypename="EFI System"),
            _part("/dev/sdb2", fstype="vfat", label="DATA"),
        ]
    )
    assert classify_contents(node) == "data"
    assert "operating-system partitions" in C.prepare_selected(node_to_disk(node, False))


def test_missing_fstype_is_unknown_not_a_windows_claim():
    node = _disk_node(children=[_part("/dev/nvme0n1p1"), _part("/dev/nvme0n1p2")])
    assert classify_contents(node) == "unknown"
    disk = node_to_disk(node, False)
    text = C.prepare_selected(disk)
    assert text == C.PREPARE_UNKNOWN
    assert "Windows partitions" not in text


def test_whole_disk_filesystem_is_data_without_claiming_windows_os():
    node = _disk_node(children=[], fstype="ntfs", label="Windows")
    assert classify_contents(node) == "data"
    text = C.prepare_selected(node_to_disk(node, False))
    assert text == C.PREPARE_DATA
    assert "Windows partitions" not in text


def test_opened_luks_or_lvm_root_is_not_called_a_data_disk():
    """EFI plus an opened root filesystem is an OS disk, not a data disk."""
    for holder, kind in (("crypto_LUKS", "crypt"), ("LVM2_member", "lvm")):
        node = _disk_node(
            children=[
                _part(
                    "/dev/nvme0n1p1",
                    fstype="vfat",
                    label="EFI",
                    parttypename="EFI System",
                ),
                _part(
                    "/dev/nvme0n1p2",
                    fstype=holder,
                    children=[
                        {
                            "name": "dm-0",
                            "path": "/dev/dm-0",
                            "type": kind,
                            "fstype": "ext4",
                            "label": "root",
                        }
                    ],
                ),
            ]
        )
        assert classify_contents(node) == "system"
        assert C.prepare_selected(node_to_disk(node, False)) == C.PREPARE_SYSTEM


def test_opened_windows_volume_is_not_called_a_data_disk():
    node = _disk_node(
        children=[
            _part("/dev/nvme0n1p1", fstype="vfat", label="EFI", parttypename="EFI System"),
            _part(
                "/dev/nvme0n1p2",
                fstype="crypto_LUKS",
                children=[
                    {
                        "name": "dm-0",
                        "path": "/dev/dm-0",
                        "type": "crypt",
                        "fstype": "ntfs",
                        "label": "Windows",
                    }
                ],
            ),
        ]
    )
    assert classify_contents(node) == "windows"
    assert C.prepare_selected(node_to_disk(node, False)) == C.PREPARE_WINDOWS


def test_filesystem_on_a_bcache_disk_is_not_called_a_data_disk():
    """lsblk reports bcache as type=disk. The filesystem still belongs to the backing disk."""
    node = _disk_node(
        children=[
            _part("/dev/nvme0n1p1", fstype="vfat", label="EFI", parttypename="EFI System"),
            _part(
                "/dev/nvme0n1p2",
                fstype="bcache",
                children=[
                    {
                        "name": "bcache0",
                        "path": "/dev/bcache0",
                        "type": "disk",
                        "pkname": "nvme0n1p2",
                        "fstype": "ext4",
                        "label": "root",
                    }
                ],
            ),
        ]
    )
    assert classify_contents(node) == "system"
    assert C.prepare_selected(node_to_disk(node, False)) == C.PREPARE_SYSTEM

    windows = _disk_node(
        children=[
            _part("/dev/nvme0n1p1", fstype="vfat", label="EFI", parttypename="EFI System"),
            _part(
                "/dev/nvme0n1p2",
                fstype="bcache",
                children=[
                    {
                        "name": "bcache0",
                        "path": "/dev/bcache0",
                        "type": "disk",
                        "pkname": "nvme0n1p2",
                        "fstype": "ntfs",
                        "label": "Windows",
                    }
                ],
            ),
        ]
    )
    assert classify_contents(windows) == "windows"
    assert C.prepare_selected(node_to_disk(windows, False)) == C.PREPARE_WINDOWS


def test_opened_ext4_without_efi_stays_a_data_disk():
    node = _disk_node(
        children=[
            _part(
                "/dev/sdb1",
                fstype="crypto_LUKS",
                children=[
                    {
                        "name": "dm-0",
                        "path": "/dev/dm-0",
                        "type": "crypt",
                        "fstype": "ext4",
                        "label": "photos",
                    }
                ],
            )
        ]
    )
    assert classify_contents(node) == "data"
    assert C.prepare_selected(node_to_disk(node, False)) == C.PREPARE_DATA


def test_flat_windows_partition_rows_keep_the_windows_warning(monkeypatch, tmp_path):
    from beamo_wipe.discover import discover

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    found = discover(
        lsblk_payload={
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": 80_000_000_000,
                    "tran": "sata",
                    "model": "WIN DISK",
                    "serial": "WIN-1",
                    "wwn": "win-wwn",
                },
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "pkname": "sda",
                    "fstype": "vfat",
                    "label": "EFI",
                    "parttypename": "EFI System",
                    "size": 500_000_000,
                },
                {
                    "name": "sda2",
                    "path": "/dev/sda2",
                    "type": "part",
                    "pkname": "sda",
                    "fstype": "ntfs",
                    "label": "Windows",
                    "size": 70_000_000_000,
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
        },
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    disk = next(item for item in found.selectable if item.path == "/dev/sda")
    assert disk.contents == "windows"
    assert C.prepare_selected(disk) == C.PREPARE_WINDOWS


def test_demo_disks_without_fstype_stay_unknown():
    from beamo_wipe.demo import make_demo_wizard

    for disk in make_demo_wizard().selectable:
        assert disk.contents == "unknown"
        assert C.prepare_selected(disk) == C.PREPARE_UNKNOWN


@pytest.mark.parametrize("code,view", list(VIEWS.items()))
def test_aftercare_only_follows_successful_outcomes(code, view):
    if view.success:
        assert AFTERCARE_SUCCESS in view.next_step
        assert "validated selected disk" in view.next_step
        assert "separate task" in view.next_step
    else:
        assert AFTERCARE_SUCCESS not in view.next_step
        assert "was processed" not in view.next_step
        assert "Putting an operating system back on" not in view.next_step


@pytest.mark.parametrize("ok", [True, False])
def test_preview_result_never_claims_a_disk_was_processed(ok):
    view = preview_view(ok)
    assert AFTERCARE_SUCCESS not in view.next_step
    assert "was processed" not in view.next_step
    assert "Nothing on this computer was erased" in view.next_step


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_finished_console_keeps_identity_and_scoped_aftercare(case, capsys, monkeypatch):
    wiz, _, _ = case_evidence(case)
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    out = capsys.readouterr().out
    view = wiz.result_view
    assert view.message in out
    assert view.next_step in out
    assert wiz.selected.display_name in out
    if view.success:
        assert AFTERCARE_SUCCESS in out
    else:
        assert AFTERCARE_SUCCESS not in out
        assert "was processed" not in out


class _Terminal:
    def __init__(self, wizard):
        self.rows = {}
        self.wizard = wizard

    def getmaxyx(self):
        return 24, 80

    def addstr(self, y, x, text, attr=0):
        assert 0 <= y < 24
        assert len(text) < 80
        self.rows[y] = text

    def getch(self):
        self.wizard.wants_shutdown = True
        return ord("q")

    def __getattr__(self, name):
        return lambda *a, **k: None


def _draw_console(monkeypatch, wiz):
    terminal = _Terminal(wiz)
    monkeypatch.setattr(console.curses, "curs_set", lambda *a: None)
    monkeypatch.setattr(console.curses, "use_default_colors", lambda *a: None)
    console._loop(terminal, wiz)
    shown = " ".join(terminal.rows[y] for y in sorted(terminal.rows))
    assert all(len(line) < 80 for line in terminal.rows.values())
    return shown, terminal


def test_console_what_wraps_prepare_bullets_at_80x24(monkeypatch):
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import Screen

    wiz = make_demo_wizard()
    wiz.skip_intro()
    assert wiz.screen == Screen.OWNER
    shown, _ = _draw_console(monkeypatch, wiz)
    for bullet in C.WHAT_BULLETS:
        for word in bullet.split():
            assert word in shown
    assert "copies you need" in shown
    assert "recovery partitions" in shown
    assert all(len(line) <= 78 for line in textwrap.wrap(" ".join(C.WHAT_BULLETS), 78))


def test_console_last_chance_keeps_identity_and_prepare(monkeypatch):
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import Screen

    wiz = make_demo_wizard()
    disk = node_to_disk(
        _disk_node(
            children=[
                _part("/dev/nvme0n1p1", fstype="vfat", label="EFI"),
                _part("/dev/nvme0n1p2", fstype="ntfs", label="Windows"),
            ]
        ),
        False,
    )
    wiz.selected = replace(wiz.selectable[0], contents=disk.contents, model=disk.model)
    wiz.screen = Screen.LAST_CHANCE
    shown, _ = _draw_console(monkeypatch, wiz)
    assert wiz.prepare_text() == C.PREPARE_WINDOWS
    assert "Fake Disk" in shown
    assert "Windows" in shown
    assert "recovery partitions" in shown
    assert "Wait" in shown or "Enter to erase" in shown


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_console_done_wraps_aftercare_at_80x24(case, monkeypatch):
    wiz, _, _ = case_evidence(case)
    shown, _ = _draw_console(monkeypatch, wiz)
    assert wiz.result_view.message in shown or wiz.result_view.message.split(";")[0] in shown
    if wiz.result_view.success:
        assert "validated selected disk" in shown
        assert "separate task" in shown
    else:
        assert "was processed" not in shown
        assert "validated selected disk" not in shown


def test_helper_and_what_copy_agree_on_backups_and_os_disks():
    helper = (REPO / "helper" / "index.html").read_text(encoding="utf-8")
    blob = " ".join(C.WHAT_BULLETS) + " " + helper
    assert C.WHAT_BULLETS[0] in helper
    assert "copies you need" in blob
    assert "recovery partitions on that disk" in helper
    assert "Only the disk you confirm is erased" in helper
    assert "separate task" in helper
    assert "was processed" not in helper
    assert "impossible to recover" not in blob.lower()


def test_session_disk_contents_round_trip_and_reject_unknown():
    disk = node_to_disk(
        _disk_node(children=[_part("/dev/sdb1", fstype="exfat", label="PHOTOS")]),
        False,
    )
    raw = asdict(disk)
    raw["kind"] = disk.kind.value
    raw["mountpoints"] = []
    loaded = _disk(raw)
    assert loaded.contents == "data"
    assert loaded.contents in CONTENTS_VALUES
    bad = dict(raw)
    bad["contents"] = "os"
    with pytest.raises(ValueError, match="contents"):
        _disk(bad)
    missing = dict(raw)
    missing.pop("contents")
    with pytest.raises(ValueError):
        _disk(missing)


def test_prepare_and_aftercare_avoid_recovery_promises():
    blob = " ".join(
        [
            *C.WHAT_BULLETS,
            C.PREPARE_WINDOWS,
            C.PREPARE_SYSTEM,
            C.PREPARE_DATA,
            C.PREPARE_UNKNOWN,
            AFTERCARE_SUCCESS,
        ]
    ).lower()
    for phrase in (
        "impossible to recover",
        "plug and play",
        "certified",
        "we can restore",
        "files can be recovered",
    ):
        assert phrase not in blob
