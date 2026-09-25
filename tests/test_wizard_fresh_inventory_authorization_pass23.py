# SPDX-License-Identifier: GPL-3.0-or-later
"""Final rediscovery must preserve the inventory the owner authorized."""

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
    target = initial.selectable[0]
    clock = Clock()
    runner = DryRunRunner(clock=clock)
    wizard = Wizard(initial, runner, clock=clock, dry_run=False, rediscover=lambda: fresh)
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(target.path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    assert wizard.screen == Screen.LAST_CHANCE
    clock.value = 6.0
    assert wizard.erase_enabled
    return wizard, runner


def test_new_peer_at_final_rescan_revokes_old_inventory_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    initial = discovery_for_scenario("happy")
    target = initial.selectable[0]
    added = replace(
        target,
        path="/dev/sde",
        name="sde",
        model="New peer",
        serial="NEW-PEER-001",
        size_bytes=512_000_000_000,
        size_gb_label="512",
        layout_id="new-peer-layout",
    )
    fresh = replace(
        initial,
        disks=(*initial.disks, added),
        selectable=(*initial.selectable, added),
    )
    wizard, runner = _ready(initial, fresh)

    wizard.confirm_erase()

    assert wizard.screen == Screen.CONFIRM
    assert wizard.error == C.AUTHORIZATION_STALE
    assert wizard._authorized_operation is None
    assert not runner.started


def test_unchanged_final_rescan_keeps_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    initial = discovery_for_scenario("happy")
    wizard, runner = _ready(initial, replace(initial))

    wizard.confirm_erase()

    assert wizard.screen == Screen.WORKING
    assert runner.started
