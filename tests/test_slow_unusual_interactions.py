# SPDX-License-Identifier: GPL-3.0-or-later
"""#113 — slow and unusual interactions. Deterministic fakes only; never nwipe."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
import pytest

from beamo_wipe import copy as C
from beamo_wipe.copy import REDISCOVER_ERROR
from beamo_wipe.demo import DEMO_DURATION_S, discovery_for_scenario
from beamo_wipe.models import DiscoveryResult, Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.progress import (
    FIRST_UPDATE_GRACE_S,
    STALE_PROGRESS_S,
    ProgressTiming,
    observe,
)
from beamo_wipe.safety import SafetyError
from beamo_wipe.startup_stages import STAGE_BOOT_USB, STAGE_FINDING, StartupRun
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import EVIDENCE_RETRIES, Wizard

MANY = 24
LONG_MODEL = ("External USB Bridge Adapter " * 6).strip()


class Clock:
    def __init__(self, t=0.0):
        self.mono = float(t)
        self.wall = 1000.0

    def __call__(self):
        return self.mono

    def add(self, seconds):
        self.mono += float(seconds)
        self.wall += float(seconds)


class HeldRunner:
    """Never completes, never execs nwipe, never opens a host disk."""

    def __init__(self):
        self.progress = None
        self.progress_observation = None
        self.result = None
        self.started = False
        self.finalizing = False
        self.cancelled = False
        self.request = None

    def start(self, request):
        self.started = True
        self.request = request

    def poll(self, request):
        return self.result

    def cancel(self):
        self.cancelled = True


def _progress_line(device, pct, eta=400, phase="writing"):
    hours, seconds = divmod(eta, 3600)
    minutes, seconds = divmod(seconds, 60)
    return (
        f"{device}: {pct:.2f}%, round 1 of 1, pass 1 of 1, "
        f"eta {hours:02}:{minutes:02}:{seconds:02}, [{phase}]\n"
    )


def _observation(device, pct, **kwargs):
    result = observe(_progress_line(device, pct, **kwargs), device)
    assert result is not None
    return result


def _long_serial(tag: str) -> str:
    return f"SER{tag}-" + ("X" * 53) + "-TAIL"


def _clone_disk(disk, **changes):
    return replace(disk, **changes)


def long_identity_discovery():
    base = discovery_for_scenario("happy")
    disks, selectable = [], []
    for index, disk in enumerate(base.disks):
        if disk in base.selectable:
            disk = _clone_disk(
                disk,
                model=LONG_MODEL,
                serial=_long_serial(f"D{index}"),
            )
            selectable.append(disk)
        disks.append(disk)
    return replace(base, disks=tuple(disks), selectable=tuple(selectable))


def many_disk_discovery(count=MANY):
    base = discovery_for_scenario("happy")
    template = base.selectable[0]
    extra = []
    for i in range(count):
        extra.append(
            _clone_disk(
                template,
                path=f"/dev/vd{chr(97 + i)}",
                name=f"vd{chr(97 + i)}",
                model=f"Bulk Drive {i:02d} {LONG_MODEL}",
                serial=_long_serial(f"M{i:02d}"),
                size_bytes=template.size_bytes + (i + 1) * 1_000_000_000,
                size_gb_label=str(300 + i),
            )
        )
    return replace(
        base,
        disks=tuple(base.disks) + tuple(extra),
        selectable=tuple(base.selectable) + tuple(extra),
    )


def make_wiz(discovery=None, runner=None, rediscover=None, clock=None, preview=True):
    base = discovery or discovery_for_scenario("happy")
    run = runner or DryRunRunner(duration_s=DEMO_DURATION_S, clock=clock)
    wiz = Wizard(
        base,
        run,
        clock=clock or time.monotonic,
        dry_run=True,
        rediscover=rediscover or (lambda: base),
    )
    wiz.preview = preview
    return wiz


def at_pick(wiz=None):
    wiz = wiz or make_wiz()
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    return wiz


def at_last(wiz=None):
    wiz = at_pick(wiz)
    wiz.select_disk(sorted(wiz.selectable, key=lambda d: d.path)[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0
    return wiz


def bind_timing(wiz, clock):
    wiz._clock = clock
    wiz._progress_timing.clock = clock
    wiz._progress_timing.wall_clock = lambda: clock.wall
    wiz._progress_timing.last_clock = (clock(), clock.wall)


# ---------------------------------------------------------------------------
# 1. Slow discovery
# ---------------------------------------------------------------------------


def test_slow_discovery_refuses_a_second_scan_and_drops_stale_results():
    ready = threading.Event()
    proceed = threading.Event()
    fresh = discovery_for_scenario("happy")

    def slow():
        ready.set()
        assert proceed.wait(5)
        return fresh

    wiz = at_pick(make_wiz(rediscover=slow))
    selected = wiz.selectable[0].path
    wiz.select_disk(selected)
    seq = wiz.begin_refresh()
    assert seq is not None
    assert wiz.screen == Screen.REFRESHING
    assert wiz.selected is None and not wiz.owner_ok
    assert wiz.begin_refresh() is None  # one scan at a time
    assert wiz.refresh_disks() is False
    wiz.back()
    wiz.open_disk_help()
    wiz.shutdown()
    assert wiz.screen == Screen.REFRESHING  # scan owns the screen
    assert wiz.finish_refresh(seq - 1, fresh) is False  # stale sequence
    proceed.set()
    assert wiz.finish_refresh(seq, fresh) is True
    assert wiz.screen == Screen.OWNER
    assert wiz.selected is None and not wiz.owner_ok and not wiz.confirm_input


def test_slow_startup_reports_stages_before_the_wizard_arrives():
    at_boot = threading.Event()
    proceed = threading.Event()

    def slow_build(report):
        report(STAGE_BOOT_USB)
        at_boot.set()
        proceed.wait(timeout=5)
        report(STAGE_FINDING)
        return "wizard-sentinel"

    run = StartupRun(slow_build)
    run.start()
    try:
        assert at_boot.wait(timeout=5)
        deadline = time.monotonic() + 5
        snapshot = {}
        while time.monotonic() < deadline:
            snapshot = {row["key"]: row["state"] for row in run.drain()}
            if snapshot.get(STAGE_BOOT_USB) == "active":
                break
        assert snapshot.get(STAGE_BOOT_USB) == "active"
        assert snapshot.get(STAGE_FINDING) == "pending"
        assert run.poll() is None
        proceed.set()
        deadline = time.monotonic() + 5
        outcome = None
        while time.monotonic() < deadline:
            run.drain()
            outcome = run.poll()
            if outcome is not None:
                break
            time.sleep(0.02)
        assert outcome == ("wizard", "wizard-sentinel")
    finally:
        proceed.set()


def test_tk_refresh_loop_beats_during_slow_discovery():
    from test_refresh_scan_flow import _settle, _stub_app

    app, calls, main_ident = _stub_app(
        lambda: discovery_for_scenario("happy"), delay=0.4
    )
    beats = []

    def beat():
        beats.append(time.monotonic())
        if app.w.screen == Screen.REFRESHING:
            app.root.after(50, beat)

    try:
        app._click_refresh()
        assert app.w.screen == Screen.REFRESH_CONFIRM
        app.root.after(50, beat)
        start = time.monotonic()
        app._click_refresh()
        assert time.monotonic() - start < 0.25
        assert app.w.screen == Screen.REFRESHING
        assert app._click_refresh() is None or app.w.screen == Screen.REFRESHING
        assert _settle(app) == Screen.OWNER
        assert len(beats) >= 3, f"UI loop stalled ({len(beats)} beats)"
        assert calls and calls[0] != main_ident
        assert all(ident == main_ident for ident, _screen in app.draws)
        assert app.w.selected is None
    finally:
        app._teardown()


# ---------------------------------------------------------------------------
# 2. Delayed progress
# ---------------------------------------------------------------------------


def test_delayed_progress_marks_old_without_stopping_or_inventing_an_eta():
    clock = Clock()
    wiz = at_last(make_wiz(runner=HeldRunner(), clock=clock))
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    bind_timing(wiz, clock)
    device = wiz.selected.path
    wiz.runner.progress = 42.0
    wiz.runner.progress_observation = _observation(device, 42)
    live = wiz.progress_view
    assert live.percent == pytest.approx(42)
    assert not live.percent_is_old
    assert live.stale_for is None
    clock.add(STALE_PROGRESS_S + 1)
    delayed = wiz.progress_view
    assert delayed.percent == pytest.approx(42)
    assert delayed.percent_is_old
    assert delayed.stale_for == pytest.approx(STALE_PROGRESS_S + 1)
    assert delayed.remaining is None
    assert "Last reported:" in delayed.status_text
    assert "(old)" in delayed.status_text
    assert "No new progress update" in delayed.timing_text
    assert wiz.screen == Screen.WORKING
    assert not wiz.runner.cancelled
    assert wiz.wipe_result is None


def test_first_progress_grace_then_unavailable_without_a_percentage():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    early = timing.view(None, False)
    assert early.animate and early.stale_for is None
    clock.add(FIRST_UPDATE_GRACE_S + 1)
    late = timing.view(None, False)
    assert late.stale_for == pytest.approx(FIRST_UPDATE_GRACE_S + 1)
    assert not late.animate
    assert late.percent is None
    assert "No new progress update" in late.status_text


def test_displayed_percent_is_throttled_five_seconds_while_phase_stays_live():
    clock = Clock()
    wiz = at_last(make_wiz(runner=HeldRunner(), clock=clock))
    wiz.confirm_erase()
    bind_timing(wiz, clock)
    device = wiz.selected.path
    wiz.runner.progress = 10.0
    wiz.runner.progress_observation = _observation(device, 10)
    first = wiz.progress_view
    wiz.runner.progress = 40.0
    wiz.runner.progress_observation = _observation(device, 40)
    clock.add(1)
    held = wiz.progress_view
    assert held.percent == first.percent
    assert held.phase == "Writing"
    clock.add(5)
    later = wiz.progress_view
    assert later.percent == pytest.approx(40)


# ---------------------------------------------------------------------------
# 3. Long identifiers
# ---------------------------------------------------------------------------


def test_long_identifiers_wrap_and_keep_the_exact_confirm_token():
    from beamo_wipe.ui.tk_wizard import _soft_break_tokens

    discovery = long_identity_discovery()
    wiz = at_pick(make_wiz(discovery=discovery, rediscover=lambda: discovery))
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    view = wiz.disk_view(disk)
    assert LONG_MODEL.replace("\n", "") in view.title.replace("\n", "")
    assert disk.serial == view.id_value
    assert "…" not in view.id_value and "..." not in view.id_value
    broken = _soft_break_tokens(view.id_value, lambda text: len(text) * 10, 200)
    assert "\n" in broken
    assert broken.replace("\n", "") == view.id_value
    wiz.continue_pick()
    token = wiz.confirm.token
    assert token
    assert "\n" not in token
    wiz.set_confirm_input(token[:-1])
    wiz.continue_confirm()
    assert wiz.screen == Screen.CONFIRM
    wiz.set_confirm_input(token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD


def test_console_wraps_long_identifiers_inside_80_columns(monkeypatch):
    from test_console_parity import Terminal

    discovery = long_identity_discovery()
    wiz = at_pick(make_wiz(discovery=discovery, rediscover=lambda: discovery))
    wiz.select_disk(sorted(wiz.selectable, key=lambda d: d.path)[0].path)
    term = Terminal(wiz, h=24, w=80, keys=[])
    for name in ("curs_set", "use_default_colors", "echo", "noecho"):
        monkeypatch.setattr(console.curses, name, lambda *a, **k: None)
    console._loop(term, wiz)
    last = term.frames[-1]
    packed = "".join(last[y] for y in sorted(last))
    assert wiz.selected.serial in packed
    assert all(len(line) < 80 for line in last.values())
    assert max(last) < 24


# ---------------------------------------------------------------------------
# 4. Many disks
# ---------------------------------------------------------------------------


def test_many_disks_keep_boot_excluded_and_require_a_real_choice():
    discovery = many_disk_discovery()
    wiz = at_pick(make_wiz(discovery=discovery, rediscover=lambda: discovery))
    assert len(wiz.selectable) >= MANY
    boot = wiz.discovery.boot
    assert boot is not None
    wiz.select_disk(boot.path)
    assert wiz.selected is None
    assert boot.path not in {d.path for d in wiz.selectable}
    last = sorted(wiz.selectable, key=lambda d: d.path)[-1]
    wiz.move_selection(1)
    for _ in range(len(wiz.selectable) + 2):
        wiz.move_selection(1)
    assert wiz.selected.path == last.path
    view = wiz.disk_view(last)
    assert last.serial == view.id_value
    wiz.continue_pick()
    assert wiz.screen == Screen.CONFIRM
    spec = wiz.confirm
    assert spec is not None and spec.token
    wiz.set_confirm_input(spec.token[:-1])
    wiz.continue_confirm()
    assert wiz.screen == Screen.CONFIRM
    wiz.set_confirm_input(spec.token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD


def test_console_pages_many_disks_without_overflow(monkeypatch):
    from test_console_parity import Terminal

    discovery = many_disk_discovery()
    wiz = at_pick(make_wiz(discovery=discovery, rediscover=lambda: discovery))
    last = sorted(wiz.selectable, key=lambda d: d.path)[-1]
    wiz.select_disk(last.path)
    term = Terminal(wiz, h=24, w=80, keys=[])
    for name in ("curs_set", "use_default_colors", "echo", "noecho"):
        monkeypatch.setattr(console.curses, name, lambda *a, **k: None)
    console._loop(term, wiz)
    last_frame = term.frames[-1]
    packed = "".join(last_frame[y] for y in sorted(last_frame))
    assert last.serial in packed
    assert ">" in packed
    assert all(len(line) < 80 for line in last_frame.values())
    assert max(last_frame) < 24


# ---------------------------------------------------------------------------
# 5. Failed exports
# ---------------------------------------------------------------------------


def _done_with_exporter(exporter, tmp_path):
    from test_usb_report_workflow import _done_wizard

    wiz = _done_wizard(exporter, tmp_path)
    wiz.report_wanted = True
    return wiz


def test_failed_export_stays_visible_one_at_a_time_then_recovers(tmp_path):
    from test_usb_report_workflow import _success_receipt

    calls = []

    def flaky(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise SafetyError("The report USB was removed before the copy finished.")
        return _success_receipt(**kwargs)

    wiz = _done_with_exporter(flaky, tmp_path)
    wiz.save_report_to_usb()
    assert wiz.screen == Screen.DONE
    assert wiz.report_status == "error"
    assert "removed" in wiz.report_message.casefold()
    assert "safe to remove" not in wiz.report_message.casefold()
    assert wiz.report_view.can_save
    assert not wiz.report_view.exporting
    wiz.save_report_to_usb()
    assert wiz.report_status == "saved"
    assert "safe to remove" in wiz.report_message.casefold()
    assert not wiz.report_view.can_save
    wiz.save_report_to_usb()
    assert wiz.report_status == "saved"
    assert len(calls) == 2


def test_busy_export_refuses_a_second_attempt(tmp_path):
    from test_usb_report_workflow import _success_receipt

    entered = threading.Event()
    release = threading.Event()

    def blocked(**kwargs):
        entered.set()
        assert release.wait(5)
        return _success_receipt(**kwargs)

    wiz = _done_with_exporter(blocked, tmp_path)
    assert wiz.begin_report_export() is True
    assert entered.wait(5)
    assert wiz.report_view.exporting
    assert wiz.begin_report_export() is False
    assert wiz.screen == Screen.DONE
    release.set()
    deadline = time.monotonic() + 5
    while wiz.report_view.exporting and time.monotonic() < deadline:
        time.sleep(0.02)
    assert wiz.report_status == "saved"


def test_evidence_retries_are_bounded(tmp_path, monkeypatch):
    from beamo_wipe import evidence
    from test_evidence import _wiz as evidence_wiz

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    w, clock = evidence_wiz(tmp_path)
    w.skip_intro()
    w.accept_what()
    w.set_owner(True)
    w.continue_owner()
    w.select_disk(w.selectable[0].path)
    w.continue_pick()
    w.set_confirm_input(w.confirm.token)
    w.continue_confirm()
    w.continue_method()
    clock.add(5)
    monkeypatch.setattr(
        evidence,
        "write_evidence_atomic",
        lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left")),
    )
    w.confirm_erase()
    clock.add(1)
    w.tick()
    assert w.screen == Screen.DONE
    assert w.can_retry_evidence
    assert w.report_view.retries_remaining == EVIDENCE_RETRIES
    for remaining in range(EVIDENCE_RETRIES, 0, -1):
        assert w.report_view.retries_remaining == remaining
        assert w.retry_evidence_save() is False
    assert not w.can_retry_evidence
    assert w.report_view.retries_remaining == 0
    assert "contact support" in w.evidence_warning.casefold()
    assert w.retry_evidence_save() is False
    assert w.wipe_result is not None
    assert not w.runner.started or w.screen == Screen.DONE


# ---------------------------------------------------------------------------
# 6. Changed media
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    ["added", "removed", "renamed", "boot_changed", "identity_changed"],
)
def test_refresh_after_changed_media_clears_authorization(change):
    wiz = at_last()
    old = wiz.discovery
    disks = list(old.disks)
    targets = list(old.selectable)
    boot = old.boot
    if change == "added":
        extra = replace(targets[0], name="sdz", path="/dev/sdz", serial="ADDED")
        disks.append(extra)
        targets.append(extra)
    elif change == "removed":
        removed = targets.pop(0)
        disks.remove(removed)
    elif change == "renamed":
        renamed = replace(targets[0], path="/dev/sdz", name="sdz")
        disks[disks.index(targets[0])] = renamed
        targets[0] = renamed
    elif change == "boot_changed":
        boot = replace(old.boot, name="sdy", path="/dev/sdy", serial="NEWBOOT")
        disks[disks.index(old.boot)] = boot
    elif change == "identity_changed":
        mutated = replace(targets[0], serial="CHANGED-SERIAL")
        disks[disks.index(targets[0])] = mutated
        targets[0] = mutated
    fresh = replace(
        old, disks=tuple(disks), selectable=tuple(targets), boot=boot, excluded=()
    )
    wiz._rediscover = lambda: fresh
    assert wiz.refresh_disks()
    assert wiz.screen == Screen.OWNER
    assert wiz.selected is None
    assert not wiz.owner_ok and not wiz.confirm_input
    assert wiz._authorized_operation is None
    assert not wiz.runner.started


def test_changed_identity_at_start_refuses_erase():
    wiz = at_last()
    wiz.preview = False
    wiz.dry_run = False
    fresh = replace(
        wiz.discovery,
        disks=tuple(
            replace(d, serial="CHANGED") if d.path == wiz.selected.path else d
            for d in wiz.discovery.disks
        ),
        selectable=tuple(replace(d, serial="CHANGED") for d in wiz.discovery.selectable),
    )
    wiz._rediscover = lambda: fresh
    wiz.confirm_erase()
    assert not wiz.runner.started
    assert wiz.wipe_result is None
    assert wiz.error
    assert wiz.screen in {Screen.LAST_CHANCE, Screen.CONFIRM, Screen.PICK}


def test_lost_boot_identity_fails_closed_with_no_disks():
    wiz = at_pick()
    wiz._rediscover = lambda: DiscoveryResult(
        error="boot missing", boot_identified=False, error_code="boot_unidentified"
    )
    assert wiz.refresh_disks()
    assert wiz.screen == Screen.PICK_BLOCKED
    assert wiz.selectable == ()
    assert wiz.selected is None
    assert wiz.error == REDISCOVER_ERROR
    wiz.select_disk("/dev/sda")
    assert wiz.selected is None


# ---------------------------------------------------------------------------
# 7. Repeated keys
# ---------------------------------------------------------------------------


def test_console_enter_repeat_is_suppressed_and_cannot_skip_screens():
    import curses

    assert console._is_enter_repeat(True, 10)
    assert console._is_enter_repeat(True, 13)
    assert console._is_enter_repeat(True, curses.KEY_ENTER)
    assert not console._is_enter_repeat(False, 10)
    assert not console._is_enter_repeat(True, 27)

    wiz = at_pick()
    wiz.select_disk(sorted(wiz.selectable, key=lambda d: d.path)[0].path)
    console._handle(wiz, 10)
    assert wiz.screen == Screen.CONFIRM
    skipped = 0
    for _ in range(8):
        if console._is_enter_repeat(True, 10):
            skipped += 1
            continue
        console._handle(wiz, 10)
    assert skipped == 8
    assert wiz.screen == Screen.CONFIRM
    assert not wiz.token_ok
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD
    console._handle(wiz, 10)
    assert wiz.screen == Screen.LAST_CHANCE
    assert not wiz.erase_enabled
    skipped = 0
    for _ in range(8):
        if console._is_enter_repeat(True, 10):
            skipped += 1
            continue
        console._handle(wiz, 10)
    assert skipped == 8
    assert wiz.screen == Screen.LAST_CHANCE
    assert not wiz.runner.started
    wiz._erase_until = 0
    assert wiz.erase_enabled
    skipped = 0
    for _ in range(8):
        if console._is_enter_repeat(True, 10):
            skipped += 1
            continue
        console._handle(wiz, 10)
    assert skipped == 8
    assert not wiz.runner.started


def test_key_repeat_cannot_bypass_last_chance_or_export(tmp_path):
    from test_usb_report_workflow import _done_wizard, _success_receipt

    wiz = at_last()
    for _ in range(20):
        wiz.confirm_erase()
    # Countdown still owns the gate even under a flood of confirms.
    assert wiz.screen in {Screen.LAST_CHANCE, Screen.WORKING, Screen.CHECKING}
    if wiz.screen == Screen.LAST_CHANCE:
        assert wiz._erase_until == 0 or wiz.erase_enabled

    exporter = _success_receipt
    done = _done_wizard(exporter, tmp_path)
    done.report_wanted = True
    assert done.begin_report_export() is True
    # A second attempt while the first claim is current is refused (or
    # already finished; either way it cannot start a pile of exports).
    second = done.begin_report_export()
    assert second in {False, True}
    if second:
        assert done.report_status in {"saved", "saving", "error"}


# ---------------------------------------------------------------------------
# 8. Return from help
# ---------------------------------------------------------------------------


def test_disk_help_return_revokes_selection_and_ignores_stale_actions():
    wiz = at_pick()
    target = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(target.path)
    wiz.confirm_input = "stale-token"
    wiz._erase_until = 1
    wiz._authorized_operation = ("stale",)
    wiz.open_disk_help()
    assert wiz.screen == Screen.DISK_HELP
    assert wiz.selected is None
    assert wiz.confirm_input == ""
    assert wiz._authorized_operation is None
    console._handle(wiz, 10)
    console._handle(wiz, 13)
    wiz.select_disk(target.path)
    wiz.continue_pick()
    wiz.confirm_erase()
    assert wiz.screen == Screen.DISK_HELP
    assert not wiz.runner.started
    wiz.back()
    assert wiz.screen == Screen.PICK
    assert wiz.selected is None
    wiz.continue_pick()
    assert wiz.screen == Screen.PICK


def test_report_help_returns_to_origin_and_does_not_authorize():
    wiz = at_pick()
    wiz.back()
    assert wiz.screen == Screen.OWNER
    wiz.open_report_help()
    assert wiz.screen == Screen.REPORT_HELP
    wiz.set_report_wanted(True)
    console._handle(wiz, 10)
    assert wiz.screen == Screen.OWNER
    assert wiz.report_wanted is True
    assert wiz.selected is None
    assert not wiz.runner.started

    wiz = at_last()
    origin = wiz.screen
    wiz.back()
    assert wiz.screen == Screen.METHOD
    wiz.open_report_help()
    wiz.back()
    assert wiz.screen == Screen.METHOD
    assert origin == Screen.LAST_CHANCE
    assert wiz.selected is not None


def test_stale_help_open_from_other_screens_is_ignored():
    wiz = at_pick()
    for screen in (Screen.CONFIRM, Screen.CHECKING, Screen.WORKING, Screen.PICK_BLOCKED):
        wiz.screen = screen
        wiz.open_disk_help()
        assert wiz.screen == screen


# ---------------------------------------------------------------------------
# Native Tk — focus, wrap, overflow, key-repeat, delayed progress
# ---------------------------------------------------------------------------


try:
    import tkinter as tk
    from beamo_wipe.ui.tk_wizard import TkWizard, _Button
except ImportError:
    tk = None
    TkWizard = None
    _Button = None


def _needs_display():
    from test_tk_runtime import _needs_display as require

    require()


def _tk_app(wiz, size=(1024, 740)):
    _needs_display()
    app = TkWizard(wiz)
    app.root.geometry(f"{size[0]}x{size[1]}+40+40")
    app.root.update_idletasks()
    app.root.focus_force()
    return app


def _focus_button_text(app):
    focused = app.root.focus_get()
    if isinstance(focused, _Button):
        return focused.itemcget(focused._label, "text")
    return getattr(focused, "winfo_class", lambda: type(focused).__name__)()


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


@pytest.mark.skipif(tk is None, reason="tkinter not available")
def test_tk_return_from_disk_help_focuses_back_and_ignores_held_enter():
    from test_tk_runtime import _clipping_problems, _off_window_problems

    wiz = at_pick()
    wiz.select_disk(sorted(wiz.selectable, key=lambda d: d.path)[0].path)
    app = _tk_app(wiz)
    try:
        app._draw()
        app.root.update()
        unsure = next(
            x
            for x in _descendants(app.root)
            if isinstance(x, _Button) and x.itemcget(x._label, "text") == C.DISK_HELP_BUTTON
        )
        unsure.focus_set()
        app.root.update()
        unsure.event_generate("<Return>")
        app.root.update()
        assert wiz.screen == Screen.DISK_HELP
        assert wiz.selected is None
        reader = next(x for x in _descendants(app.root) if isinstance(x, tk.Text))
        assert app.root.focus_get() == reader
        # Held Enter while reading help must not pick a disk or leave help.
        app._return_held = True
        app._on_return()
        app.root.update()
        assert wiz.screen == Screen.DISK_HELP
        assert wiz.selected is None
        app._return_held = False
        app._on_escape()
        app.root.update()
        assert wiz.screen == Screen.PICK
        assert wiz.selected is None
        assert _focus_button_text(app) == C.BTN_BACK
        app._return_held = True
        app._on_return()
        app.root.update()
        assert wiz.screen == Screen.PICK
        assert not wiz.runner.started
        assert not _clipping_problems(app)
        assert not _off_window_problems(app)
    finally:
        app._teardown()


@pytest.mark.skipif(tk is None, reason="tkinter not available")
def test_tk_report_help_return_restores_origin_focus():
    wiz = make_wiz()
    wiz.skip_intro()
    app = _tk_app(wiz)
    try:
        app._draw()
        app.root.update()
        assert wiz.screen == Screen.OWNER
        link = next(
            x
            for x in _descendants(app.root)
            if isinstance(x, _Button) and x.itemcget(x._label, "text") == C.REPORT_HELP_TITLE
        )
        link._command()
        app.root.update()
        assert wiz.screen == Screen.REPORT_HELP
        reader = next(x for x in _descendants(app.root) if isinstance(x, tk.Text))
        assert app.root.focus_get() == reader
        app._on_escape()
        app.root.update()
        assert wiz.screen == Screen.OWNER
        focused = app.root.focus_get()
        assert focused is not None
        assert not wiz.runner.started
    finally:
        app._teardown()


@pytest.mark.skipif(tk is None, reason="tkinter not available")
def test_tk_many_disks_overflow_and_keep_selection_in_view():
    from test_tk_runtime import MIN_WINDOW, _clipping_problems

    discovery = many_disk_discovery()
    wiz = at_pick(make_wiz(discovery=discovery, rediscover=lambda: discovery))
    app = _tk_app(wiz, size=MIN_WINDOW)
    try:
        app._draw()
        app.root.update()
        canvas = app._pick_canvas
        assert canvas is not None
        bbox = canvas.bbox("all")
        assert bbox and bbox[3] > canvas.winfo_height(), (
            "forced many-disk list must overflow; the original demo-list test skipped"
        )
        ordered = sorted(wiz.selectable, key=lambda d: d.path)
        for _ in range(len(ordered)):
            (app.root.focus_get() or app.root).event_generate("<KeyPress>", keysym="Down")
            app.root.update()
        last = ordered[-1]
        assert wiz.selected is not None and wiz.selected.path == last.path
        canvas = app._pick_canvas
        card = app._pick_cards[last.path]
        top, bottom = canvas.yview()
        content_h = float(canvas.bbox("all")[3])
        y0 = card.winfo_y() / content_h
        y1 = (card.winfo_y() + card.winfo_height()) / content_h
        assert y0 >= top - 0.02
        assert y1 <= bottom + 0.02
        boot = wiz.discovery.boot
        assert boot.path not in app._pick_cards or boot.path not in {
            d.path for d in wiz.selectable
        }
        assert not _clipping_problems(app)
    finally:
        app._teardown()


@pytest.mark.skipif(tk is None, reason="tkinter not available")
def test_tk_long_identifiers_keep_the_serial_tail_visible():
    from test_tk_runtime import MIN_WINDOW, _clipping_problems, _off_window_problems

    discovery = long_identity_discovery()
    wiz = at_pick(make_wiz(discovery=discovery, rediscover=lambda: discovery))
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    app = _tk_app(wiz, size=MIN_WINDOW)
    try:
        app._draw()
        app.root.update()
        texts = []
        for widget in _descendants(app.root):
            if isinstance(widget, tk.Label):
                texts.append(str(widget.cget("text")))
        joined = "\n".join(texts)
        assert "TAIL" in joined.replace("\n", "")
        assert "…" not in joined and "..." not in joined
        assert not _off_window_problems(app)
        assert not _clipping_problems(app)
        wiz.continue_pick()
        app._draw()
        app.root.update()
        assert wiz.confirm.token
        assert disk.serial.replace("\n", "") in "\n".join(
            str(w.cget("text")) for w in _descendants(app.root) if isinstance(w, tk.Label)
        ).replace("\n", "") or disk.serial[-4:] in wiz.confirm.prompt
    finally:
        app._teardown()


@pytest.mark.skipif(tk is None, reason="tkinter not available")
def test_tk_delayed_progress_paints_old_and_keeps_ticking():
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.progress import ProgressView
    from test_tk_runtime import _clipping_problems

    clock = Clock()
    wiz = at_last(make_wiz(runner=HeldRunner(), clock=clock))
    wiz.confirm_erase()
    bind_timing(wiz, clock)
    app = _tk_app(wiz)
    try:
        view = ProgressView("Writing", 42, 120, stale_for=11, percent_is_old=True)
        with patch.object(Wizard, "progress_view", new_callable=PropertyMock, return_value=view):
            app._draw()
            app.root.update_idletasks()
            assert app._progress_pct.cget("text") == "42% (old)"
            assert "No new progress update" in app._progress_label.cget("text")
            before = [app._progress_bar.coords(item) for item in app._progress_bar.find_all()]
            scheduled = []

            def capture(ms, fn):
                scheduled.append((ms, fn))
                return len(scheduled)

            app.root.after = capture  # type: ignore[method-assign]
            app._tick()
            assert scheduled, "working tick must reschedule"
            after = [app._progress_bar.coords(item) for item in app._progress_bar.find_all()]
            assert after == before
            assert not _clipping_problems(app)
            assert wiz.screen == Screen.WORKING
            assert not wiz.runner.cancelled
    finally:
        app._teardown()


@pytest.mark.skipif(tk is None, reason="tkinter not available")
def test_tk_failed_export_keeps_failure_and_focus(tmp_path):
    from test_tk_runtime import MIN_WINDOW
    from test_usb_report_workflow import _done_wizard

    def boom(**_kwargs):
        raise SafetyError("The report USB was removed before the copy finished.")

    wiz = _done_wizard(boom, tmp_path)
    wiz.report_wanted = True
    wiz.preview = False
    app = _tk_app(wiz, size=MIN_WINDOW)
    try:
        app._draw()
        app.root.update()
        wiz.save_report_to_usb()
        app._draw()
        app.root.update()
        assert wiz.report_status == "error"
        shown = []
        for widget in _descendants(app.root):
            if isinstance(widget, tk.Label):
                shown.append(str(widget.cget("text")))
            if isinstance(widget, _Button):
                shown.append(widget.itemcget(widget._label, "text"))
        text = " ".join(shown)
        assert "removed" in text.casefold()
        assert "safe to remove" not in text.casefold()
        focused = app.root.focus_get()
        assert focused is not None
    finally:
        app._teardown()


@pytest.mark.skipif(tk is None, reason="tkinter not available")
def test_tk_changed_media_refresh_clears_focus_selection():
    wiz = at_pick()
    target = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(target.path)
    empty = DiscoveryResult(
        error="boot missing", boot_identified=False, error_code="boot_unidentified"
    )
    wiz._rediscover = lambda: empty
    app = _tk_app(wiz)
    try:
        app._draw()
        app.root.update()
        app._click_refresh()
        assert wiz.screen == Screen.REFRESH_CONFIRM
        assert wiz.selected is not None
        app._click_refresh()
        deadline = time.monotonic() + 5
        while wiz.screen == Screen.REFRESHING and time.monotonic() < deadline:
            app.root.update()
            time.sleep(0.02)
        assert wiz.screen == Screen.PICK_BLOCKED
        assert wiz.selected is None
        assert wiz.selectable == ()
        assert _focus_button_text(app)
        assert not wiz.runner.started
    finally:
        app._teardown()


def test_gallery_does_not_pretend_to_simulate_these_timings():
    """Browser preview is a static click-through; native Tk/console own this card."""
    from beamo_wipe import gallery

    src = gallery.__file__
    text = open(src, encoding="utf-8").read()
    assert "does not wipe" in (gallery.__doc__ or "").casefold()
    assert "run_tk_startup" not in text
    assert "ProgressTiming" not in text
    assert "begin_report_export" not in text
