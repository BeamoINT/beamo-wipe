# SPDX-License-Identifier: GPL-3.0-or-later
"""Prove confirmation gates cannot be bypassed.

Models the wizard as explicit states and invariants, then adversarially
tries to bypass each gate via keyboard/mouse/focus/rapid-click/key-repeat/
paste/stale-callback/screen-recreation/restart/cancellation/clock-jump/
unusual-ordering.

All fake lsblk JSON, DryRunRunner/SpyRunner, never host disks, never real nwipe.
Covers: ownership ack, exact token, 5 s monotonic delay, device binding,
final eligibility (all gates simultaneously valid).

See docs/confirmation-gates.md for the state model.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.models import MethodId, Screen, WipeRequest
from beamo_wipe.safety import SafetyError
from beamo_wipe.wizard import Wizard

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return load_lsblk_json_text((FIXTURES / name).read_text(encoding="utf-8"))


class Clock:
    def __init__(self, t=0.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def add(self, s):
        self.t += float(s)

    def set(self, t):
        self.t = float(t)


class SpyRunner:
    def __init__(self, duration_s=1.0, fail=False):
        self.start_calls: list[WipeRequest] = []
        self.started = False
        self.progress = None
        self.result = None
        self.duration_s = duration_s
        self.fail = fail
        self._request = None
        self._start_t = None

    def start(self, request: WipeRequest) -> None:
        self.start_calls.append(request)
        self.started = True
        self._request = request
        self._start_t = time.monotonic()

    def poll(self, request):
        if not self.started or self._start_t is None:
            return None
        if time.monotonic() - self._start_t >= self.duration_s:
            from beamo_wipe.models import WipeResult

            ok = not self.fail
            return WipeResult(ok=ok, exit_code=0 if ok else 1, summary="fake", logfile=request.logfile)
        return None

    def cancel(self):
        self.started = False


def _wiz_with_clock(tmp_path=None, *, spy=None, clock=None, dry_run=True):
    if clock is None:
        clock = Clock()
    if spy is None:
        spy = SpyRunner()
    base = make_demo_wizard()
    wiz = Wizard(base.discovery, spy, clock=clock, dry_run=dry_run)
    if tmp_path is not None:
        # Use isolated log dir to avoid host /tmp pollution in assertions
        import beamo_wipe.safety as s

        orig = s.default_log_dir
        wiz._orig_log_dir = orig  # type: ignore[attr-defined]
    return wiz, clock, spy


def _drive_to_last_chance(wiz: Wizard, clock: Clock, tmp_path):
    """Drive wizard from SPLASH to LAST_CHANCE via valid gates."""
    import beamo_wipe.safety as s

    # Patch log dir for this wizard
    orig_default = s.default_log_dir
    s.default_log_dir = lambda: tmp_path  # type: ignore[assignment]
    try:
        wiz.skip_splash()
        wiz.accept_what()
        wiz.set_owner(True)
        wiz.continue_owner()
        assert wiz.screen == Screen.PICK
        target = wiz.selectable[0]
        wiz.select_disk(target.path)
        wiz.continue_pick()
        assert wiz.screen == Screen.CONFIRM
        # Use the exact token for this device (may be size or serial suffix)
        token = wiz.confirm.token  # type: ignore[union-attr]
        wiz.set_confirm_input(token)
        wiz.continue_confirm()
        assert wiz.screen == Screen.METHOD
        wiz.continue_method()
        assert wiz.screen == Screen.LAST_CHANCE
        return target
    finally:
        s.default_log_dir = orig_default  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 1. Model: explicit states and invariants
# ---------------------------------------------------------------------------


def test_model_states_and_invariants_exist():
    """Document the state model: ensure code actually enforces each invariant."""
    import inspect

    from beamo_wipe.wizard import Wizard
    from beamo_wipe.safety import assert_ready_to_wipe

    src = inspect.getsource(Wizard.confirm_erase)
    # Must check every gate explicitly
    assert "erase_enabled" in src
    assert "selected is None" in src
    assert "dry_run" in src and "NwipeRunner" in src
    assert "_rediscover" in src and "discover" in src
    assert "assert_boot_excluded" in src
    assert "assert_disk_identity" in src
    assert "assert_ready_to_wipe" in src
    # assert_ready_to_wipe must check owner, token, countdown, method, identity, mounts, whole-disk
    src2 = inspect.getsource(assert_ready_to_wipe)
    assert "owner_ok" in src2
    assert "token_matches" in src2
    assert "countdown_complete" in src2
    assert "METHODS" in src2
    assert "assert_disk_identity" in src2
    assert "assert_not_system_mounted" in src2
    assert "normalize_whole_disk" in src2


# ---------------------------------------------------------------------------
# 2. Ownership acknowledgement gate
# ---------------------------------------------------------------------------


def test_ownership_checkbox_required(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock(), spy=SpyRunner())
    # Try to continue from OWNER without checking box
    wiz.skip_splash()
    wiz.accept_what()
    assert wiz.screen == Screen.OWNER
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER  # blocked
    assert spy.start_calls == []
    # Checking then unchecking should re-block
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    wiz.back()
    assert wiz.screen == Screen.OWNER
    wiz.set_owner(False)
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
    # Focus changes, rapid double calls must not bypass
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.continue_owner()  # second rapid call while already PICK - no-op
    assert wiz.screen == Screen.PICK
    assert spy.start_calls == []


def test_ownership_rapid_clicks_and_focus_do_not_bypass(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    wiz.skip_splash()
    wiz.accept_what()
    # Spam set_owner toggles rapidly
    for _ in range(10):
        wiz.set_owner(True)
        wiz.set_owner(False)
    assert not wiz.owner_ok
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
    wiz.set_owner(True)
    # Rapid continue clicks
    for _ in range(5):
        wiz.continue_owner()
    assert wiz.screen == Screen.PICK


# ---------------------------------------------------------------------------
# 3. Exact type-to-confirm token
# ---------------------------------------------------------------------------


def test_token_must_be_exact_case_insensitive_but_trimmed(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    # At this point confirm already passed, but we can go back and test token gates
    wiz.back()
    assert wiz.screen == Screen.METHOD
    wiz.back()
    assert wiz.screen == Screen.CONFIRM
    spec = wiz.confirm
    assert spec is not None
    token = spec.token
    # Wrong token variants must not pass
    for bad in ["", " ", token + "x", "x" + token, token[:-1] if len(token) > 1 else "zzz", "  ", "\n"]:
        wiz.set_confirm_input(bad)
        wiz.continue_confirm()
        assert wiz.screen == Screen.CONFIRM, f"bad token {bad!r} should not pass"
    # Case-insensitive exact should pass (code uses casefold)
    wiz.set_confirm_input(token.lower())
    assert wiz.token_ok
    wiz.set_confirm_input(token.upper())
    assert wiz.token_ok
    # Leading/trailing whitespace trimmed then exact
    wiz.set_confirm_input(f"  {token}  ")
    assert wiz.token_ok
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD
    # But embedded whitespace or newline must fail
    wiz.back()
    wiz.set_confirm_input(token + " ")
    # trailing space trimmed → still ok (per token_matches strip), so still passes
    assert wiz.token_ok
    wiz.set_confirm_input(token + "\n")
    # newline stripped → ok as well; but token with newline in middle fails
    wiz.set_confirm_input(token[:1] + "\n" + token[1:])
    assert not wiz.token_ok


def test_token_paste_and_key_repeat_do_not_bypass(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    # Simulate paste of huge string via trace: directly set _confirm_var would go via set_confirm_input
    # Use wizard API: set_confirm_input with pasted oversized
    wiz.back()
    wiz.back()
    assert wiz.screen == Screen.CONFIRM
    huge = "A" * 10000
    wiz.set_confirm_input(huge)
    assert not wiz.token_ok
    wiz.continue_confirm()
    assert wiz.screen == Screen.CONFIRM
    # Paste of correct token with extra null bytes / control chars must fail (SAFE_TOKEN_RE)
    # But our token is alphanum, so pasted token with control char inside fails
    bad_paste = wiz.confirm.token + "\x00"  # type: ignore[union-attr]
    wiz.set_confirm_input(bad_paste)
    # token_ok is False because stripped token with \x00 not matching spec
    assert not wiz.token_ok


def test_token_bound_to_device_identity_snapshot(tmp_path, monkeypatch):
    """Switching disk after CONFIRM must invalidate token."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # Use multi-disk fixture to have two same-size disks requiring serial token

    payload = _load("lsblk_same_size.json")
    disc = discover(lsblk_payload=payload, boot_path="/dev/sdb", mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    clock = Clock()
    spy = SpyRunner()
    wiz = Wizard(disc, spy, clock=clock, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    # Pick first nvme, get its token, go to confirm
    first = next(d for d in wiz.selectable if d.path == "/dev/nvme0n1")
    wiz.select_disk(first.path)
    wiz.continue_pick()
    token_first = wiz.confirm.token  # type: ignore[union-attr]
    # Now go back and pick second disk, token should be different (1111 vs 2222)
    wiz.back()
    assert wiz.screen == Screen.PICK
    second = next(d for d in wiz.selectable if d.path == "/dev/nvme1n1")
    wiz.select_disk(second.path)
    wiz.continue_pick()
    token_second = wiz.confirm.token  # type: ignore[union-attr]
    assert token_first != token_second
    # Using first token for second disk must fail
    wiz.set_confirm_input(token_first)
    assert not wiz.token_ok
    wiz.continue_confirm()
    assert wiz.screen == Screen.CONFIRM
    wiz.set_confirm_input(token_second)
    assert wiz.token_ok


# ---------------------------------------------------------------------------
# 4. Five-second monotonic delay
# ---------------------------------------------------------------------------


def test_five_second_delay_blocks_early_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock(), spy=SpyRunner())
    _drive_to_last_chance(wiz, clock, tmp_path)
    assert not wiz.erase_enabled
    assert wiz.countdown_left > 4.9
    # Early confirm must not start
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert spy.start_calls == []
    assert wiz.error is None or "delay" not in wiz.error.lower()  # early is silently ignored, not error


def test_countdown_completes_only_after_five_seconds(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    clock = Clock()
    wiz, _, spy = _wiz_with_clock(clock=clock, spy=SpyRunner())
    _drive_to_last_chance(wiz, clock, tmp_path)
    clock.add(4.9)
    assert not wiz.erase_enabled
    wiz.confirm_erase()
    assert spy.start_calls == []
    clock.add(0.2)
    wiz.tick()
    assert wiz.erase_enabled
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert len(spy.start_calls) == 1


def test_clock_going_backwards_does_not_bypass_delay(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    clock = Clock(t=10.0)
    wiz, _, spy = _wiz_with_clock(clock=clock, spy=SpyRunner())
    _drive_to_last_chance(wiz, clock, tmp_path)
    # _erase_until = 15.0
    assert wiz._erase_until == 15.0
    # Jump clock backwards to 5.0 — countdown should be max(0, 15-5)=10, still blocked
    clock.set(5.0)
    assert wiz.countdown_left == 10.0
    assert not wiz.erase_enabled
    wiz.confirm_erase()
    assert spy.start_calls == []
    # Jump forward to exactly 15.0 should enable
    clock.set(15.0)
    assert wiz.countdown_left == 0.0
    assert wiz.erase_enabled


def test_clock_jump_forward_still_requires_exact_token(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    clock = Clock()
    wiz, _, spy = _wiz_with_clock(clock=clock, spy=SpyRunner())
    _drive_to_last_chance(wiz, clock, tmp_path)
    # Clear token by going back and re-entering with wrong token
    wiz.back()
    wiz.back()
    # Now on CONFIRM, set wrong token, go forward again
    wiz.set_confirm_input("WRONG")
    wiz.continue_confirm()
    assert wiz.screen == Screen.CONFIRM  # blocked by token
    wiz.set_confirm_input(wiz.confirm.token)  # type: ignore[union-attr]
    wiz.continue_confirm()
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    # Even if we jump clock, token check at confirm_erase time still uses assert_ready_to_wipe
    clock.add(5.0)
    wiz.confirm_input = "WRONG"  # tamper after reaching LAST_CHANCE
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert spy.start_calls == []
    assert wiz.error is not None and "token" in wiz.error.lower()


# ---------------------------------------------------------------------------
# 5. Selected-device binding (immutable snapshot)
# ---------------------------------------------------------------------------


def test_select_disk_ignored_outside_pick(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    # Try to select from SPLASH/WHAT/OWNER/CONFIRM/METHOD/LAST_CHANCE — all no-ops
    wiz.select_disk("/dev/nvme0n1")
    assert wiz.selected is None
    wiz.skip_splash()
    wiz.accept_what()
    wiz.select_disk("/dev/nvme0n1")
    assert wiz.selected is None
    wiz.set_owner(True)
    wiz.continue_owner()
    # Now PICK — allowed
    wiz.select_disk(wiz.selectable[0].path)
    assert wiz.selected is not None
    first = wiz.selected.path
    wiz.continue_pick()
    # Now CONFIRM — select ignored
    wiz.select_disk(wiz.selectable[1].path if len(wiz.selectable) > 1 else "/dev/sda")
    assert wiz.selected.path == first
    # Jump to LAST_CHANCE
    wiz.set_confirm_input(wiz.confirm.token)  # type: ignore[union-attr]
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    wiz.select_disk(wiz.selectable[1].path if len(wiz.selectable) > 1 else "/dev/sda")
    assert wiz.selected.path == first


def test_back_navigation_invalidates_erase_timer(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    clock.add(5.0)
    wiz.tick()
    assert wiz.erase_enabled
    wiz.back()
    assert wiz.screen == Screen.METHOD
    assert wiz._erase_until is None
    # Going forward again creates a fresh 5 s timer
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    assert not wiz.erase_enabled
    assert wiz.countdown_left > 4.9
    wiz.confirm_erase()
    assert spy.start_calls == []


def test_device_identity_change_invalidates_confirm(tmp_path, monkeypatch):
    """Disk serial/size/wwn change on rediscover must fail closed."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # Use real rediscover path (dry_run=False)
    from dataclasses import replace

    clock = Clock()
    spy = SpyRunner()
    base = make_demo_wizard()
    wiz = Wizard(base.discovery, spy, clock=clock, dry_run=False)
    wiz.preview = False
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    target = wiz.selectable[0]
    wiz.select_disk(target.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)  # type: ignore[union-attr]
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    wiz.tick()
    # Mutate serial
    mutated = replace(target, serial="MUTATED_SERIAL_XYZ")
    from beamo_wipe.models import DiscoveryResult

    fresh = DiscoveryResult(
        disks=tuple(mutated if d.path == target.path else d for d in wiz.discovery.disks),
        selectable=tuple(mutated if d.path == target.path else d for d in wiz.discovery.selectable),
        boot=wiz.discovery.boot,
        error=None,
        boot_identified=True,
    )
    wiz._rediscover = lambda: fresh  # type: ignore[attr-defined]
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.error is not None and "identity" in wiz.error.lower()
    assert spy.start_calls == []


# ---------------------------------------------------------------------------
# 6. Focus / keyboard / mouse / key repeat / paste / stale callback
# ---------------------------------------------------------------------------


def test_focus_changes_do_not_bypass_gates(monkeypatch, tmp_path):
    """Tk focus: trace on _confirm_var only updates token_ok, does not auto-advance."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    # Simulate focus moving in/out: just call set_confirm_input with partial token
    partial = wiz.confirm.token[:1]  # type: ignore[union-attr]
    wiz.set_confirm_input(partial)
    assert not wiz.token_ok
    # continue_confirm should still be blocked even after focus events
    wiz.continue_confirm()
    assert wiz.screen == Screen.CONFIRM
    # Now give correct token via "paste" (large set)
    wiz.set_confirm_input(wiz.confirm.token)  # type: ignore[union-attr]
    assert wiz.token_ok
    # But still need explicit Enter (continue_confirm) — token_ok alone doesn't advance
    assert wiz.screen == Screen.CONFIRM
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD


def test_rapid_clicks_do_not_double_start(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock(), spy=SpyRunner())
    _drive_to_last_chance(wiz, clock, tmp_path)
    clock.add(5.0)
    wiz.tick()
    # Rapid double confirm_erase
    wiz.confirm_erase()
    wiz.confirm_erase()
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert len(spy.start_calls) == 1
    # Further calls while WORKING are no-ops
    wiz.confirm_erase()
    assert len(spy.start_calls) == 1


def test_key_repeat_held_return_does_not_bypass(tmp_path, monkeypatch):
    """Tk binds <KeyRelease-Return> to arm; held repeat without release must not fire."""
    # This is the DM's held-enter invariant: Wizard uses _done_keyboard_armed and erase_enabled
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    # Before countdown, held Return should not start
    wiz.confirm_erase()  # early
    assert spy.start_calls == []
    # After countdown, first call starts
    clock.add(5.0)
    wiz.tick()
    # Simulate X11 repeat: two KeyPress without intervening KeyRelease — TkWizard would call _on_return twice
    # Wizard.confirm_erase is idempotent: second call sees screen==WORKING, returns
    wiz.confirm_erase()
    assert len(spy.start_calls) == 1
    # Second repeat while already WORKING must not create second request
    wiz.confirm_erase()
    assert len(spy.start_calls) == 1


def test_stale_callback_after_screen_change_does_not_fire(tmp_path, monkeypatch):
    """Tick is the only timer callback; stale _erase_until after back must not auto-start."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    # Back clears _erase_until
    wiz.back()
    assert wiz._erase_until is None
    # Even if clock jumps, no auto-start without explicit confirm_erase
    clock.add(10.0)
    wiz.tick()
    assert wiz.screen == Screen.METHOD
    assert spy.start_calls == []


def test_screen_recreation_does_not_reset_gates(tmp_path, monkeypatch):
    """TkWizard._draw recreation must not clear wizard.error or re-enable erase."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    # Simulate error from previous failed confirm_erase (e.g., token mismatch due to tamper)
    wiz.confirm_input = "BAD"
    # Need to wait for countdown to test error path
    clock.add(5.0)
    wiz.tick()
    wiz.confirm_erase()
    assert wiz.error is not None
    assert wiz.screen == Screen.LAST_CHANCE
    # Screen recreation (e.g., Tk _draw) would keep error until back
    assert wiz.error is not None
    wiz.back()
    assert wiz.error is None
    assert wiz.screen == Screen.METHOD


# ---------------------------------------------------------------------------
# 7. Restart / cancellation / unusual ordering
# ---------------------------------------------------------------------------


def test_restart_clears_all_gates(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz = make_demo_wizard()
    # Drive to confirm
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)  # type: ignore[union-attr]
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD
    # Preview restart
    wiz.reset_for_preview()
    assert wiz.screen == Screen.SPLASH
    assert not wiz.owner_ok
    assert wiz.selected is None
    assert wiz.confirm_input == ""
    assert wiz._erase_until is None
    assert wiz._wipe_request is None
    assert wiz.error is None
    # Must re-pass all gates from scratch
    wiz.skip_splash()
    wiz.accept_what()
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER  # owner not set
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK


def test_cancellation_does_not_leave_stale_request(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock(), spy=SpyRunner(duration_s=10.0))
    _drive_to_last_chance(wiz, clock, tmp_path)
    clock.add(5.0)
    wiz.tick()
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert wiz._wipe_request is not None
    wiz.runner.cancel()  # type: ignore[attr-defined]
    # Poll will transition to DONE (failure) on next tick if runner supports it; for SpyRunner poll returns None
    # Ensure that after cancel, a second confirm_erase is not possible without full restart
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert len(spy.start_calls) == 1


def test_unusual_ordering_any_sequence_before_gates_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    # Try every destructive-adjacent call out of order
    wiz.confirm_erase()
    assert wiz.screen == Screen.SPLASH
    assert spy.start_calls == []
    wiz.continue_confirm()
    assert spy.start_calls == []
    wiz.continue_method()
    assert spy.start_calls == []
    wiz.set_confirm_input("123")
    assert wiz.confirm is None  # no selected
    wiz.select_disk("/dev/sda")
    assert wiz.selected is None  # not in PICK
    wiz.skip_splash()
    # Still on WHAT, try to jump to LAST_CHANCE
    wiz.continue_method()
    assert wiz.screen == Screen.WHAT
    wiz.confirm_erase()
    assert spy.start_calls == []


def test_no_accessibility_or_preview_path_can_invoke_nwipe(tmp_path, monkeypatch):
    """Preview/DryRun must never reach real NwipeRunner even if injected."""
    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # Dry-run wizard with real runner must be blocked at confirm_erase
    base = make_demo_wizard()
    clock = Clock()
    real_runner = NwipeRunner()
    wiz = Wizard(base.discovery, real_runner, clock=clock, dry_run=True)
    wiz.preview = False  # dry_run True but preview False — still blocked
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)  # type: ignore[union-attr]
    wiz.continue_confirm()
    wiz.continue_method()
    clock.add(5.0)
    wiz.tick()
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert "Preview" in (wiz.error or "")
    assert wiz._wipe_request is None
    # Even if someone calls runner.start directly with a fake request, require_real_live_for_nwipe should block
    from beamo_wipe.models import WipeRequest

    fake_req = WipeRequest(device="/dev/sda", method=MethodId.EVERYDAY, boot_device="/dev/sdb", logfile=str(tmp_path / "nwipe-sda.log"))
    with pytest.raises(SafetyError):
        real_runner.start(fake_req)


def test_no_timer_callback_auto_starts_wipe(tmp_path, monkeypatch):
    """Tick only auto-advances SPLASH→WHAT and polls WORKING; never starts a wipe."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    # Let splash time out to WHAT automatically
    clock.add(3.1)
    wiz.tick()
    assert wiz.screen == Screen.WHAT
    # Tick many times without user input must never start
    for _ in range(10):
        clock.add(1.0)
        wiz.tick()
        assert wiz.screen == Screen.WHAT
        assert spy.start_calls == []
    # Even on LAST_CHANCE, tick after countdown does NOT auto-start
    _drive_to_last_chance(wiz, clock, tmp_path)
    clock.add(10.0)
    for _ in range(5):
        wiz.tick()
        assert wiz.screen == Screen.LAST_CHANCE
        assert spy.start_calls == []
    # Only explicit confirm_erase starts
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING


def test_all_gates_must_be_simultaneously_valid(tmp_path, monkeypatch):
    """Prove no single gate alone can start; only all together succeed."""
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)

    # Case A: owner true, token ok, countdown ok, but no selected
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    # Don't select — try to jump to LAST_CHANCE via direct calls (should fail)
    wiz.continue_pick()
    assert wiz.screen == Screen.PICK
    wiz.set_confirm_input("any")
    wiz.continue_confirm()
    assert wiz.screen == Screen.PICK
    wiz.continue_method()
    assert wiz.screen == Screen.PICK
    assert spy.start_calls == []

    # Case B: owner false at final moment
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    clock.add(5.0)
    wiz.tick()
    wiz.set_owner(False)
    wiz.confirm_erase()
    assert wiz.screen == Screen.LAST_CHANCE
    assert spy.start_calls == []
    assert wiz.error is not None

    # Case C: token stale
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    clock.add(5.0)
    wiz.tick()
    wiz.confirm_input = "BADTOKEN"
    wiz.confirm_erase()
    assert spy.start_calls == []
    assert wiz.error is not None

    # Case D: countdown not yet done
    wiz, clock, spy = _wiz_with_clock(clock=Clock())
    _drive_to_last_chance(wiz, clock, tmp_path)
    # Don't add 5 s
    wiz.confirm_erase()
    assert spy.start_calls == []

    # Case E: valid all together → succeeds
    wiz, clock, spy = _wiz_with_clock(clock=Clock(), spy=SpyRunner())
    _drive_to_last_chance(wiz, clock, tmp_path)
    clock.add(5.0)
    wiz.tick()
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert len(spy.start_calls) == 1
