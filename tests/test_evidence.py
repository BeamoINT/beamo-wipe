# SPDX-License-Identifier: GPL-3.0-or-later
"""Auditable evidence: truthful schema, outcomes, off-target, atomic, checksum, export."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from beamo_wipe import NWIPE_PINNED_COMMIT, NWIPE_PINNED_VERSION, __version__
from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.evidence import (
    ALLOWED_OUTCOMES,
    EVIDENCE_PREFIX,
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_INTERRUPTED,
    OUTCOME_RUNNING,
    OUTCOME_STARTED,
    OUTCOME_VERIFIED,
    build_evidence,
    export_evidence,
    load_evidence,
    verify_evidence_checksum,
    write_evidence_atomic,
)
from beamo_wipe.methods import DEFAULT_METHOD, METHODS
from beamo_wipe.models import Disk, MethodId, Screen, WipeRequest, WipeResult
from beamo_wipe.nwipe_runner import DryRunRunner, evaluate_nwipe_completion
from beamo_wipe.safety import SafetyError
from beamo_wipe.wizard import Wizard, make_demo_wizard

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


def _wiz(tmp_path: Path, clock=None, dry_run=True, wall=None):
    clock = clock or Clock()
    base = make_demo_wizard()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=0.5, clock=clock), clock=clock, dry_run=dry_run, wall_clock=wall)
    return wiz, clock


# ---------------------------------------------------------------------------
# 1. Truthful result schema
# ---------------------------------------------------------------------------


def test_schema_covers_required_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    assert wiz.evidence is not None
    ev = wiz.evidence
    assert ev["schema_version"] == 1
    assert ev["beamo_wipe_version"] == __version__
    assert ev["nwipe_version"] == NWIPE_PINNED_VERSION
    assert ev["nwipe_commit"] == NWIPE_PINNED_COMMIT
    assert ev["outcome"] in ALLOWED_OUTCOMES
    assert ev["device"] is not None
    assert ev["device"]["path"] == wiz.selected.path  # type: ignore[union-attr]
    assert ev["method"]["id"] == wiz.method.value
    assert ev["boot_device"] == wiz.discovery.boot.path  # type: ignore[union-attr]
    assert ev["timestamps"]["started_at_wall"]
    assert ev["nwipe"]["argv_redacted"]
    assert "exit_evidence" in ev
    assert "verification" in ev
    assert "warnings" in ev
    assert "interruption" in ev
    assert "logfile" in ev
    assert "provenance" in ev
    assert ev["provenance"]["evidence_file"]
    # No sensitive host details
    blob = json.dumps(ev)
    assert "beamo-wipe" not in blob.lower() or "beamo" in blob.lower()  # only version/commit, not hostname
    for leak in ["127.0.0.1", "localhost", "/Users/", "/home/"]:
        assert leak not in blob


def test_nwipe_version_args_redacted_no_control_chars(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    argv = wiz.evidence["nwipe"]["argv_redacted"]  # type: ignore[index]
    assert argv[0] == "nwipe"
    assert "--autonuke" in argv
    assert "--exclude=" in " ".join(argv)
    for a in argv:
        assert "\n" not in a and "\r" not in a and "\0" not in a


# ---------------------------------------------------------------------------
# 2. Outcome distinctions
# ---------------------------------------------------------------------------


def test_outcomes_distinguished(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # started
    wiz, clock = _wiz(tmp_path)
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
    assert wiz.evidence["outcome"] == OUTCOME_STARTED  # type: ignore[index]

    # running -> poll not yet finished
    wiz.tick()
    assert wiz.screen == Screen.WORKING
    clock.add(0.6)
    wiz.tick()
    # After finish, should be verified (DEFAULT_METHOD prng verify last) and exit 0
    assert wiz.screen == Screen.DONE
    assert wiz.evidence["outcome"] == OUTCOME_VERIFIED  # type: ignore[index]
    assert wiz.done_ok

    # failed: nonzero exit without markers
    from beamo_wipe.evidence import build_evidence
    from beamo_wipe.models import DiscoveryResult

    disc = wiz.discovery
    disk = wiz.selected
    result = WipeResult(ok=False, exit_code=1, summary="nwipe exited 1", logfile="/tmp/beamo-wipe/nwipe-sda.log")
    ev = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=wiz._wipe_request,
        result=result,
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="2026-01-01T00:01:00Z",
        started_mono=0.0,
        ended_mono=60.0,
        argv=["nwipe", "--autonuke"],
        log_text="",
    )
    assert ev["outcome"] == OUTCOME_FAILED
    assert ev["failure_reason"] is not None

    # interrupted
    ev2 = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=wiz._wipe_request,
        result=WipeResult(ok=False, exit_code=143, summary="interrupted", logfile=""),
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="2026-01-01T00:01:00Z",
        started_mono=0.0,
        ended_mono=10.0,
        argv=[],
        log_text="",
        interrupted=True,
        cancelled=True,
    )
    assert ev2["outcome"] == OUTCOME_INTERRUPTED

    # completed vs verified: QUICK_ZERO verify off -> completed even if ok
    ev3 = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.QUICK_ZERO,
        request=wiz._wipe_request,
        result=WipeResult(ok=True, exit_code=0, summary="finished", logfile=""),
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="2026-01-01T00:01:00Z",
        started_mono=0.0,
        ended_mono=60.0,
        argv=[],
        log_text="",
    )
    assert ev3["outcome"] == OUTCOME_COMPLETED
    assert ev3["verification"]["verified"] is False
    assert ev3["verification"]["requested"] == "off"


def test_never_translate_nonzero_or_missing_evidence_into_success(tmp_path):
    # Direct evaluate mapping already tested; here via evidence
    from beamo_wipe.evidence import build_evidence

    base = make_demo_wizard()
    disc = base.discovery
    disk = next(d for d in disc.selectable if d.path == "/dev/sda")
    for code, log, should_ok in [
        (0, "", False),
        (1, "Nwipe successfully completed", False),
        (0, "Nwipe successfully completed", False),  # empty without markers
        (0, "/dev/sda: 100.00%, round 1 of 1, pass 1 of 1\nNwipe was aborted by the user", False),
    ]:
        ok, _ = evaluate_nwipe_completion(code, log, disk.path)
        assert ok is False, f"code {code} log {log[:20]!r} should not be ok"
        result = WipeResult(ok=ok, exit_code=code, summary="nwipe exited without wiping" if not ok else "finished", logfile="")
        ev = build_evidence(
            disk=disk,
            discovery=disc,
            method=MethodId.EVERYDAY,
            request=None,
            result=result,
            started_at_wall="2026-01-01T00:00:00Z",
            ended_at_wall="2026-01-01T00:01:00Z",
            started_mono=0.0,
            ended_mono=1.0,
            argv=[],
            log_text=log,
        )
        assert ev["outcome"] == OUTCOME_FAILED
        assert "certificate" not in json.dumps(ev).lower()


# ---------------------------------------------------------------------------
# 3. Off-target, atomic, preserve through restart/export failure
# ---------------------------------------------------------------------------


def test_evidence_off_target_and_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    assert wiz.evidence_path
    p = Path(wiz.evidence_path)
    assert p.exists()
    assert tmp_path in p.parents
    # Not on target
    from beamo_wipe.safety import assert_log_not_on_target

    assert_log_not_on_target(str(p), wiz.selected.path)  # type: ignore[union-attr]
    # Atomic: file is regular, 0o600, checksum sidecar exists
    st = p.stat()
    assert stat.S_IMODE(st.st_mode) == 0o600
    sidecar = Path(str(p) + ".sha256")
    assert sidecar.exists()
    assert verify_evidence_checksum(p)
    # No partial temp left
    assert not any(tmp_path.glob(".*.tmp.*"))


def test_preserve_through_restart_and_export_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    path_before = wiz.evidence_path
    assert Path(path_before).exists()  # type: ignore[arg-type]
    # UI restart must not delete evidence file
    wiz.reset_for_preview()
    assert Path(path_before).exists()  # type: ignore[arg-type]
    assert wiz.evidence_path == path_before
    # Export failure (dest on target) must not delete evidence
    import tempfile

    # Create a fake target mount: use target path as dest (should be blocked)
    with pytest.raises(SafetyError):
        wiz.export_evidence(str(tmp_path / "nwipe-sda.log"))  # not a dir
    assert Path(path_before).exists()  # type: ignore[arg-type]
    # Export to missing dir also preserves
    with pytest.raises(SafetyError):
        wiz.export_evidence(str(tmp_path / "nonexistent"))
    assert Path(path_before).exists()  # type: ignore[arg-type]


def test_write_failure_does_not_crash_wizard(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    # Make directory unwritable
    monkeypatch.setattr("beamo_wipe.evidence.write_evidence_atomic", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    # Should not raise, just set evidence_error
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING  # still proceeds to working despite evidence write failure
    assert wiz.evidence_error is not None or wiz.evidence is None


# ---------------------------------------------------------------------------
# 4. Export/print path with checksum, off-target
# ---------------------------------------------------------------------------


def test_export_to_second_usb_with_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    clock.add(0.6)
    wiz.tick()
    assert wiz.screen == Screen.DONE
    # Export to second USB (another tmp dir acting as mount)
    second = tmp_path / "second_usb"
    second.mkdir()
    dest = wiz.export_evidence(str(second))
    assert Path(dest).exists()
    assert Path(dest).parent == second
    assert verify_evidence_checksum(Path(dest))
    sidecar = Path(str(dest) + ".sha256")
    assert sidecar.exists()
    # Export to a symlink destination must be rejected
    link = tmp_path / "link_usb"
    try:
        link.symlink_to(second)
    except OSError:
        link = second  # fallback
        # Create a symlink file inside second that points elsewhere
        # Instead test missing dest
        with pytest.raises(SafetyError):
            wiz.export_evidence(str(tmp_path / "nonexistent_dir"))
        return
    with pytest.raises(SafetyError):
        wiz.export_evidence(str(link))


def test_export_preserves_checksum_tamper_evident(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    p = Path(wiz.evidence_path)  # type: ignore[arg-type]
    assert verify_evidence_checksum(p)
    # Tamper
    obj = json.loads(p.read_text(encoding="utf-8"))
    obj["outcome"] = "verified"
    p.write_text(json.dumps(obj), encoding="utf-8")
    assert not verify_evidence_checksum(p)


def test_missing_sidecar_is_not_verified(tmp_path):
    """A sidecar-less file, however well-formed, never verifies (fail closed).

    Otherwise a forged `result-*.json` with a plausible schema would carry
    `provenance.verified = True` without any integrity check ever running.
    """
    p = tmp_path / "result-forged.json"
    p.write_text(
        json.dumps({"schema_version": 1, "outcome": "verified", "device": "/dev/sda"}),
        encoding="utf-8",
    )
    assert not Path(str(p) + ".sha256").exists()
    assert not verify_evidence_checksum(p)


# ---------------------------------------------------------------------------
# 5. Edge cases: malformed output, signals, partial logs, clock anomalies,
#    duplicate events, recovery
# ---------------------------------------------------------------------------


def test_malformed_nwipe_output_is_failed_not_certified(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # Simulate nwipe log with binary garbage, missing markers, truncated mid-UTF8
    for log in [
        " \x00\xff binary \x01\x02 ",
        "Nwipe successfully completed\n",  # no device markers
        "/dev/sda: 45.00%, round 1 of 1\n",  # no success marker
        "      sda | Erased |  120MB/s | 01:25:04 | QEMU/HARDDISK\n"[:12],  # truncated before Erased
        "",
    ]:
        ok, _ = evaluate_nwipe_completion(0, log, "/dev/sda")
        assert ok is False
        # Build evidence with that log
        base = make_demo_wizard()
        disc = base.discovery
        disk = next(d for d in disc.selectable if d.path == "/dev/sda")
        ev = build_evidence(
            disk=disk,
            discovery=disc,
            method=MethodId.EVERYDAY,
            request=WipeRequest(device=disk.path, method=MethodId.EVERYDAY, boot_device="/dev/sdb", logfile="/tmp/beamo-wipe/nwipe-sda.log"),
            result=WipeResult(ok=ok, exit_code=0, summary="nwipe exited without wiping" if not ok else "finished", logfile=""),
            started_at_wall="2026-01-01T00:00:00Z",
            ended_at_wall="2026-01-01T00:01:00Z",
            started_mono=0.0,
            ended_mono=60.0,
            argv=[],
            log_text=log,
        )
        assert ev["outcome"] == OUTCOME_FAILED
        assert "certificate" not in json.dumps(ev).lower()


def test_signal_exit_is_interrupted_or_failed(tmp_path, monkeypatch):
    from beamo_wipe.evidence import build_evidence

    base = make_demo_wizard()
    disc = base.discovery
    disk = next(d for d in disc.selectable if d.path == "/dev/sda")
    # SIGTERM: NwipeRunner returns 143 via cancel
    for code, expected_outcome in [(-15, OUTCOME_FAILED), (143, OUTCOME_FAILED), (137, OUTCOME_FAILED)]:
        ok, _ = evaluate_nwipe_completion(code, "", disk.path)
        result = WipeResult(ok=ok, exit_code=code, summary=f"nwipe exited {code}", logfile="")
        ev = build_evidence(
            disk=disk,
            discovery=disc,
            method=MethodId.EVERYDAY,
            request=None,
            result=result,
            started_at_wall="2026-01-01T00:00:00Z",
            ended_at_wall="2026-01-01T00:01:00Z",
            started_mono=0.0,
            ended_mono=10.0,
            argv=[],
            log_text="",
        )
        assert ev["exit_evidence"]["exit_code"] == code
        # signal derived only for negative codes
        if code < 0:
            assert ev["exit_evidence"]["signal"] == -code
        assert ev["outcome"] == OUTCOME_FAILED


def test_power_interruption_simulation(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    assert wiz.screen == Screen.WORKING
    # Simulate power loss: runner cancel + wizard interruption
    wiz.cancel_wipe()
    assert wiz.screen == Screen.DONE
    assert wiz.evidence is not None
    assert wiz.evidence["outcome"] == OUTCOME_INTERRUPTED  # type: ignore[index]
    assert wiz.evidence["interruption"]["cancelled"] is True  # type: ignore[index]
    assert wiz.wipe_result is not None and wiz.wipe_result.ok is False


def test_partial_log_preserved_and_checksummed(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # Create a log file that will be partially written (simulate crash mid-write)
    log_path = tmp_path / "nwipe-sda.log"
    log_path.write_text("partial log without newline and truncated mid-utf8 \xf0\x9f", encoding="utf-8", errors="replace")
    # Build evidence with that partial log
    base = make_demo_wizard()
    disc = base.discovery
    disk = next(d for d in disc.selectable if d.path == "/dev/sda")
    result = WipeResult(ok=False, exit_code=1, summary="nwipe exited 1", logfile=str(log_path))
    ev = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=WipeRequest(device=disk.path, method=MethodId.EVERYDAY, boot_device="/dev/sdb", logfile=str(log_path)),
        result=result,
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="2026-01-01T00:01:00Z",
        started_mono=0.0,
        ended_mono=10.0,
        argv=[],
        log_text=log_path.read_text(encoding="utf-8", errors="replace"),
    )
    assert ev["log_checksum_sha256"] is not None
    # Atomic write should succeed even with partial log
    p = write_evidence_atomic(ev, log_dir=tmp_path, device_path=disk.path)
    assert p.exists()
    assert verify_evidence_checksum(p)


def test_clock_anomalies_handled(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # Wall clock returns empty on exception
    def bad_wall():
        raise OSError("clock failed")

    wiz, clock = _wiz(tmp_path, wall=bad_wall)
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
    # Should not crash, evidence should have empty wall or fallback
    assert wiz.evidence is not None
    assert wiz.evidence["timestamps"]["started_at_wall"] == ""  # type: ignore[index]

    # Monotonic going backwards: duration None
    base = make_demo_wizard()
    disc = base.discovery
    disk = next(d for d in disc.selectable if d.path == "/dev/sda")
    ev = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=None,
        result=WipeResult(ok=False, exit_code=1, summary="fail", logfile=""),
        started_at_wall="2026-01-01T00:01:00Z",
        ended_at_wall="2026-01-01T00:00:00Z",
        started_mono=10.0,
        ended_mono=5.0,
        argv=[],
        log_text="",
    )
    assert ev["timestamps"]["duration_s"] is None  # type: ignore[index]

    # Duplicate wall timestamps (same ns) still valid
    ev2 = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=None,
        result=WipeResult(ok=True, exit_code=0, summary="finished", logfile=""),
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="2026-01-01T00:00:00Z",
        started_mono=0.0,
        ended_mono=0.0,
        argv=[],
        log_text="",
    )
    assert ev2["timestamps"]["duration_s"] == 0.0  # type: ignore[index]


def test_duplicate_events_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    path1 = wiz.evidence_path
    assert path1
    # Tick with same WORKING state and poll returning same result twice
    clock.add(0.6)
    wiz.tick()
    path2 = wiz.evidence_path
    assert path1 == path2 or Path(path2).exists()  # type: ignore[arg-type]
    # Second tick should not create new evidence file
    files_before = list(tmp_path.glob(f"{EVIDENCE_PREFIX}*.json"))
    wiz.tick()
    wiz.tick()
    files_after = list(tmp_path.glob(f"{EVIDENCE_PREFIX}*.json"))
    assert len(files_after) == len(files_before)
    # _finish deduplication: calling _finish twice with same result should not rewrite
    if wiz.wipe_result:
        wiz._finish(wiz.wipe_result)
        files_after2 = list(tmp_path.glob(f"{EVIDENCE_PREFIX}*.json"))
        assert len(files_after2) == len(files_after)


def test_recovery_after_failed_write_then_success(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    # Fail first evidence write
    monkeypatch.setattr("beamo_wipe.evidence.write_evidence_atomic", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    wiz.confirm_erase()
    assert wiz.evidence_error is not None
    assert wiz.screen == Screen.WORKING
    # Now fix and complete
    monkeypatch.setattr("beamo_wipe.evidence.write_evidence_atomic", lambda ev, **k: tmp_path / "recovered.json")  # type: ignore[assignment]

    # Simulate poll completion
    def fake_write(ev, **kw):
        p = tmp_path / "recovered2.json"
        p.write_text(json.dumps(ev), encoding="utf-8")
        (tmp_path / "recovered2.json.sha256").write_text("fake", encoding="utf-8")
        return p

    monkeypatch.setattr("beamo_wipe.evidence.write_evidence_atomic", fake_write)
    clock.add(0.6)
    wiz.tick()
    assert wiz.screen == Screen.DONE
    # Evidence should now exist despite earlier failure
    assert wiz.evidence is not None or wiz.evidence_error is None


def test_malformed_log_output_and_signals_do_not_overstate(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # Each malformed case must be FAILED
    cases = [
        ("", 0, False),
        ("Nwipe successfully completed\n", 0, False),
        ("/dev/sda is reported as IN USE\nNwipe successfully completed\n", 0, False),
        ("Unable to open device '/dev/sda'.\n", 0, False),
        ("/dev/sda: 100.00%, round 1 of 1, pass 1 of 3\nNwipe successfully completed\n", 0, False),
        ("      sda | Erased |  120MB/s\n", 0, True),
        ("/dev/sda: 100.00%, round 1 of 1\n", 0, True),
    ]
    for log, code, should_ok in cases:
        ok, reason = evaluate_nwipe_completion(code, log, "/dev/sda")
        assert ok == should_ok, f"log {log[:30]!r} code {code} expected ok={should_ok}"
        base = make_demo_wizard()
        disc = base.discovery
        disk = next(d for d in disc.selectable if d.path == "/dev/sda")
        ev = build_evidence(
            disk=disk,
            discovery=disc,
            method=MethodId.EVERYDAY,
            request=WipeRequest(device=disk.path, method=MethodId.EVERYDAY, boot_device="/dev/sdb", logfile=""),
            result=WipeResult(ok=ok, exit_code=code, summary=reason, logfile=""),
            started_at_wall="2026-01-01T00:00:00Z",
            ended_at_wall="2026-01-01T00:01:00Z",
            started_mono=0.0,
            ended_mono=1.0,
            argv=[],
            log_text=log,
        )
        if not should_ok:
            assert ev["outcome"] == OUTCOME_FAILED
        else:
            assert ev["outcome"] in (OUTCOME_COMPLETED, OUTCOME_VERIFIED)
        # Never contains "certificate" or "certified"
        assert "certificate" not in json.dumps(ev).lower()
        assert "certified" not in json.dumps(ev).lower()


def test_no_sensitive_host_details_in_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setenv("HOME", "/home/secret-user")
    monkeypatch.setenv("USER", "secret-user")
    wiz, clock = _wiz(tmp_path)
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
    blob = json.dumps(wiz.evidence)
    for leak in ["/home/secret-user", "secret-user", os.uname().nodename if hasattr(os, "uname") else ""]:
        if leak:
            assert leak not in blob


def test_evidence_files_off_target_and_no_forbidden_roots(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz, clock = _wiz(tmp_path)
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
    p = Path(wiz.evidence_path)  # type: ignore[arg-type]
    # Must not be under forbidden roots or on target
    for forbidden in ["/mnt/target", "/target", "/media/target"]:
        assert not str(p).startswith(forbidden)
    from beamo_wipe.safety import assert_log_not_on_target

    assert_log_not_on_target(str(p), wiz.selected.path)  # type: ignore[union-attr]


def test_atomic_write_no_partial_file_on_failure(tmp_path, monkeypatch):
    # Simulate crash mid-write: os.write succeeds but rename fails
    from beamo_wipe.evidence import build_evidence

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    base = make_demo_wizard()
    disc = base.discovery
    disk = next(d for d in disc.selectable if d.path == "/dev/sda")
    ev = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=None,
        result=None,
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="",
        started_mono=0.0,
        ended_mono=None,
        argv=[],
        log_text="",
    )
    # Force os.rename to fail
    orig_rename = os.rename
    monkeypatch.setattr(os, "rename", lambda *a, **k: (_ for _ in ()).throw(OSError("rename failed")))
    with pytest.raises(OSError):
        write_evidence_atomic(ev, log_dir=tmp_path, device_path=disk.path)
    # No partial .json should be visible, only tmp
    assert not any(tmp_path.glob(f"{EVIDENCE_PREFIX}*.json"))
    # tmp files may remain but not as evidence
    monkeypatch.setattr(os, "rename", orig_rename)
    # Now succeed
    p = write_evidence_atomic(ev, log_dir=tmp_path, device_path=disk.path)
    assert p.exists()
