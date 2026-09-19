"""Uncertainty must revoke target authorization; fake disks only."""
import pytest
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen


def picker():
    w = make_demo_wizard()
    w.skip_intro()
    w.accept_what()
    w.set_owner(True)
    w.continue_owner()
    return w


def test_help_revokes_selection_and_cannot_authorize():
    w = picker()
    w.select_disk(w.selectable[0].path)
    w.confirm_input = 'stale'
    w._erase_until = 1
    w._authorized_operation = ('stale',)
    w.open_disk_help()
    assert w.screen == Screen.DISK_HELP
    assert w.selected is None
    assert w.confirm_input == ''
    assert w._erase_until is None
    assert w._authorized_operation is None
    assert w.owner_ok  # retains an acknowledgement, never grants one
    w.move_selection(1)
    w.select_disk(w.selectable[0].path)
    w.continue_pick()
    w.continue_confirm()
    w.continue_method()
    w.confirm_erase()
    assert w.screen == Screen.DISK_HELP
    assert w.selected is None
    assert not w.runner.started
    w.back()
    w.continue_pick()
    assert w.screen == Screen.PICK
    assert w.selected is None


@pytest.mark.parametrize('screen', [Screen.CONFIRM, Screen.CHECKING, Screen.WORKING, Screen.PICK_BLOCKED])
def test_stale_help_action_is_ignored(screen):
    w = picker()
    w.screen = screen
    w.open_disk_help()
    assert w.screen == screen


def test_console_unsure_keys_and_plain_stop(monkeypatch, capsys):
    import curses
    from beamo_wipe.ui.console_wizard import _handle, _plain_loop
    w = picker()
    _handle(w, ord('u'))
    for key in [10, 13, curses.KEY_DOWN, curses.KEY_NPAGE, ord(' ')]:
        _handle(w, key)
        assert w.screen == Screen.DISK_HELP and w.selected is None
    _handle(w, 27)
    assert w.screen == Screen.PICK and w.selected is None
    answers = iter(['U', 'BACK', 'U', 'STOP'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    _plain_loop(w)
    assert w.wants_shutdown and not w.runner.started
    assert 'external disk' in capsys.readouterr().out


def test_after_help_full_confirmation_still_required():
    from test_wizard_flow import Clock
    w = picker()
    clock = Clock()
    w._clock = clock
    w.open_disk_help()
    w.back()
    w.select_disk(w.selectable[0].path)
    w.continue_pick()
    w.continue_confirm()
    assert w.screen == Screen.CONFIRM
    w.set_confirm_input(w.confirm.token)
    w.continue_confirm()
    w.continue_method()
    assert w.screen == Screen.LAST_CHANCE and not w.erase_enabled
    w.confirm_erase()
    assert not w.runner.started
    clock.add(4.99)
    assert not w.erase_enabled
    clock.add(.01)
    assert w.erase_enabled
    assert not w.runner.started


def test_help_does_not_grant_ownership_and_shutdown_preserves_report():
    w = picker()
    w.owner_ok = False
    w.open_disk_help()
    assert not w.owner_ok
    w.report_wanted = True
    w.shutdown()
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not w.wants_shutdown
    w.back()
    assert w.screen == Screen.DISK_HELP and w.selected is None


@pytest.mark.parametrize('fixture', ['lsblk_identical_missing_serial.json', 'lsblk_duplicate_serial.json'])
def test_help_preserves_identity_protections(fixture):
    from test_identity import _disc
    from beamo_wipe.wizard import Wizard
    from beamo_wipe.nwipe_runner import DryRunRunner
    w = Wizard(_disc(fixture), DryRunRunner(), dry_run=True)
    w.skip_intro()
    w.accept_what()
    w.set_owner(True)
    w.continue_owner()
    target = w.selectable[0]
    before = w.disk_view(target)
    w.select_disk(target.path)
    w.open_disk_help()
    w.back()
    assert w.selected is None and w.disk_view(target) == before
    w.select_disk(target.path)
    w.continue_pick()
    if not before.confirmable:
        assert w.screen == Screen.PICK and w.confirm is None
    assert not w.runner.started


def test_help_keyboard_and_refresh_return_paths():
    w = picker()
    w.open_disk_help()
    w.open_keyboard()
    w.back()
    assert w.screen == Screen.DISK_HELP and w.selected is None
    fresh = w.discovery
    w._rediscover = lambda: fresh
    w.refresh_disks()
    assert w.screen == Screen.OWNER and not w.owner_ok and w.selected is None
