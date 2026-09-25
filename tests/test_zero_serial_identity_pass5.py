# SPDX-License-Identifier: GPL-3.0-or-later
"""Zero-padded serials are placeholders, never owner confirmation IDs."""

from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.identity import SERIAL_NOT_REPORTED, present_disk
from beamo_wipe.inventory import comparison_entries
from beamo_wipe.models import DiscoveryResult, Disk, DiskKind, Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.safety import SafetyError, confirm_spec, disk_identity
from beamo_wipe.wizard import Wizard
from test_console_parity import _at_pick, _draw, replace_selectable


def _disk(name: str, *, serial: str, wwn: str = "") -> Disk:
    return Disk(
        path=f"/dev/{name}",
        name=name,
        model="Same model",
        serial=serial,
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
        wwn=wwn,
    )


@pytest.mark.parametrize(
    "serial", ["0", "00000000", " 00000000 ", "0x00000000", "0X00000000",
               "00:00:00:00", "0000-0000", "UNKNOWN", "N/A", "NONE",
               "not applicable", "no serial", "unspecified", "not specified"]
)
def test_zero_serial_cannot_distinguish_same_size_disks(serial: str) -> None:
    padded = _disk("sda", serial=serial)
    missing = _disk("sdb", serial="")
    for disk in (padded, missing):
        with pytest.raises(SafetyError, match="too similar"):
            confirm_spec(disk, (padded, missing))
        view = present_disk(disk, (padded, missing), compare_serials=True)
        assert not view.confirmable
        assert view.id_value == SERIAL_NOT_REPORTED
        assert view.missing_note
        assert not view.comparison_note


def test_zero_serial_uses_hardware_id_when_it_is_unique() -> None:
    padded = _disk("sda", serial="00000000", wwn="0x5002538e00000001")
    missing = _disk("sdb", serial="", wwn="0x5002538e00000002")
    spec = confirm_spec(padded, (padded, missing))
    view = present_disk(padded, (padded, missing))
    assert spec.identity_field == "wwn"
    assert view.id_label == "Hardware ID"
    assert view.id_value == padded.wwn
    assert view.confirmable
    # Keep the raw serial in the rediscovery identity so a later change fails closed.
    assert disk_identity(padded) != disk_identity(replace(padded, serial=""))


@pytest.mark.parametrize("wwn", ["00:00:00:00", "0000-0000", "UNKNOWN", "N/A"])
def test_separator_padded_zero_wwn_cannot_disambiguate_disks(wwn: str) -> None:
    padded = _disk("sda", serial="", wwn=wwn)
    missing = _disk("sdb", serial="")
    with pytest.raises(SafetyError, match="too similar"):
        confirm_spec(padded, (padded, missing))


def test_wizard_cannot_advance_with_zero_serial_as_only_distinction() -> None:
    padded = _disk("sda", serial="00000000")
    missing = _disk("sdb", serial="")
    boot = replace(_disk("sdc", serial="BOOT-123"), is_boot=True,
                   size_bytes=16_000_000_000, size_gb_label="16", bus="USB")
    discovery = DiscoveryResult(
        disks=(padded, missing, boot),
        selectable=(padded, missing),
        boot=boot,
        boot_identified=True,
    )
    wizard = Wizard(discovery, DryRunRunner(), dry_run=True)
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(padded.path)
    wizard.continue_pick()
    assert wizard.screen == Screen.PICK
    assert wizard.confirm is None


def test_read_only_comparison_does_not_present_zero_padding_as_a_serial() -> None:
    padded = _disk("sda", serial="00000000", wwn="0x5002538e00000001")
    missing = _disk("sdb", serial="")
    entries = comparison_entries((padded, missing))
    assert "00000000" not in entries[0]
    assert f"Serial number: {SERIAL_NOT_REPORTED}" in entries[0]
    assert "Hardware ID: 0x5002538e00000001" in entries[0]


def test_console_keeps_same_size_warning_with_missing_serial(monkeypatch) -> None:
    wizard = _at_pick()
    first = next(d for d in wizard.selectable if d.path == "/dev/nvme0n1")
    other = next(d for d in wizard.selectable if d.path == "/dev/sdd")
    wizard.discovery = replace_selectable(
        wizard, (replace(first, serial="00000000"), replace(other, serial=""))
    )
    shown, packed, _term = _draw(monkeypatch, wizard, h=20, w=80)
    assert SERIAL_NOT_REPORTED in packed
    assert C.SAME_SIZE_HINT in shown
    assert wizard.inventory_count in shown
