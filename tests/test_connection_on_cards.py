# SPDX-License-Identifier: GPL-3.0-or-later
"""Observed connection type is on disk cards without Show more.

Fake lsblk only. Never nwipe a real disk. Selection eligibility is unchanged.
"""

from __future__ import annotations

from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.gallery import gallery_html
from beamo_wipe.identity import (
    CONNECTION_BRIDGE_NOTE,
    CONNECTION_LABEL,
    CONNECTION_OTHER,
    CONNECTION_UNKNOWN,
    connection_label,
    present_disk,
)
from beamo_wipe.inventory import comparison_text
from beamo_wipe.models import Disk, DiskKind, Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.safety import listed_disks, selectable_disks
from beamo_wipe.wizard import Wizard
from test_excluded_inventory import node


LOCATION_GUESSES = ("internal", "external", "inside the computer", "enclosure")


def _result(payload, boot="/dev/sdb"):
    return parse_lsblk_json({"blockdevices": payload}, boot_path=boot)


def _disk(**changes) -> Disk:
    data = dict(
        path="/dev/sda",
        name="sda",
        model="Example",
        serial="SERIAL1",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    data.update(changes)
    return Disk(**data)


def test_direct_usb_sata_nvme_are_labeled_on_the_card_without_show_more():
    result = discovery_for_scenario("happy")
    listed = listed_disks(result)
    by_bus = {present_disk(disk, listed).connection: disk for disk in listed}
    assert {"USB", "SATA", "NVMe"} <= set(by_bus)
    for disk in listed:
        view = present_disk(disk, listed)
        assert f"{CONNECTION_LABEL}: {view.connection}" in view.announcement
        assert view.connection in {"USB", "SATA", "NVMe"}
        assert "internal" not in view.connection.casefold()
        assert "external" not in view.connection.casefold()
        assert disk.path not in view.announcement


def test_missing_and_other_connections_stay_honest():
    missing = present_disk(_disk(bus=""))
    other = present_disk(_disk(bus="other", path="/dev/vda", name="vda"))
    iscsi = present_disk(_disk(bus="ISCSI", path="/dev/sde", name="sde"))
    assert missing.connection == CONNECTION_UNKNOWN
    assert other.connection == CONNECTION_OTHER
    assert iscsi.connection == CONNECTION_OTHER
    assert f"{CONNECTION_LABEL}: {CONNECTION_UNKNOWN}" in missing.announcement
    assert "internal" not in missing.connection.casefold()


def test_contradictory_nvme_name_with_usb_tran_uses_observed_usb():
    result = _result([
        node("nvme0n1", tran="usb", rota=False, serial="USBNVME1"),
        node("sdb", tran="usb", mountpoints=["/run/live/medium"]),
    ])
    disk = next(d for d in result.disks if d.path == "/dev/nvme0n1")
    view = present_disk(disk)
    assert disk.bus == "USB"
    assert view.connection == "USB"
    assert view.kind_chip == "SSD"
    assert view.connection != "NVMe"
    assert "NVMe" not in view.connection


def test_bridged_sata_hotplug_does_not_guess_location():
    result = _result([
        node("sda", tran="sata", rm=True, hotplug=True, model="Internal SATA", serial="INT001"),
        node("sdb", tran="usb", mountpoints=["/run/live/medium"]),
        node("sdc", tran="usb", rm=True, hotplug=True, serial="USBHDD001"),
    ])
    sata = next(d for d in result.disks if d.path == "/dev/sda")
    usb = next(d for d in result.disks if d.path == "/dev/sdc")
    sata_view = present_disk(sata)
    usb_view = present_disk(usb)
    assert sata.hotplug and usb.hotplug
    assert sata_view.connection == "SATA"
    assert sata_view.connection_note == CONNECTION_BRIDGE_NOTE
    assert "internal" not in sata_view.connection.casefold()
    assert "enclosure" in sata_view.connection_note.casefold()
    assert CONNECTION_BRIDGE_NOTE in sata_view.announcement
    assert usb_view.connection == "USB"
    assert not usb_view.connection_note
    before = {d.path for d in selectable_disks(result)}
    Wizard(result, DryRunRunner(), dry_run=True)
    assert {d.path for d in selectable_disks(result)} == before
    assert "/dev/sdb" not in before
    assert "/dev/sda" in before and "/dev/sdc" in before


def test_direct_sata_without_hotplug_has_no_bridge_note():
    view = present_disk(_disk(bus="SATA", hotplug=False))
    assert view.connection == "SATA"
    assert not view.connection_note
    for guess in LOCATION_GUESSES:
        assert guess not in view.connection.casefold()


def test_long_connection_note_is_preserved_for_wrapping():
    view = present_disk(_disk(bus="SATA", hotplug=True, model="LONGMODEL" * 12))
    assert CONNECTION_BRIDGE_NOTE in view.announcement
    assert CONNECTION_BRIDGE_NOTE in view.notes
    assert "LONGMODEL" in view.title


def test_gallery_and_comparison_label_connection_without_show_more():
    html = gallery_html()
    assert CONNECTION_LABEL in html
    assert '"connectionLabel"' in html or CONNECTION_LABEL in html
    assert "showMore ? d.connection" not in html
    result = discovery_for_scenario("happy")
    text = comparison_text(result.selectable, peers=listed_disks(result))
    assert f"{CONNECTION_LABEL}: NVMe" in text
    assert f"{CONNECTION_LABEL}: SATA" in text


def test_plain_console_shows_connection_without_a_more_command(monkeypatch, capsys):
    from beamo_wipe.ui import console_wizard as console

    wiz = make_demo_wizard()
    wiz.screen = Screen.PICK
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    output = capsys.readouterr().out
    assert "USB" in output
    assert "NVMe" in output
    assert "SATA" in output
    assert "Show more" not in output
    assert not wiz.runner.started


def test_connection_label_never_uses_kernel_name():
    disk = _disk(path="/dev/nvme0n1", name="nvme0n1", bus="")
    assert "nvme" not in connection_label(disk).casefold()
    assert connection_label(disk) == CONNECTION_UNKNOWN
