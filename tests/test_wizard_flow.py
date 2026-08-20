# SPDX-License-Identifier: GPL-3.0-or-later
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard, make_demo_wizard


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def add(self, seconds: float) -> None:
        self.t += seconds


def _wiz(fail: bool = False) -> tuple[Wizard, Clock]:
    base = make_demo_wizard(fail=fail)
    clock = Clock()
    runner = DryRunRunner(duration_s=1.0, fail=fail)
    wiz = Wizard(base.discovery, runner, clock=clock, dry_run=True)
    return wiz, clock


def test_no_autostart_wipe():
    wiz, _clock = _wiz()
    assert wiz.screen == Screen.SPLASH
    assert not getattr(wiz.runner, "started", False)
    wiz.tick()
    assert not getattr(wiz.runner, "started", False)


def test_splash_times_out():
    wiz, clock = _wiz()
    clock.add(3.1)
    wiz.tick()
    assert wiz.screen == Screen.WHAT


def test_happy_path_dry_run(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    assert wiz.screen == Screen.OWNER
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    assert wiz.selected is None
    wiz.continue_pick()
    assert wiz.screen == Screen.PICK
    boot = wiz.discovery.boot
    assert boot is not None
    wiz.select_disk(boot.path)
    assert wiz.selected is None or wiz.selected.path != boot.path
    target = wiz.selectable[0]
    wiz.select_disk(target.path)
    wiz.continue_pick()
    assert wiz.screen == Screen.CONFIRM
    wiz.continue_confirm()
    assert wiz.screen == Screen.CONFIRM
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    wiz.confirm_erase()
    assert not getattr(wiz.runner, "started", False)
    clock.add(5.0)
    wiz.tick()
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert wiz.runner.started
    clock.add(2.0)
    # DryRunRunner uses time.monotonic, not the wizard clock.
    import time

    time.sleep(1.05)
    wiz.tick()
    assert wiz.screen == Screen.DONE
    assert wiz.done_ok


def test_kill_mid_run_is_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    wiz.runner.cancel()
    wiz.tick()
    assert wiz.screen == Screen.DONE
    assert not wiz.done_ok


def test_nonzero_exit_is_not_success(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(fail=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    wiz.confirm_erase()
    import time

    time.sleep(1.05)
    wiz.tick()
    assert wiz.screen == Screen.DONE
    assert not wiz.done_ok
    assert "secure" not in (wiz.log_text or "").lower()


def test_back_from_last_chance_redraws_method_state():
    wiz, clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    wiz.back()
    assert wiz.screen == Screen.METHOD
    assert wiz._erase_until is None


def test_move_selection_does_not_start_on_boot():
    wiz, _clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.selected is None
    wiz.move_selection(1)
    assert wiz.selected is not None
    assert not wiz.selected.is_boot
    boot = wiz.discovery.boot
    assert boot is not None
    paths = {d.path for d in wiz.selectable}
    assert wiz.selected.path in paths


def test_preview_splash_does_not_auto_advance():
    wiz = make_demo_wizard()
    assert wiz.preview
    assert wiz.screen == Screen.SPLASH
    wiz._splash_until = wiz.now - 1
    wiz.tick()
    assert wiz.screen == Screen.SPLASH
    wiz.skip_splash()
    assert wiz.screen == Screen.WHAT


def test_empty_and_blocked_scenarios():
    empty = make_demo_wizard(scenario="empty")
    empty.skip_splash()
    empty.accept_what()
    empty.set_owner(True)
    empty.continue_owner()
    assert empty.screen == Screen.PICK_EMPTY
    blocked = make_demo_wizard(scenario="blocked")
    blocked.skip_splash()
    blocked.accept_what()
    blocked.set_owner(True)
    blocked.continue_owner()
    assert blocked.screen == Screen.PICK_BLOCKED


def test_reset_for_preview_clears_selection(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz = make_demo_wizard()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.reset_for_preview()
    assert wiz.screen == Screen.SPLASH
    assert wiz.selected is None
    assert not wiz.owner_ok
