# SPDX-License-Identifier: GPL-3.0-or-later
"""Concise inventory count so owners can check expected hardware was found.

Fake lsblk and DryRunRunner only. Never nwipe a real disk.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.discover import parse_lsblk_json
from beamo_wipe.gallery import gallery_html
from beamo_wipe.inventory import count_summary, full_text, other_devices
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.safety import selectable_disks
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import Wizard
from test_excluded_inventory import node


HAPPY = "3 disks available to erase · Beamo USB protected · 1 other device not available"
EMPTY = "No disks available to erase · Beamo USB protected · 1 other device not available"
UNKNOWN = "Disk list could not be confirmed. No disk is available to erase."


def _wizard(payload, boot_path="/dev/sdb"):
    result = parse_lsblk_json({"blockdevices": payload}, boot_path=boot_path)
    return Wizard(result, DryRunRunner(), dry_run=True)


def test_happy_demo_counts_many_eligible_protected_usb_and_other_device():
    result = discovery_for_scenario("happy")
    assert len(selectable_disks(result)) == 3
    assert [d.path for d in other_devices(result)] == ["/dev/loop0"]
    assert count_summary(result) == HAPPY
    spoken = count_summary(result, spoken=True)
    assert spoken == (
        "3 disks available to erase. Beamo USB protected. "
        "1 other device not available."
    )
    assert "Choose one disk" not in HAPPY
    wiz = make_demo_wizard()
    assert wiz.inventory_count == HAPPY
    assert wiz.inventory_count_announcement == spoken


def test_empty_demo_uses_zero_plural_and_still_names_protected_usb():
    result = discovery_for_scenario("empty")
    assert selectable_disks(result) == ()
    assert count_summary(result) == EMPTY
    assert "0 disk" not in count_summary(result)
    assert count_summary(result, spoken=True).endswith("not available.")


def test_one_eligible_disk_uses_singular():
    wiz = _wizard([
        node("sda", tran="sata"),
        node("sdb", tran="usb", mountpoints=["/run/live/medium"]),
    ])
    text = count_summary(wiz.discovery)
    assert text == "1 disk available to erase · Beamo USB protected"
    assert "1 disks" not in text
    assert "other device" not in text


def test_two_eligible_disks_use_plural_without_other_devices():
    wiz = _wizard([
        node("sda", tran="sata"),
        node("sdc", tran="sata", serial="sdc"),
        node("sdb", tran="usb", mountpoints=["/run/live/medium"]),
    ])
    assert count_summary(wiz.discovery) == (
        "2 disks available to erase · Beamo USB protected"
    )


def test_optical_boot_media_uses_disc_wording():
    wiz = _wizard([
        node("sda", tran="sata"),
        node("sdb", tran="ata", mountpoints=["/run/live/medium"]),
    ])
    text = count_summary(wiz.discovery)
    assert "Beamo boot disc protected" in text
    assert "Beamo USB protected" not in text
    assert text.startswith("1 disk available to erase")


def test_many_excluded_devices_use_plural_and_keep_reasons_visible():
    wiz = _wizard([
        node("sda", tran="sata"),
        node("sdb", tran="usb", mountpoints=["/run/live/medium"]),
        node("sdc", mountpoints=["/media/data"], ro=True),
        node("loop0", type="loop"),
        node("sdd", size=0),
    ])
    text = count_summary(wiz.discovery)
    assert text == (
        "1 disk available to erase · Beamo USB protected · "
        "3 other devices not available"
    )
    reasons = full_text(wiz.other_devices)
    assert "mounted or in use" in reasons
    assert "unsupported device" in reasons
    assert "zero capacity" in reasons
    wiz.select_disk("/dev/sdb")
    wiz.select_disk("/dev/sdc")
    wiz.select_disk("/dev/loop0")
    assert wiz.selected is None
    assert not wiz.runner.started


def test_uncertain_excluded_device_is_named_in_the_summary():
    wiz = _wizard([
        node("sda", tran="sata"),
        node("sdb", tran="usb", mountpoints=["/run/live/medium"]),
        node("sde", size=None),
    ])
    text = count_summary(wiz.discovery)
    assert "1 disk available to erase" in text
    assert "Beamo USB protected" in text
    assert "1 other device not available" in text
    assert "Some devices could not be fully identified" in text
    assert "capacity could not be confirmed" in full_text(wiz.other_devices)
    spoken = count_summary(wiz.discovery, spoken=True)
    assert spoken.endswith("fully identified.")
    assert " · " not in spoken


@pytest.mark.parametrize(
    "changes",
    [
        dict(boot_identified=False),
        dict(error="Conflicting boot media"),
        dict(boot=None),
    ],
)
def test_unknown_discovery_never_claims_a_count_or_protected_usb(changes):
    result = replace(discovery_for_scenario("happy"), **changes)
    text = count_summary(result)
    spoken = count_summary(result, spoken=True)
    assert text == UNKNOWN
    assert spoken == UNKNOWN
    assert "available to erase" not in text.split(".")[0]
    assert "Beamo USB protected" not in text
    assert "0 disk" not in text
    assert "3 disks" not in text
    assert other_devices(result) == ()
    assert selectable_disks(result) == ()


def test_blocked_demo_is_the_unknown_summary():
    result = discovery_for_scenario("blocked")
    assert count_summary(result) == UNKNOWN
    wiz = make_demo_wizard(scenario="blocked")
    assert wiz.inventory_count == UNKNOWN
    assert wiz.inventory_count_announcement == UNKNOWN


def test_refresh_replaces_the_count_from_the_new_discovery():
    wiz = make_demo_wizard()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    assert wiz.inventory_count == HAPPY
    empty = discovery_for_scenario("empty")
    wiz._rediscover = lambda: empty
    assert wiz.refresh_disks()
    assert wiz.inventory_count == EMPTY
    assert wiz.selected is None
    blocked = discovery_for_scenario("blocked")
    wiz._rediscover = lambda: blocked
    assert wiz.refresh_disks()
    assert wiz.inventory_count == UNKNOWN
    assert wiz.selectable == ()
    assert not wiz.runner.started


def test_nested_partitions_do_not_inflate_the_other_device_count():
    result = discovery_for_scenario("happy")
    text = count_summary(result)
    assert "1 other device not available" in text
    assert "4 other" not in text
    assert "5 other" not in text
    blob = full_text(other_devices(result))
    assert "nvme0n1p1" not in blob
    assert "BEAMO_WIPE" not in blob


def test_gallery_uses_shared_summaries_not_a_local_js_count():
    html = gallery_html()
    for phrase in (
        "3 disks available to erase",
        "No disks available to erase",
        "Beamo USB protected",
        "1 other device not available",
        UNKNOWN,
    ):
        assert phrase in html
    assert "Choose one disk" not in html
    assert "selectable().length === 1" not in html
    assert 'role="status"' in html
    assert "inventoryCount" in html


def test_plain_console_prints_the_count_before_eligible_disks(monkeypatch, capsys):
    wiz = make_demo_wizard()
    wiz.screen = Screen.PICK
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    output = capsys.readouterr().out
    assert HAPPY in output
    assert output.index(HAPPY) < output.index("Eligible disks")
    assert not wiz.runner.started


def test_plain_console_empty_prints_zero_count(monkeypatch, capsys):
    wiz = make_demo_wizard(scenario="empty")
    wiz.screen = Screen.PICK_EMPTY
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    output = capsys.readouterr().out
    assert EMPTY in output
    assert "Beamo USB protected" in output


def test_curses_pick_shows_the_count(monkeypatch):
    from test_console_parity import _at_pick, _draw

    wiz = _at_pick()
    shown, _, _term = _draw(monkeypatch, wiz)
    assert "3 disks available to erase" in shown
    assert "Beamo USB protected" in shown
    assert "1 other device not available" in shown


@pytest.mark.parametrize(
    "scenario,screen,phrase",
    [
        ("happy", "pick", HAPPY),
        ("empty", "empty", EMPTY),
        ("blocked", "blocked", UNKNOWN),
    ],
)
@pytest.mark.parametrize("width", [1024, 390])
def test_browser_inventory_count_is_visible(tmp_path, scenario, screen, phrase, width):
    playwright = pytest.importorskip("playwright.sync_api")
    html = tmp_path / "index.html"
    html.write_text(gallery_html())
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True, args=["--no-sandbox"])
        except playwright.Error as exc:
            pytest.skip(f"Browser runtime unavailable: {exc}")
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.goto(html.as_uri() + f"#scenario={scenario}&s={screen}")
            status = page.locator(".inventory-count")
            assert status.count() == 1
            assert status.get_attribute("role") == "status"
            assert status.inner_text() == phrase
            assert status.evaluate("e => e.scrollWidth <= e.clientWidth + 2")
            if scenario == "happy":
                assert page.locator(".card.pickable").count() == 3
            elif scenario == "blocked":
                assert page.locator(".card.pickable").count() == 0
            assert "Choose one disk" not in page.locator("body").inner_text()
        finally:
            browser.close()


def test_helper_has_no_live_inventory_count():
    text = (Path(__file__).resolve().parents[1] / "helper" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "available to erase" not in text
    assert "inventory-count" not in text
    assert "Beamo USB protected" not in text
