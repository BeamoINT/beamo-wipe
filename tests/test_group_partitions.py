# SPDX-License-Identifier: GPL-3.0-or-later
"""Partitions nest under physical disks. Fake lsblk only; nothing is erased."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.gallery import gallery_html
from beamo_wipe.inventory import (
    NESTED_INTRO,
    TITLE,
    card_nesting_text,
    full_text,
    nested_heading,
    nested_under,
    other_devices,
)
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.safety import selectable_disks
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import Wizard

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _grouped(name: str = "lsblk_group_partitions.json", boot: str = "/dev/sdb"):
    return parse_lsblk_json(_load(name), boot_path=boot)


def _wizard(result=None):
    discovery = result or _grouped()
    wiz = Wizard(discovery, DryRunRunner(), dry_run=True)
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    return wiz


def test_demo_happy_nests_partitions_and_keeps_loop_standalone():
    result = discovery_for_scenario("happy")
    selectable = {d.path for d in selectable_disks(result)}
    assert selectable == {"/dev/nvme0n1", "/dev/sda", "/dev/sdd"}
    others = other_devices(result)
    assert [d.path for d in others] == ["/dev/loop0"]
    assert others[0].kind_label == "Loop device"
    assert not others[0].parent_path
    text = full_text(others)
    assert "Loop device" in text or "unsupported device" in text
    other_paths = {d.path for d in others}
    for path in (
        "/dev/sdb1",
        "/dev/nvme0n1p1",
        "/dev/nvme0n1p2",
        "/dev/sda1",
        "/dev/sdd1",
    ):
        assert path not in other_paths
    nvme = nested_under("/dev/nvme0n1", result.excluded)
    assert [c.path for c in nvme] == ["/dev/nvme0n1p1", "/dev/nvme0n1p2"]
    assert all(c.kind_label == "Partition" for c in nvme)
    boot_parts = nested_under("/dev/sdb", result.excluded)
    assert [c.path for c in boot_parts] == ["/dev/sdb1"]
    assert "BEAMO_WIPE" in nested_heading(boot_parts[0])


def test_sata_nvme_usb_and_bridge_nest_under_parent():
    result = _grouped()
    sata = nested_under("/dev/sda", result.excluded)
    assert [c.path for c in sata] == [
        "/dev/sda1",
        "/dev/sda2",
        "/dev/mapper/cryptroot",
    ]
    assert [c.kind_label for c in sata] == [
        "Partition",
        "Partition",
        "Encrypted volume",
    ]
    assert "EFI" in nested_heading(sata[0])
    nvme = nested_under("/dev/nvme0n1", result.excluded)
    assert len(nvme) == 8
    assert [c.path for c in nvme][-1] == "/dev/nvme0n1p8"
    assert all(c.kind_label == "Partition" for c in nvme)
    usb = nested_under("/dev/sdd", result.excluded)
    assert [c.path for c in usb] == ["/dev/sdd1"]
    assert "PHOTOS" in nested_heading(usb[0])
    bridge = nested_under("/dev/sdc", result.excluded)
    assert [c.path for c in bridge] == ["/dev/sdc1"]
    assert "BACKUP" in nested_heading(bridge[0])
    parent = next(d for d in result.disks if d.path == "/dev/sdc")
    assert parent.serial == "BRIDGE001"
    assert parent.bus == "SATA"


def test_flat_pkname_chain_nests_mapper_under_disk():
    result = _grouped()
    kids = nested_under("/dev/sde", result.excluded)
    assert [c.path for c in kids] == ["/dev/sde1", "/dev/mapper/cryptflat"]
    assert kids[0].kind_label == "Partition"
    assert kids[1].kind_label == "Encrypted volume"
    assert "vault" in nested_heading(kids[1])
    assert "/dev/sde1" not in {d.path for d in other_devices(result)}
    assert "/dev/mapper/cryptflat" not in {d.path for d in other_devices(result)}


def test_loop_optical_and_orphan_stay_honest_standalone():
    result = _grouped()
    others = other_devices(result)
    paths = [d.path for d in others]
    assert "/dev/loop0" in paths
    assert "/dev/sr0" in paths
    assert "/dev/mystery1" in paths
    orphan = next(d for d in others if d.path == "/dev/mystery1")
    assert not orphan.parent_path
    assert orphan.kind_label == "Partition"
    assert "ORPHAN" in nested_heading(orphan)
    assert "unsupported device" in orphan.reasons
    optical = next(d for d in others if d.path == "/dev/sr0")
    assert optical.kind_label == "Optical disc"
    assert not optical.parent_path
    text = full_text(others)
    assert "ORPHAN" in text
    assert "Loop device" in text or "/dev/loop0" in {d.path for d in others}


def test_missing_parent_is_not_invented_from_kernel_name():
    payload = {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo Wipe",
                "serial": "BEAMOUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                        "size": 15500000000,
                    }
                ],
            },
            {
                "name": "sda1",
                "path": "/dev/sda1",
                "size": 1000000000,
                "type": "part",
                "label": "STRAY",
            },
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    stray = next(d for d in result.excluded if d.path == "/dev/sda1")
    assert stray.parent_path == ""
    assert stray.path in {d.path for d in other_devices(result)}
    assert nested_under("/dev/sda", result.excluded) == ()


def test_ineligible_parent_keeps_children_and_identity():
    result = _grouped()
    others = other_devices(result)
    mounted = next(d for d in others if d.path == "/dev/sdf")
    assert "MOUNTED001" in mounted.identity
    assert "Mounted Disk" in mounted.identity
    assert "mounted or in use" in mounted.reasons
    assert [c.path for c in mounted.children] == ["/dev/sdf1"]
    assert "FILES" in nested_heading(mounted.children[0])
    text = full_text(others)
    parent_at = text.index("MOUNTED001")
    child_at = text.index("FILES")
    assert parent_at < child_at
    assert "/dev/sdf1" not in {d.path for d in others}


def test_parent_identity_stays_on_parent_card():
    wiz = _wizard()
    sata = next(d for d in wiz.selectable if d.path == "/dev/sda")
    view = wiz.disk_view(sata)
    assert view.title.startswith("WDC")
    assert "1000" in view.capacity or "1000" in sata.size_gb_label
    assert view.id_value == "WD-WCC6Y1234567"
    kids = wiz.nested_components(sata)
    assert kids
    nest = card_nesting_text(kids)
    assert NESTED_INTRO in nest
    assert "WD-WCC6Y1234567" not in nest
    assert "Partition" in nest
    assert "Encrypted volume" in nest
    assert "unsupported device" not in nest
    assert "/dev/" not in nest


def test_eligibility_unchanged_for_nested_and_boot():
    wiz = _wizard()
    assert wiz.screen == Screen.PICK
    selectable = [d.path for d in wiz.selectable]
    assert "/dev/sda" in selectable
    assert "/dev/nvme0n1" in selectable
    assert "/dev/sdb" not in selectable
    forbidden = [
        "/dev/sdb",
        "/dev/sdb1",
        "/dev/sda1",
        "/dev/mapper/cryptroot",
        "/dev/loop0",
        "/dev/sr0",
        "/dev/mystery1",
        "/dev/sdf",
        "/dev/sdf1",
        "/dev/nvme0n1p3",
    ]
    for path in forbidden:
        wiz.select_disk(path)
        assert wiz.selected is None
        assert wiz.screen == Screen.PICK
    wiz.select_disk("/dev/sda")
    assert wiz.selected is not None and wiz.selected.path == "/dev/sda"
    assert not wiz.runner.started


def test_boot_fail_closed_hides_nested_inventory():
    wiz = _wizard()
    disk = wiz.selectable[0]
    first = wiz.nested_components(disk)
    assert first
    wiz.discovery = replace(wiz.discovery, boot_identified=False)
    assert wiz.other_devices == ()
    assert wiz.nested_components(disk) == ()
    assert wiz.protected_boot is None


def test_plain_console_nests_unnumbered_and_keeps_numbers_for_disks(monkeypatch, capsys):
    wiz = _wizard()
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    assert "Eligible disks" in text
    assert "[1]" in text
    eligible = text[text.index("Eligible disks"):]
    sda = eligible.index("WDC WD10EZEX")
    nest = eligible.index(NESTED_INTRO, sda)
    chunk = eligible[nest:nest + 500]
    assert "Partition" in chunk
    assert "Encrypted volume" in chunk
    assert "EFI" in chunk
    assert "[2]" in text
    assert TITLE in text
    assert "ORPHAN" in text
    assert not wiz.runner.started
    assert wiz.selected is None


def test_curses_pick_block_includes_nested_lines():
    wiz = _wizard()
    blocks = console._pick_blocks(wiz, 80)
    sata = next(block for disk, block in blocks if disk.path == "/dev/sda")
    joined = "\n".join(sata)
    assert NESTED_INTRO in joined
    assert "Partition" in joined
    assert "Encrypted volume" in joined
    nvme = next(block for disk, block in blocks if disk.path == "/dev/nvme0n1")
    assert sum(1 for line in nvme if "Partition" in line) == 8


def test_gallery_mirrors_picker_nesting():
    html = gallery_html()
    assert NESTED_INTRO in html
    assert "nested-intro" in html
    assert '"heading": "Partition' in html
    result = discovery_for_scenario("happy")
    text = full_text(other_devices(result))
    assert "nvme0n1p1" not in text
    assert "BEAMO_WIPE" not in text
    assert any(d.path == "/dev/loop0" for d in other_devices(result))


def test_adversarial_partitioned_fixture_nests_without_changing_targets():
    result = _grouped("lsblk_adversarial_partitioned.json")
    assert {d.path for d in selectable_disks(result)} == {
        "/dev/sda",
        "/dev/nvme0n1",
        "/dev/mmcblk0",
    }
    assert [c.path for c in nested_under("/dev/sda", result.excluded)] == [
        "/dev/sda1",
        "/dev/sda2",
    ]
    others = other_devices(result)
    assert "/dev/sda1" not in {d.path for d in others}
    assert "/dev/sdb1" not in {d.path for d in others}


@pytest.mark.parametrize(
    "path",
    ["/dev/sda1", "/dev/nvme0n1p1", "/dev/mapper/cryptroot", "/dev/loop0"],
)
def test_nested_paths_never_enter_selectable(path):
    result = _grouped()
    assert path not in {d.path for d in selectable_disks(result)}
    assert path not in {d.path for d in result.selectable}


def test_usb_sata_bridge_fixture_nests_partition():
    result = parse_lsblk_json(_load("lsblk_sata_bridge.json"), boot_path="/dev/sdb")
    kids = nested_under("/dev/sdb", result.excluded)
    assert [c.path for c in kids] == ["/dev/sdb1"]
    leftover = nested_under("/dev/sda", result.excluded)
    assert [c.path for c in leftover] == ["/dev/sda1"]


def test_tk_nested_rows_are_not_independent_targets():
    tk = pytest.importorskip("tkinter")
    try:
        from beamo_wipe.ui.tk_wizard import TkWizard
    except ImportError:
        pytest.skip("tkinter wizard unavailable")
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no display: {exc}")

    from test_tk_runtime import WINDOW, _needs_display

    _needs_display()
    wiz = make_demo_wizard()
    app = TkWizard(wiz)
    app.root.geometry(f"{WINDOW[0]}x{WINDOW[1]}+40+40")
    try:
        wiz.skip_intro()
        wiz.accept_what()
        wiz.set_owner(True)
        wiz.continue_owner()
        app._draw()
        app.root.update()
        assert wiz.screen == Screen.PICK
        assert wiz.selected is None
        nested = []

        def visit(widget):
            if getattr(widget, "_beamo_nested", False):
                nested.append(widget)
            for child in widget.winfo_children():
                visit(child)

        visit(app.root)
        assert nested
        labels = []
        for frame in nested:
            def collect(widget):
                if isinstance(widget, tk.Label):
                    labels.append(str(widget.cget("text")))
                for child in widget.winfo_children():
                    collect(child)
            collect(frame)
        blob = "\n".join(labels)
        assert NESTED_INTRO in blob
        assert "Partition" in blob
        assert "BEAMO_WIPE" in blob
        nvme = next(d for d in wiz.selectable if d.path == "/dev/nvme0n1")
        wiz.select_disk("/dev/nvme0n1p1")
        assert wiz.selected is None
        app._click_disk(nvme.path)
        app.root.update()
        assert wiz.selected is not None and wiz.selected.path == nvme.path
        assert not wiz.runner.started
        reader_text = []

        def find_inventory(widget):
            if getattr(widget, "_beamo_inventory", False):
                reader_text.append(widget.get("1.0", "end-1c"))
            for child in widget.winfo_children():
                find_inventory(child)

        find_inventory(app.root)
        assert reader_text
        assert reader_text[0] == full_text(wiz.other_devices)
        assert "nvme0n1p1" not in reader_text[0]
        assert "BEAMO_WIPE" not in reader_text[0]
    finally:
        app._teardown()
