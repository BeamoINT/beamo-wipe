# SPDX-License-Identifier: GPL-3.0-or-later
"""Protected boot presentation never supplies erase targets (fake disks only)."""
from dataclasses import replace

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


def test_confirmed_boot_has_separate_customer_identity():
    w = make_demo_wizard()
    assert w.protected_boot == w.discovery.boot
    assert "protected" in w.protected_boot_text
    assert "cannot be erased" in w.protected_boot_text
    assert w.discovery.boot.serial in w.protected_boot_text
    assert w.discovery.boot.path not in {d.path for d in w.selectable}
    assert w.discovery.boot.path not in {d.path for d in w.other_devices}


@pytest.mark.parametrize("changes", [dict(boot_identified=False), dict(error="Conflicting boot media"), dict(boot=None)])
def test_unconfirmed_boot_never_gets_reassuring_card(changes):
    w = make_demo_wizard()
    w.discovery = replace(w.discovery, **changes)
    assert w.protected_boot is None
    assert not w.protected_boot_text
    assert not w.selectable


def test_plain_console_boot_is_unnumbered(monkeypatch, capsys):
    w = make_demo_wizard()
    w.screen = Screen.PICK
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(w)
    output = capsys.readouterr().out
    assert w.protected_boot_text in output
    assert output.index(w.protected_boot_text) < output.index("Eligible disks")
    assert not w.runner.started


def test_multiple_usb_devices_and_boot_alias_stay_excluded():
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard
    from test_excluded_inventory import node
    result = parse_lsblk_json({"blockdevices": [
        node("sda", tran="usb"),
        node("sdb", tran="usb", wwn="boot-id", mountpoints=["/run/live/medium"]),
        node("sdc", tran="usb", wwn="boot-id"),
    ]}, boot_path="/dev/sdb")
    w = Wizard(result, DryRunRunner(), dry_run=True)
    assert w.protected_boot.path == "/dev/sdb"
    assert [d.path for d in w.selectable] == ["/dev/sda"]
    assert any(d.path == "/dev/sdc" for d in w.other_devices)
    w.screen = Screen.PICK
    for path in ("/dev/sdb", "/dev/sdc"):
        w.select_disk(path)
        assert w.selected is None
    assert not w.runner.started


def test_conflicting_boot_sources_fail_closed():
    from beamo_wipe.discover import discover
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard
    from test_excluded_inventory import node
    result = discover(lsblk_payload={"blockdevices": [
        node("sda", mountpoints=["/run/live/medium"]),
        node("sdb", mountpoints=["/lib/live/mount/medium"]),
    ]}, mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    w = Wizard(result, DryRunRunner(), dry_run=True)
    assert not w.selectable
    assert not w.protected_boot_text
