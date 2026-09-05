# SPDX-License-Identifier: GPL-3.0-or-later
"""Atomic refresh with fake discovery and deterministic concurrency barriers."""

from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import DiscoveryResult, MethodId, Screen


@pytest.mark.parametrize(
    "change", ["unchanged", "added", "removed", "renamed", "boot_changed", "invalid"]
)
def test_refresh_rereads_fake_json_and_reidentifies_boot(change, tmp_path, monkeypatch):
    from beamo_wipe.app import _build_wizard, _parser

    monkeypatch.setattr("beamo_wipe.app.running_on_live_usb", lambda: False)
    monkeypatch.delenv("BEAMO_WIPE_BOOT_DEVICE", raising=False)
    payload = json.loads(
        (Path(__file__).parent / "fixtures/lsblk_same_size.json").read_text()
    )
    source = tmp_path / "disks.json"
    source.write_text(json.dumps(payload))
    wiz = _build_wizard(_parser().parse_args(["--lsblk-json", str(source)]))
    assert wiz.discovery.boot.path == "/dev/sdb"
    nodes = payload["blockdevices"]
    if change == "added":
        nodes.append({**nodes[1], "name": "sdz", "path": "/dev/sdz", "serial": "NEW"})
    elif change == "removed":
        nodes.pop(1)
    elif change == "renamed":
        nodes[1].update(name="sdz", path="/dev/sdz")
    elif change == "boot_changed":
        nodes[0].update(name="sdy", path="/dev/sdy")
        nodes[0]["children"][0].update(name="sdy1", path="/dev/sdy1")
    source.write_text("invalid JSON" if change == "invalid" else json.dumps(payload))
    wiz.skip_splash()
    assert wiz.refresh_disks()
    if change == "invalid":
        assert wiz.screen == Screen.PICK_BLOCKED and not wiz.selectable
    else:
        assert wiz.screen == Screen.WHAT
        assert wiz.discovery.boot.path == (
            "/dev/sdy" if change == "boot_changed" else "/dev/sdb"
        )
        assert {disk.path for disk in wiz.selectable} == {
            node["path"] for node in nodes[1:]
        }
    assert wiz.selected is None and not wiz.owner_ok and not wiz.confirm_input


def authorized():
    wiz = make_demo_wizard()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.set_method(MethodId.QUICK_ZERO)
    wiz.continue_method()
    wiz._erase_until = 0
    return wiz


@pytest.mark.parametrize(
    "change", ["unchanged", "added", "removed", "renamed", "boot_changed"]
)
def test_refresh_requires_every_authorization_again(change):
    wiz = authorized()
    old = wiz.discovery
    disks = list(old.disks)
    targets = list(old.selectable)
    boot = old.boot
    if change == "added":
        extra = replace(targets[0], name="sdz", path="/dev/sdz", serial="ADDED")
        disks.append(extra)
        targets.append(extra)
    if change == "removed":
        removed = targets.pop(0)
        disks.remove(removed)
    if change == "renamed":
        renamed = replace(targets[0], path="/dev/sdz", name="sdz")
        disks[disks.index(targets[0])] = renamed
        targets[0] = renamed
    if change == "boot_changed":
        boot = replace(old.boot, name="sdy", path="/dev/sdy", serial="NEWBOOT")
        disks[disks.index(old.boot)] = boot
    fresh = replace(
        old, disks=tuple(disks), selectable=tuple(targets), boot=boot, excluded=()
    )
    calls = []
    wiz._rediscover = lambda: calls.append(True) or fresh
    assert wiz.refresh_disks()
    assert calls == [True] and wiz.discovery is fresh
    assert wiz.screen == Screen.WHAT and not wiz.owner_ok
    assert wiz.selected is None and wiz.confirm_input == ""
    assert wiz.method == MethodId.EVERYDAY and wiz._erase_until is None
    wiz.confirm_erase()
    wiz.back()
    assert not wiz.runner.started
    wiz.accept_what()
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.selected is None
    if targets:
        wiz.select_disk(targets[0].path)
        wiz.continue_pick()
        wiz.continue_confirm()
        assert wiz.screen == Screen.CONFIRM
        wiz.set_confirm_input(wiz.confirm.token)
        wiz.continue_confirm()
        wiz.continue_method()
        assert not wiz.erase_enabled


@pytest.mark.parametrize(
    "bad", [None, {}, DiscoveryResult(), RuntimeError("fake failure")]
)
def test_refresh_failure_never_retains_stale_targets(bad):
    wiz = authorized()

    def discover():
        if isinstance(bad, Exception):
            raise bad
        return bad

    wiz._rediscover = discover
    assert wiz.refresh_disks()
    assert wiz.screen == Screen.PICK_BLOCKED
    assert not wiz.selectable and not wiz.other_devices and wiz.selected is None
    assert not wiz.owner_ok and not wiz.confirm_input and not wiz.erase_enabled


def test_refresh_claim_blocks_repeat_navigation_and_start():
    wiz = authorized()
    fresh = wiz.discovery
    entered, release = threading.Event(), threading.Event()
    calls = []

    def discover():
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return fresh

    wiz._rediscover = discover
    worker = threading.Thread(target=wiz.refresh_disks)
    worker.start()
    try:
        assert entered.wait(5)
        assert wiz.screen == Screen.REFRESHING and not wiz.selectable
        assert not wiz.refresh_disks()
        wiz.back()
        wiz.open_advanced()
        wiz.set_owner(True)
        wiz.confirm_erase()
        assert wiz.screen == Screen.REFRESHING and not wiz.owner_ok
        assert not wiz.runner.started
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and calls == [True]
    assert wiz.screen == Screen.WHAT and wiz.selected is None


def test_running_wipe_cannot_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz = authorized()
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    before = wiz.discovery
    wiz._rediscover = lambda: pytest.fail("refresh ran during erase")
    assert not wiz.refresh_disks()
    assert wiz.discovery is before and wiz.runner.started


def test_selection_already_in_flight_cannot_restore_stale_target(monkeypatch):
    import beamo_wipe.wizard as module

    wiz = authorized()
    wiz.screen = Screen.PICK
    target = wiz.selectable[0].path
    entered, release, refreshed = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    original = module.os.path.realpath

    def delayed(path, *args, **kwargs):
        if threading.current_thread().name == "fake-selection" and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(module.os.path, "realpath", delayed)
    selection = threading.Thread(
        target=lambda: wiz.select_disk(target), name="fake-selection"
    )
    refresh = threading.Thread(target=lambda: (wiz.refresh_disks(), refreshed.set()))
    selection.start()
    try:
        assert entered.wait(5)
        refresh.start()
        assert not refreshed.wait(0.05)
    finally:
        release.set()
        selection.join(5)
        if refresh.ident is not None:
            refresh.join(5)
    assert refreshed.is_set()
    assert wiz.selected is None and not wiz.owner_ok and not wiz.confirm_input
    assert wiz.screen == Screen.WHAT


@pytest.mark.parametrize(
    "screen",
    [Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE, Screen.ADVANCED, Screen.LIMITS],
)
def test_refresh_after_back_navigation_clears_token_and_method(screen):
    wiz = authorized()
    wiz.screen = screen
    wiz.back()
    assert wiz.refresh_disks()
    assert wiz.screen == Screen.WHAT
    assert wiz.selected is None and not wiz.confirm_input and not wiz.owner_ok
