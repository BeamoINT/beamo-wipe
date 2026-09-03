# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for 2026-09-03 systematic inspection (fake devices only)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_normalize_delimiter_message_names_delimiter():
    from beamo_wipe.safety import SafetyError, normalize_whole_disk

    for bad in ("/dev/sda;rm", "/dev/sda,rm"):
        try:
            normalize_whole_disk(bad)
        except SafetyError as exc:
            assert "delimiter" in str(exc).lower(), f"misleading message for {bad!r}: {exc}"
        else:  # pragma: no cover - must raise
            raise AssertionError(f"{bad!r} was not rejected")


def test_nwipe_cancel_preserves_logfile(tmp_path, monkeypatch):
    """cancel() must keep the evidence path like poll()/DryRun do (fake proc only)."""
    import subprocess

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    from beamo_wipe.models import MethodId, WipeRequest
    from beamo_wipe.nwipe_runner import NwipeRunner
    from beamo_wipe.safety import default_log_dir

    logdir = str(default_log_dir())
    req = WipeRequest(
        device="/dev/sda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sdb",
        logfile=logdir + "/nwipe-sda-cancel-reg.log",
        device_rdev=0,
        device_size_bytes=1000,
    )

    class _FakeProc:
        returncode = None

        def poll(self):  # pragma: no cover - cancel path only
            return self.returncode

        def terminate(self):
            self.returncode = 143

        def kill(self):
            self.returncode = 143

        def wait(self, timeout=None):
            self.returncode = 143
            return self.returncode

        def send_signal(self, sig):  # pragma: no cover
            pass

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc())
    runner = NwipeRunner(binary="/tmp/beamo-fake-wipe")
    runner.start(req)
    runner.cancel()
    assert runner.result is not None
    assert runner.result.summary == "cancelled"
    assert runner.result.logfile == req.logfile, (
        f"cancel discarded evidence path: {runner.result.logfile!r} != {req.logfile!r}"
    )


def test_build_iso_provenance_not_masked_by_pipe():
    text = (REPO_ROOT / "scripts/build-iso.sh").read_text(encoding="utf-8")
    # Provenance display must not pipe ls to head (masks missing-file failure
    # without pipefail under `#!/bin/sh`). Fail closed with explicit checks.
    section = text.split("Generating release manifest")[-1]
    assert 'manifest.json.sha256" 2>&1 | head' not in section, (
        "build-iso masks missing manifest via `| head`"
    )
    # No masking pipe anywhere in the provenance section (not just on ls
    # lines — e.g. `cat manifest | head` would hide a missing file too).
    assert "| head" not in section, "provenance section pipes to head, masking failure"
    # The fail-closed existence gate itself must be present.
    assert "missing provenance file" in section, (
        "provenance existence gate missing from build-iso.sh"
    )


def test_generate_manifest_always_verifies():
    """generate-release-manifest must verify even for ALLOW_DIRTY runs.

    Only the dirty-state check may be skipped (via allow_dirty); checksum,
    placeholder, nwipe-pin, and ISO checks must still run. Guards the shell
    wiring, not just the Python contract in test_release_manifest.py.
    """
    text = (REPO_ROOT / "scripts/generate-release-manifest.sh").read_text(encoding="utf-8")
    assert "verify_manifest(out, allow_dirty=not strict)" in text, (
        "manifest generation no longer verifies unconditionally"
    )
    assert "skip strict verify" not in text, (
        "ALLOW_DIRTY path skips verification entirely"
    )
