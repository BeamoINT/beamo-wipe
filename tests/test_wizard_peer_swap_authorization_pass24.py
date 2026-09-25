# SPDX-License-Identifier: GPL-3.0-or-later
"""Final discovery must not reuse consent after a peer changes at one path."""

from dataclasses import replace

from beamo_wipe import copy as C
from beamo_wipe.demo import discovery_for_scenario
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


def _ready(initial, fresh):
    clock = Clock()
    runner = DryRunRunner(clock=clock)
    wizard = Wizard(initial, runner, clock=clock, dry_run=False, rediscover=lambda: fresh)
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(initial.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    assert wizard.screen == Screen.LAST_CHANCE
    clock.value = 6.0
    assert wizard.erase_enabled
    return wizard, runner


def _two_disk_inventory():
    base = discovery_for_scenario("happy")
    peer = replace(
        base.selectable[0], path="/dev/sde", name="sde", model="Peer A",
        serial="PEER-A", size_bytes=512_000_000_000, size_gb_label="512",
        layout_id="peer-a-layout",
    )
    return replace(base, disks=(*base.disks, peer), selectable=(*base.selectable, peer)), peer


def test_peer_replaced_at_same_path_revokes_inventory_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    initial, peer = _two_disk_inventory()
    replacement = replace(peer, model="Peer B", serial="PEER-B", layout_id="peer-b-layout")
    fresh = replace(
        initial,
        disks=tuple(replacement if item.path == peer.path else item for item in initial.disks),
        selectable=tuple(replacement if item.path == peer.path else item for item in initial.selectable),
    )
    wizard, runner = _ready(initial, fresh)

    wizard.confirm_erase()

    assert wizard.screen == Screen.CONFIRM
    assert wizard.error == C.AUTHORIZATION_STALE
    assert wizard._authorized_operation is None
    assert not runner.started


def test_unchanged_peer_inventory_allows_authorized_start(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    initial, _peer = _two_disk_inventory()
    wizard, runner = _ready(initial, replace(initial))

    wizard.confirm_erase()

    assert wizard.screen == Screen.WORKING
    assert runner.started
