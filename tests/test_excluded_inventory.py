# SPDX-License-Identifier: GPL-3.0-or-later
"""Fake inventory remains display-only across discovery and console navigation."""

from dataclasses import replace

import pytest

from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.inventory import TITLE, full_text
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import Wizard


def node(name, **changes):
    data = dict(
        name=name,
        path=f"/dev/{name}",
        type="disk",
        size=1000000000,
        model="Same model",
        serial=name,
        ro=False,
        mountpoints=[],
        rota=None,
    )
    data.update(changes)
    return data


def inventory_wizard():
    payload = {
        "blockdevices": [
            node("sda"),
            node("sdb", mountpoints=["/run/live/medium"]),
            node("sdc", mountpoints=["/media/data"], ro=True),
            node("sdd", size=0),
            node("sde", size=None),
            node("loop0", type="loop"),
            node("sdf", mountpoints=["/"]),
            node("sdg", type="raid1"),
            node("", path="", size=None),
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    wiz = Wizard(result, DryRunRunner(), dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    return wiz


def test_complete_excluded_inventory_does_not_add_targets():
    wiz = inventory_wizard()
    assert [d.path for d in wiz.selectable] == ["/dev/sda"]
    assert len(wiz.other_devices) == 8
    text = full_text(wiz.other_devices)
    for reason in (
        "boot or system protected",
        "mounted or in use",
        "read-only",
        "zero capacity",
        "capacity could not be confirmed",
        "unsupported device",
        "identity could not be confirmed",
    ):
        assert reason in text
    mounted = next(d for d in wiz.other_devices if "/dev/sdc" in d.identity)
    assert mounted.reasons == ("mounted or in use", "read-only")
    for path in ("/dev/sdb", "/dev/sdc", "/dev/sdd", "/dev/loop0", "/dev/sdf"):
        wiz.select_disk(path)
        wiz.continue_pick()
        assert wiz.selected is None and wiz.screen == Screen.PICK
    assert not wiz.runner.started


def test_blocked_boot_hides_inventory_and_refresh_replaces_it():
    wiz = inventory_wizard()
    first = wiz.discovery
    wiz.discovery = replace(first, boot_identified=False)
    assert not wiz.other_devices and not wiz.selectable
    wiz.discovery = parse_lsblk_json(
        {"blockdevices": [node("sdb")]}, boot_path="/dev/sdb"
    )
    wiz._enter_pick()
    assert wiz.screen == Screen.PICK_EMPTY
    assert len(wiz.other_devices) == 1
    assert "/dev/sdc" not in full_text(wiz.other_devices)


def test_plain_console_has_distinct_unnumbered_inventory(monkeypatch, capsys):
    wiz = inventory_wizard()
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    assert TITLE in text
    assert text.index("Eligible disks") < text.index("[1]")
    for device in wiz.other_devices:
        assert device.explanation in text
    assert "[2]" not in text
    assert not wiz.runner.started


@pytest.mark.parametrize("screen", [Screen.PICK, Screen.PICK_EMPTY])
def test_curses_80x24_inventory_keys_cannot_select_or_continue(monkeypatch, screen):
    wiz = inventory_wizard()
    wiz.screen = screen
    keys = iter([ord("o"), 10, ord("1"), console.curses.KEY_NPAGE, 27])
    frames = []

    class Terminal:
        def erase(self):
            self.rows = {}

        def getmaxyx(self):
            return (24, 80)

        def addstr(self, y, x, text, attr=0):
            assert 0 <= y < 24 and len(text) < 80
            self.rows[y] = text

        def getch(self):
            frames.append(" ".join(self.rows.values()))
            assert wiz.screen == screen and wiz.selected is None
            try:
                return next(keys)
            except StopIteration:
                wiz.wants_shutdown = True
                return -1

        def __getattr__(self, name):
            return lambda *args: None

    monkeypatch.setattr(console.curses, "curs_set", lambda *a: None)
    monkeypatch.setattr(console.curses, "use_default_colors", lambda *a: None)
    console._loop(Terminal(), wiz)
    assert any("Read only." in text for text in frames)
    assert any("Cannot erase:" in text for text in frames)
    assert not wiz.runner.started
