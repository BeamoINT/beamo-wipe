# SPDX-License-Identifier: GPL-3.0-or-later
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard, make_demo_wizard, format_progress_percent


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
    runner = DryRunRunner(duration_s=1.0, fail=fail, clock=clock)
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
    clock.add(2.0)
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


def test_move_selection_follows_path_sorted_order():
    """Keyboard highlight must match the on-screen sort (path, boot last)."""
    wiz, _clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    ordered = sorted(wiz.selectable, key=lambda d: d.path)
    wiz.move_selection(1)
    assert wiz.selected is not None
    assert wiz.selected.path == ordered[0].path
    if len(ordered) > 1:
        wiz.move_selection(1)
        assert wiz.selected.path == ordered[1].path


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


class _BoomRunner:
    progress = None
    result = None
    started = False

    def start(self, request) -> None:
        raise OSError("nwipe: command not found")

    def poll(self, request):
        return None

    def cancel(self) -> None:
        return None


def test_confirm_erase_does_not_enter_working_if_start_fails(monkeypatch, tmp_path):
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
    wiz.runner = _BoomRunner()
    try:
        wiz.confirm_erase()
    except OSError:
        pass
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.error
    wiz.tick()
    assert wiz.screen == Screen.LAST_CHANCE


def test_confirm_erase_safety_error_stays_on_last_chance(monkeypatch, tmp_path):
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
    wiz.set_owner(False)
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.error
    assert not getattr(wiz.runner, "started", False)


def test_select_disk_ignored_after_confirm(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    first = wiz.selectable[0]
    second = wiz.selectable[1]
    wiz.select_disk(first.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    wiz.select_disk(second.path)
    assert wiz.selected is not None
    assert wiz.selected.path == first.path
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert wiz.runner._request.device == first.path


def test_confirm_erase_refuses_disk_removed_from_selectable(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe.models import DiscoveryResult

    wiz, clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    # Unique size so the confirm token does not change when the list shrinks.
    target = next(d for d in wiz.selectable if d.size_gb_label == "1000")
    wiz.select_disk(target.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    wiz.discovery = DiscoveryResult(
        disks=wiz.discovery.disks,
        selectable=tuple(d for d in wiz.discovery.selectable if d.path != target.path),
        boot=wiz.discovery.boot,
        error=wiz.discovery.error,
        boot_identified=wiz.discovery.boot_identified,
    )
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert not getattr(wiz.runner, "started", False)
    assert wiz.error


def test_confirm_erase_refuses_identity_change_on_rediscover(monkeypatch, tmp_path):
    from dataclasses import replace

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    target = wiz.selectable[0]
    wiz.select_disk(target.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    mutated = replace(wiz.discovery.selectable[0], serial="CHANGED")
    fresh = type(wiz.discovery)(
        disks=wiz.discovery.disks,
        selectable=(mutated,) + wiz.discovery.selectable[1:],
        boot=wiz.discovery.boot,
        error=wiz.discovery.error,
        boot_identified=wiz.discovery.boot_identified,
    )
    wiz.dry_run = False
    wiz.preview = False
    wiz._rediscover = lambda: fresh
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert not getattr(wiz.runner, "started", False)
    assert wiz.error
    assert "identity" in (wiz.error or "").lower()


def test_confirm_erase_fails_closed_on_unexpected_rediscover_error(monkeypatch, tmp_path):
    """A non-standard rediscover failure (not OSError/ValueError/…) must still
    refuse the wipe with a visible error, never start nwipe. Fake disks only."""
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
    wiz.dry_run = False
    wiz.preview = False

    def _boom():
        raise RuntimeError("unexpected lsblk harness failure")

    wiz._rediscover = _boom
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert not getattr(wiz.runner, "started", False)
    assert wiz.error and "Could not re-read disks" in wiz.error


def test_confirm_erase_refuses_real_runner_in_dry_run(monkeypatch, tmp_path):
    from beamo_wipe.nwipe_runner import NwipeRunner

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
    wiz.runner = NwipeRunner()
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.error
    assert "nwipe" in (wiz.error or "").lower()


def test_preview_confirm_erase_ignores_host_sysfs_size(monkeypatch, tmp_path):
    """Demo disks use /dev/sda etc. Host sysfs must not block the fake erase."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr("beamo_wipe.safety.block_size_bytes", lambda _path: 1)
    wiz, clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    target = next(d for d in wiz.selectable if d.path == "/dev/sda")
    wiz.select_disk(target.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert getattr(wiz.runner, "started", False)
    assert not wiz.error


def test_set_method_ignored_off_method_screen():
    from beamo_wipe.methods import DEFAULT_METHOD
    from beamo_wipe.models import MethodId

    wiz, _clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    assert wiz.method == DEFAULT_METHOD
    wiz.set_method(MethodId.QUICK_ZERO)
    assert wiz.method == DEFAULT_METHOD
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD
    wiz.set_method(MethodId.QUICK_ZERO)
    assert wiz.method == MethodId.QUICK_ZERO


def test_confirm_input_ignored_after_confirm_screen(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    token = wiz.confirm.token
    wiz.set_confirm_input(token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD
    wiz.set_confirm_input("nope")
    assert wiz.confirm_input == token
    wiz.continue_method()
    clock.add(5.0)
    wiz.set_confirm_input("nope")
    assert wiz.confirm_input == token
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING


def test_open_advanced_twice_does_not_trap_on_advanced():
    wiz, _clock = _wiz()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD
    wiz.open_advanced()
    assert wiz.screen == Screen.ADVANCED
    wiz.open_advanced()
    wiz.close_advanced()
    assert wiz.screen == Screen.METHOD
    wiz.open_advanced()
    wiz.back()
    assert wiz.screen == Screen.METHOD


def test_confirm_erase_unidentified_rediscover_is_not_usb_unplug_copy(
    monkeypatch, tmp_path
):
    from beamo_wipe.copy import IDENTIFY_ERROR, REDISCOVER_ERROR
    from beamo_wipe.models import DiscoveryResult

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
    wiz.dry_run = False
    wiz.preview = False
    wiz._rediscover = lambda: DiscoveryResult(
        error="Cannot tell which disk is this USB. Unplug extra USB drives and reboot.",
        boot_identified=False,
    )
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert not getattr(wiz.runner, "started", False)
    assert wiz.error == REDISCOVER_ERROR
    assert wiz.error != IDENTIFY_ERROR


def test_pick_empty_keyboard_ignored_until_armed():
    empty = make_demo_wizard(scenario="empty")
    empty.preview = False
    empty.skip_splash()
    empty.accept_what()
    empty.set_owner(True)
    empty.continue_owner()
    assert empty.screen == Screen.PICK_EMPTY
    empty.accept_done_keyboard()
    assert not empty.wants_shutdown
    empty.arm_done_keyboard()
    empty.accept_done_keyboard()
    assert empty.wants_shutdown


def test_pick_blocked_keyboard_ignored_until_armed():
    blocked = make_demo_wizard(scenario="blocked")
    blocked.preview = False
    blocked.skip_splash()
    blocked.accept_what()
    blocked.set_owner(True)
    blocked.continue_owner()
    assert blocked.screen == Screen.PICK_BLOCKED
    blocked.accept_done_keyboard()
    assert not blocked.wants_shutdown
    blocked.arm_done_keyboard()
    blocked.accept_done_keyboard()
    assert blocked.wants_shutdown


def test_done_keyboard_ignored_until_armed(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, _clock = _wiz(fail=True)
    wiz.preview = False
    wiz._finish(
        WipeResult(ok=False, exit_code=1, summary="The wipe did not finish.", logfile="")
    )
    assert wiz.screen == Screen.DONE
    wiz.accept_done_keyboard()
    assert not wiz.wants_shutdown
    wiz.arm_done_keyboard()
    wiz.accept_done_keyboard()
    assert wiz.wants_shutdown


def test_format_progress_percent_does_not_round_up_to_one_hundred():
    """Working must not display 100% while nwipe is still at 99.5–99.99."""
    assert format_progress_percent(99.4) == "99%"
    assert format_progress_percent(99.5) == "99%"
    assert format_progress_percent(99.99) == "99%"
    assert format_progress_percent(100.0) == "100%"
    assert format_progress_percent(0.0) == "0%"
    assert format_progress_percent(45.7) == "45%"


def test_working_uis_never_round_percent_with_point_zero_f():
    import inspect

    from beamo_wipe.ui.console_wizard import _loop
    from beamo_wipe.ui.tk_wizard import TkWizard

    tk_src = inspect.getsource(TkWizard._refresh_working)
    assert "format_progress_percent" in tk_src
    assert ":.0f" not in tk_src
    console_src = inspect.getsource(_loop)
    assert "format_progress_percent" in console_src
    assert ":.0f" not in console_src


def _drive_to_working(wiz, clock):
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


def test_cancel_wipe_failure_stays_working_with_error(monkeypatch, tmp_path):
    """A runner that cannot stop the engine must not become clean 'interrupted'."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz()
    _drive_to_working(wiz, clock)

    def boom() -> None:
        raise OSError(1, "Operation not permitted")

    wiz.runner.cancel = boom  # type: ignore[method-assign]
    wiz.cancel_wipe()
    assert wiz.screen == Screen.WORKING
    assert wiz.error and "Could not stop the wipe" in wiz.error
    assert wiz.wipe_result is None
    # No interrupted evidence for a wipe that may still run.
    assert wiz.evidence is None or wiz.evidence.get("outcome") != "interrupted"


def test_cancel_wipe_retry_succeeds_after_failure(monkeypatch, tmp_path):
    """After a failed cancel, a retry that stops the engine interrupts cleanly."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz()
    _drive_to_working(wiz, clock)
    calls = []

    def flaky() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise OSError(1, "Operation not permitted")

    wiz.runner.cancel = flaky  # type: ignore[method-assign]
    wiz.cancel_wipe()
    assert wiz.screen == Screen.WORKING
    wiz.cancel_wipe()
    assert wiz.screen == Screen.DONE
    assert wiz.wipe_result is not None and not wiz.wipe_result.ok
    assert "interrupted" in wiz.wipe_result.summary


def test_confirm_erase_second_start_reports_already_running(monkeypatch, tmp_path):
    """A second confirm_erase while WORKING gets a visible error, no double start."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz()
    _drive_to_working(wiz, clock)
    first_request = wiz._wipe_request
    starts = []
    orig_start = wiz.runner.start
    wiz.runner.start = lambda request: (starts.append(request), orig_start(request))  # type: ignore[method-assign]
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert wiz.error == "A wipe is already running."
    assert starts == []
    assert wiz._wipe_request is first_request


def test_working_screens_render_cancel_failure():
    """WORKING must show wizard.error (failed cancel) instead of hiding it."""
    import inspect

    from beamo_wipe.ui.console_wizard import _loop
    from beamo_wipe.ui.tk_wizard import TkWizard

    assert "self.w.error" in inspect.getsource(TkWizard._working)
    console_src = inspect.getsource(_loop)
    working_block = console_src.split("Screen.WORKING", 1)[1].split("Screen.DONE", 1)[0]
    assert "wizard.error" in working_block

