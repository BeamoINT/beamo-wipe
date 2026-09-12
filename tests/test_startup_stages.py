# SPDX-License-Identifier: GPL-3.0-or-later
"""Startup stages (#53): truthful progress before the wizard opens.

All disks and processes are fake. The Tk splash and GTK stage window need
a real display, so they are not exercised here; this file pins the shared
model every surface builds on — stage order, worker discipline, the
discover hook, serial evidence, and the console sequencing — plus the
plain-language copy contract: stages describe work in progress and never
claim a safety check has passed.
"""

from __future__ import annotations

import json
import threading
from argparse import Namespace
from pathlib import Path

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.startup_stages import (
    STAGE_BOOT_USB,
    STAGE_FINDING,
    STAGE_STARTING,
    STAGES,
    StartupRun,
    StartupStages,
    complete_synchronously,
)


def _stages(monkeypatch):
    """Capture serial markers emitted by the startup model."""
    import beamo_wipe.diagnostics as diagnostics

    markers = []
    monkeypatch.setattr(diagnostics, "emit_serial_marker", markers.append)
    return markers


def test_stages_begin_in_order_and_mark_only_ended_stages_done(monkeypatch):
    markers = _stages(monkeypatch)
    stages = StartupStages()
    assert stages.active == STAGE_STARTING
    assert all(stages.states[key] == "pending" for key in STAGES[1:])

    assert stages.begin(STAGE_BOOT_USB) is True
    assert stages.states[STAGE_STARTING] == "done"
    assert stages.active == STAGE_BOOT_USB

    assert stages.begin(STAGE_FINDING) is True
    assert stages.states[STAGE_BOOT_USB] == "done"
    assert stages.active == STAGE_FINDING

    stages.succeed()
    assert stages.done and all(state == "done" for state in stages.states.values())
    assert markers == [
        "BEAMO_WIPE_STAGE_STARTING",
        "BEAMO_WIPE_STAGE_BOOT_USB",
        "BEAMO_WIPE_STAGE_FINDING",
        "BEAMO_WIPE_STAGE_DONE",
    ]


def test_failed_startup_marks_nothing_further_done(monkeypatch):
    markers = _stages(monkeypatch)
    stages = StartupStages()
    stages.begin(STAGE_BOOT_USB)
    stages.fail()
    assert stages.failed and not stages.done
    # The interrupted stage stays exactly as it was: a failure can never
    # look like a passed check, and later stages stay pending.
    assert stages.states[STAGE_BOOT_USB] == "active"
    assert stages.states[STAGE_FINDING] == "pending"
    assert stages.begin(STAGE_FINDING) is False
    assert markers[-1] == "BEAMO_WIPE_STAGE_FAILED"
    assert "BEAMO_WIPE_STAGE_DONE" not in markers


def test_unknown_stage_is_a_programming_error():
    stages = StartupStages()
    try:
        stages.begin("polishing-disks")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown stage must raise, not stick the display")


def test_stall_note_fires_once_after_threshold(monkeypatch):
    markers = _stages(monkeypatch)
    now = [100.0]
    stages = StartupStages(clock=lambda: now[0], stall_after_s=10.0)
    assert stages.stalled() is False
    now[0] += 9.9
    assert stages.stalled() is False
    now[0] += 0.2
    run = StartupRun(lambda report: None, clock=lambda: now[0], stall_after_s=10.0)
    assert run.stalled_note() is None  # fresh run sits below its own threshold
    assert stages.stalled() is True
    assert stages.stalled() is False  # one note per stage, then quiet
    assert markers.count("BEAMO_WIPE_STAGE_STALLED") == 1


def _pump(run, timeout_s=10.0):
    """Drive the UI-thread side until the worker finishes; return outcome."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run.drain()
        outcome = run.poll()
        if outcome is not None:
            return outcome
    raise AssertionError("startup worker did not finish")


def test_slow_discovery_reports_each_stage_before_the_wizard():
    import time

    # The worker/UI-thread handoff has a real race (a terminal outcome
    # landing between the last drain and its observation), so repeat the
    # handshake: every round must show ordered stages mid-flight and a
    # fully-done model once the wizard arrives.
    for _round in range(15):
        at_boot = threading.Event()
        proceed = threading.Event()

        def slow_build(report):
            report(STAGE_BOOT_USB)
            at_boot.set()
            proceed.wait(timeout=10)
            report(STAGE_FINDING)
            return "wizard-sentinel"

        run = StartupRun(slow_build)
        run.start()
        try:
            assert at_boot.wait(timeout=10)
            deadline = time.monotonic() + 10.0
            snapshot = {}
            while time.monotonic() < deadline:
                snapshot = {row["key"]: row["state"] for row in run.drain()}
                if snapshot.get(STAGE_BOOT_USB) == "active":
                    break
            assert snapshot.get(STAGE_BOOT_USB) == "active"
            assert snapshot.get(STAGE_FINDING) == "pending"
            assert run.poll() is None  # still working: no wizard yet
            proceed.set()
            assert _pump(run) == ("wizard", "wizard-sentinel")
        finally:
            proceed.set()
        assert all(state == "done" for state in run.stages.states.values())


def test_failed_discovery_returns_the_error_and_holds_later_stages():
    failure = OSError("lsblk gone")

    def broken_build(report):
        report(STAGE_BOOT_USB)
        raise failure

    run = StartupRun(broken_build)
    run.start()
    assert _pump(run) == ("failed", failure)
    assert run.stages.failed
    assert run.stages.states[STAGE_FINDING] == "pending"


def test_complete_synchronously_matches_presenter_protocol():
    assert complete_synchronously(lambda report: "w") == ("wizard", "w")
    failure = RuntimeError("nope")
    kind, payload = complete_synchronously(lambda report: (_ for _ in ()).throw(failure))
    assert kind == "failed" and payload is failure


def test_startup_copy_never_claims_a_passed_check():
    assert (C.STARTUP_TITLE, C.STARTUP_TITLE_HINT) == ("Starting Beamo Wipe", "Getting ready.")
    assert C.STARTUP_STAGE_BOOT_USB == "Checking the boot USB"
    assert C.STARTUP_STAGE_FINDING == "Finding disks"
    lines = [
        C.STARTUP_TITLE,
        C.STARTUP_TITLE_HINT,
        C.STARTUP_STAGE_BOOT_USB,
        C.STARTUP_STAGE_BOOT_USB_HINT,
        C.STARTUP_STAGE_FINDING,
        C.STARTUP_STAGE_FINDING_HINT,
        C.STARTUP_STILL_WORKING,
    ]
    banned = ("passed", "complete", "success", "verified", "secure", "okay")
    for line in lines:
        lowered = line.lower()
        assert not any(word in lowered for word in banned), line
    # Progressive tense only: the work is under way, not finished.
    assert "Checking" in C.STARTUP_STAGE_BOOT_USB
    assert "Finding" in C.STARTUP_STAGE_FINDING


def test_discover_reports_boot_usb_then_finding_on_the_live_path(monkeypatch):
    import beamo_wipe.discover as discovery

    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "lsblk_same_size.json").read_text()
    )
    monkeypatch.setattr(discovery, "run_lsblk", lambda: fixture)
    seen = []
    result = discovery.discover(
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
        progress=seen.append,
    )
    assert seen == [STAGE_BOOT_USB, STAGE_FINDING]
    assert result.boot_identified


def test_discover_reports_both_stages_before_a_failure(monkeypatch):
    import beamo_wipe.discover as discovery

    def gone():
        raise OSError("lsblk gone")

    monkeypatch.setattr(discovery, "run_lsblk", gone)
    seen = []
    result = discovery.discover(
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
        progress=seen.append,
    )
    assert seen == [STAGE_BOOT_USB, STAGE_FINDING]
    assert not result.boot_identified


def test_console_startup_prints_stages_in_order_then_returns_wizard(monkeypatch, capsys):
    from beamo_wipe import app

    def slow_build(args, progress=None):
        assert callable(progress)
        progress(STAGE_BOOT_USB)
        progress(STAGE_FINDING)
        return "wizard-sentinel"

    monkeypatch.setattr(app, "_build_wizard", slow_build)
    assert app._build_wizard_with_console_stages(Namespace()) == "wizard-sentinel"
    out = capsys.readouterr().out
    positions = [out.index(title) for title in (C.STARTUP_TITLE, C.STARTUP_STAGE_BOOT_USB, C.STARTUP_STAGE_FINDING)]
    assert positions == sorted(positions)


def test_console_startup_failure_stays_blocked_with_support_reachable(monkeypatch, capsys):
    from beamo_wipe import app

    def broken_build(args, progress=None):
        raise OSError("discovery crash")

    monkeypatch.setattr(app, "_build_wizard", broken_build)
    wizard = app._build_wizard_with_console_stages(Namespace())
    assert wizard._startup_blocked
    assert wizard.screen == Screen.PICK_BLOCKED
    assert wizard.can_open_diagnostic
    assert "Startup blocked" in capsys.readouterr().err
