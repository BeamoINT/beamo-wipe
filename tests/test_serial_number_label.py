# SPDX-License-Identifier: GPL-3.0-or-later
"""Displayed serials are prefixed with Serial number. Fake lsblk only."""

from __future__ import annotations

from beamo_wipe import copy as C
from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.gallery import gallery_html
from beamo_wipe.identity import (
    HARDWARE_ID_LABEL,
    SERIAL_LABEL,
    SERIAL_NOT_REPORTED,
    present_disk,
)
from beamo_wipe.inventory import comparison_text, full_text
from beamo_wipe.models import Disk, DiskKind, Screen
from beamo_wipe.safety import listed_disks
from beamo_wipe.ui import console_wizard as console


def _disk(**changes) -> Disk:
    data = dict(
        path="/dev/sda",
        name="sda",
        model="Example",
        serial="ABC123",
        size_bytes=256_000_000_000,
        size_gb_label="256",
        kind=DiskKind.SSD,
        bus="SATA",
        label="",
    )
    data.update(changes)
    return Disk(**data)


def test_shared_label_is_serial_number_not_bare_serial():
    assert SERIAL_LABEL == "Serial number"
    assert C.SERIAL_LABEL == SERIAL_LABEL
    assert SERIAL_LABEL != "Serial"


def test_present_serial_is_prefixed_in_announcement_and_compact_line():
    view = present_disk(_disk(serial="S4EVNX0N123456"))
    assert view.id_label == SERIAL_LABEL
    assert view.id_value == "S4EVNX0N123456"
    assert f"{SERIAL_LABEL}: S4EVNX0N123456" in view.announcement
    assert f"{SERIAL_LABEL} S4EVNX0N123456" in view.compact_line
    assert "Serial: S4EVNX0N123456" not in view.announcement


def test_absent_and_whitespace_serials_keep_the_serial_number_label():
    for serial in ("", "   ", "\t"):
        view = present_disk(_disk(serial=serial))
        assert view.id_label == SERIAL_LABEL
        assert view.id_value == SERIAL_NOT_REPORTED
        assert f"{SERIAL_LABEL}: {SERIAL_NOT_REPORTED}" in view.announcement
        assert "did not report a serial number" in view.missing_note


def test_duplicate_serials_keep_the_label_and_the_warning():
    result = discovery_for_scenario("happy")
    listed = listed_disks(result)
    first = listed[0]
    twin = _disk(
        path="/dev/sdz",
        name="sdz",
        model=first.model,
        serial=first.serial,
        size_bytes=first.size_bytes,
        size_gb_label=first.size_gb_label,
        kind=first.kind,
        bus=first.bus,
    )
    view = present_disk(first, (*listed, twin))
    assert view.id_label == SERIAL_LABEL
    assert view.id_value == first.serial
    assert view.duplicate_note
    assert f"{SERIAL_LABEL}: {first.serial}" in view.announcement


def test_non_ascii_and_long_serials_keep_the_prefix():
    serial = "시리얼-ΑΒΓΔ-" + "LONGSERIAL" * 8
    view = present_disk(_disk(serial=serial))
    assert view.id_label == SERIAL_LABEL
    assert view.id_value == serial
    assert f"{SERIAL_LABEL}: {serial}" in view.announcement
    assert serial in view.compact_line


def test_hardware_id_fallback_is_not_relabeled_as_serial_number():
    view = present_disk(_disk(serial="", wwn="0x5002538e00000001"))
    assert view.id_label == HARDWARE_ID_LABEL
    assert view.id_value == "0x5002538e00000001"
    assert SERIAL_LABEL not in f"{view.id_label}: {view.id_value}"
    assert f"{HARDWARE_ID_LABEL}: 0x5002538e00000001" in view.announcement


def test_gallery_comparison_inventory_and_console_use_serial_number():
    html = gallery_html()
    assert SERIAL_LABEL in html
    assert f'"serialLabel": "{SERIAL_LABEL}"' in html
    result = discovery_for_scenario("happy")
    listed = listed_disks(result)
    text = comparison_text(result.selectable, peers=listed)
    assert f"{SERIAL_LABEL}:" in text
    assert "Serial: S4EVNX0N123456" not in text
    from beamo_wipe.inventory import other_devices

    blob = full_text(other_devices(result))
    assert f"{SERIAL_LABEL}:" in blob


def test_plain_console_pick_and_empty_prefix_serials(monkeypatch, capsys):
    wiz = make_demo_wizard()
    wiz.screen = Screen.PICK
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    output = capsys.readouterr().out
    assert SERIAL_LABEL in output
    assert "S4EVNX0N123456" in output
    assert not wiz.runner.started


def test_review_progress_and_result_announcements_keep_the_prefix():
    wiz = make_demo_wizard()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    disk = wiz.selectable[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    view = wiz.disk_view()
    assert f"{SERIAL_LABEL}: {disk.serial}" in view.announcement
    for screen in (Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE, Screen.WORKING):
        wiz.screen = screen
        assert f"{SERIAL_LABEL}: {disk.serial}" in wiz.disk_view().announcement
    assert disk.path not in wiz.selectable or disk.path == wiz.selected.path
