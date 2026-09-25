# SPDX-License-Identifier: GPL-3.0-or-later
"""The erase action cannot manufacture a missing consent binding."""

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


def _authorized():
    clock = Clock()
    runner = DryRunRunner(clock=clock)
    wizard = Wizard(make_demo_wizard().discovery, runner, clock=clock, dry_run=True)
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    assert wizard.screen == Screen.LAST_CHANCE
    clock.value = 5.0
    assert wizard.erase_enabled
    return wizard


def test_missing_authorization_cannot_be_created_by_erase_action():
    wizard = _authorized()
    wizard._authorized_operation = None
    wizard.confirm_erase()
    assert wizard.screen == Screen.CONFIRM
    assert wizard.error == C.AUTHORIZATION_STALE
    assert wizard._authorized_operation is None
    assert not wizard.runner.started


def test_intact_authorization_starts_only_after_separate_erase_action(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = _authorized()
    assert not wizard.runner.started
    wizard.confirm_erase()
    assert wizard.runner.started
    assert wizard.screen == Screen.WORKING
