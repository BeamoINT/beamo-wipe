"""Disk identity regressions; synthetic inventory only."""

from dataclasses import replace

import pytest

from beamo_wipe.identity import present_disk
from beamo_wipe.models import Disk, DiskKind, DiscoveryResult, Screen
from beamo_wipe.safety import SafetyError, confirm_spec, token_matches


def fake_disk(name="sda", **changes):
    disk = Disk(
        path=f"/dev/{name}", name=name, model="Fixture SSD", serial="",
        size_bytes=500_000_000_000, size_gb_label="500", kind=DiskKind.SSD,
        bus="SATA", label="",
    )
    return replace(disk, **changes)


def test_confirmation_tokens_disambiguate_serial_and_hardware_id_suffixes():
    disks = [
        fake_disk("sda", serial="SERIAL1111"),
        fake_disk("sdc", wwn="WWN1111"),
    ]
    tokens = [confirm_spec(disk, disks).token.casefold() for disk in disks]
    assert len(set(tokens)) == len(disks), tokens


def test_duplicate_serials_show_the_unique_hardware_id_used_for_confirmation():
    disks = [
        fake_disk("sda", serial="DUPLICATE", wwn="WWN-A"),
        fake_disk("sdc", serial="DUPLICATE", wwn="WWN-B"),
    ]
    views = [present_disk(disk, disks) for disk in disks]
    assert all(view.confirmable for view in views)
    assert views[0].announcement != views[1].announcement
    for disk, view in zip(disks, views):
        assert disk.wwn in view.announcement
        assert view.id_label == "Hardware ID"
        assert "did not report a serial" not in view.announcement
        assert confirm_spec(disk, disks).identity_field == "wwn"


@pytest.mark.parametrize("serial,wwn", [
    ("SERIAL1111", "WWN1111"),  # suffix versus suffix; full values differ
    ("SERIALabcd", "WWNABCD"),  # matches are case-insensitive
])
def test_mixed_identifiers_cannot_authorize_the_other_disk(serial, wwn):
    disks = [fake_disk("sda", serial=serial), fake_disk("sdc", wwn=wwn)]
    specs = [confirm_spec(disk, disks) for disk in disks]
    assert specs[0].identity_field == "serial"
    assert specs[1].identity_field == "wwn"
    assert specs[0].token.casefold() != specs[1].token.casefold()
    for index, spec in enumerate(specs):
        assert token_matches(spec.token.swapcase(), spec)
        assert not token_matches(specs[1 - index].token, spec)
        assert confirm_spec(disks[index], list(reversed(disks))) == spec


@pytest.mark.parametrize("serial,wwn,blocked", [
    ("1111", "WWN1111", 0),  # full serial is the other disk's suffix
    ("SERIAL1111", "1111", 1),  # full hardware ID is the other disk's suffix
])
def test_shared_suffix_value_is_not_a_confirmation_token(serial, wwn, blocked):
    disks = [fake_disk("sda", serial=serial), fake_disk("sdc", wwn=wwn)]
    with pytest.raises(SafetyError, match="too similar"):
        confirm_spec(disks[blocked], disks)
    spec = confirm_spec(disks[1 - blocked], disks)
    assert spec.token.casefold() != "1111"
    assert not token_matches("1111", spec)


@pytest.mark.parametrize("left,right", [
    ({"serial": "SAME"}, {"wwn": "same"}),
    ({"serial": "SAME", "wwn": "WWN"}, {"serial": "same", "wwn": "wwn"}),
    ({}, {}),
])
def test_identical_or_missing_identifiers_remain_fail_closed(left, right):
    disks = [fake_disk("sda", **left), fake_disk("sdc", **right)]
    for disk in disks:
        with pytest.raises(SafetyError, match="too similar"):
            confirm_spec(disk, disks)
        assert not present_disk(disk, disks).confirmable


def _duplicate_serial_wizard():
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard

    boot = fake_disk("sdb", serial="BOOT", size_bytes=16_000_000_000, size_gb_label="16", is_boot=True)
    disks = (fake_disk("sda", serial="DUPLICATE", wwn="WWN-A"), fake_disk("sdc", serial="DUPLICATE", wwn="WWN-B"))
    result = DiscoveryResult(disks=(boot, *disks), selectable=disks, boot=boot, boot_identified=True)
    wiz = Wizard(result, DryRunRunner(duration_s=0.5), dry_run=True)
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(disks[0].path)
    wiz.continue_pick()
    return wiz


def test_duplicate_serial_wizard_shows_confirmed_id_through_review_and_retry():
    wiz = _duplicate_serial_wizard()
    assert wiz.screen == Screen.CONFIRM
    assert wiz.selected.wwn in wiz.disk_view().announcement
    assert wiz.confirm.token in wiz.confirm.prompt
    wiz.set_confirm_input(confirm_spec(wiz.selectable[1], wiz.listed_disks).token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.CONFIRM
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.selected.wwn in wiz.erase_label()
    wiz.back()
    wiz.back()
    assert wiz.screen == Screen.CONFIRM
    assert wiz.selected.wwn in wiz.disk_view().announcement
    assert not wiz.runner.started


def test_duplicate_serial_console_confirmation_renders_id_and_token(monkeypatch, capsys):
    from beamo_wipe.ui import console_wizard

    wiz = _duplicate_serial_wizard()

    class Rendered(Exception):
        pass

    def stop_at_input(*args):
        raise Rendered

    monkeypatch.setattr(console_wizard, "_answer", stop_at_input)
    with pytest.raises(Rendered):
        console_wizard._plain_loop_body(wiz)
    output = capsys.readouterr().out
    assert wiz.selected.wwn in output
    assert "Hardware ID" in output
    assert wiz.confirm.prompt in output


def test_duplicate_serial_gallery_keeps_confirm_and_review_id_consistent(monkeypatch):
    from beamo_wipe import gallery

    wiz = _duplicate_serial_wizard()
    monkeypatch.setattr(gallery, "discovery_for_scenario", lambda _: wiz.discovery)
    payload = gallery._disks_payload()
    target = next(row for row in payload if row["path"] == wiz.selected.path)
    assert target["serial"] == wiz.selected.wwn
    assert target["idLabel"] == "Hardware ID"
    assert target["token"] == wiz.confirm.token
    assert wiz.selected.wwn in target["eraseLabel"]
