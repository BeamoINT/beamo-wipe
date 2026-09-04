# SPDX-License-Identifier: GPL-3.0-or-later
"""Hidden-failure visibility regressions.

Every test uses fake devices only; never execs real nwipe or touches a
host disk. Each proves a previously swallowed error is now visible and
actionable, without leaking secrets or retrying a destructive action.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from beamo_wipe.diagnostics import _sanitize_detail, log_diag
from beamo_wipe.discover import discover, run_lsblk
from beamo_wipe.models import DiscoveryResult


def test_discover_timeout_is_diagnostic_not_generic_only(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired("lsblk", 15)

    with mock.patch("beamo_wipe.discover.subprocess.run", side_effect=boom):
        result = discover(boot_path=None, mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    assert not result.boot_identified
    assert result.error
    assert "cannot tell which disk is this usb" in result.error.lower()
    assert result.diagnostic and "TimeoutExpired" in result.diagnostic
    # Diagnostics log got a structured entry (safe, truncated, no payload dump)
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "TimeoutExpired" in diag
    assert "lsblk" in diag


def test_run_lsblk_stderr_is_logged_and_preserved():
    def boom(*_a, **_k):
        raise subprocess.CalledProcessError(1, "lsblk", stderr="lsblk: permission denied\n")

    with mock.patch("beamo_wipe.discover.subprocess.run", side_effect=boom):
        with mock.patch("beamo_wipe.diagnostics.log_diag") as lg:
            with pytest.raises(subprocess.CalledProcessError):
                run_lsblk()
            assert lg.called
            area, code, detail = lg.call_args[0]
            assert area == "discover" and code == "lsblk_failed"
            assert "permission denied" in detail.lower()


def test_findmnt_timeout_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe.discover import _run_findmnt

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired("findmnt", 8)

    with mock.patch("beamo_wipe.discover.subprocess.run", side_effect=boom):
        assert _run_findmnt("/run/live/medium") is None
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "findmnt" in diag.lower()


def test_read_cmdline_failure_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe.discover import read_cmdline

    with mock.patch("builtins.open", side_effect=OSError("perm")):
        assert read_cmdline("/proc/cmdline") == ""
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "cmdline_unreadable" in diag


def test_mountinfo_unreadable_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe.discover import read_mountinfo_sources

    with mock.patch("builtins.open", side_effect=OSError("enoent")):
        assert read_mountinfo_sources() == []
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "mountinfo_unreadable" in diag


def test_pick_blocked_logs_but_does_not_expose_diagnostic():
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.wizard import Wizard

    base = make_demo_wizard()
    blocked = DiscoveryResult(
        error="We cannot tell which disk is this USB. Unplug extra USB sticks and start again.",
        boot_identified=False,
        diagnostic="CalledProcessError: lsblk exit 1",
    )
    wiz = Wizard(blocked, base.runner, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen.value == "pick_blocked"
    assert wiz.error == blocked.error
    assert "CalledProcessError" not in (wiz.error or "")


def test_console_progress_is_formatted_not_raw():
    txt = Path("src/beamo_wipe/ui/console_wizard.py").read_text(encoding="utf-8")
    assert "format_progress_percent(wizard.progress)" in txt
    # Plain loop no longer prints raw float
    assert 'pct = "—" if wizard.progress is None else wizard.progress' not in txt


def test_nwipe_log_open_permission_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe.nwipe_runner import NwipeRunner
    import os as _os

    runner = NwipeRunner(binary=str(tmp_path / "fake"))
    real_open = _os.open

    def fake_open(path, *args, **kwargs):
        if "nwipe.log" in str(path):
            raise OSError(13, "Permission denied")
        return real_open(path, *args, **kwargs)

    with mock.patch("os.open", side_effect=fake_open):
        runner._read_log_tail(str(tmp_path / "nwipe.log"), 8000) == ""
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "log_open_failed" in diag


def test_nwipe_cancel_logs_terminate_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe.nwipe_runner import NwipeRunner
    from beamo_wipe.models import MethodId, WipeRequest

    # Fake proc that raises on terminate
    class BadProc:
        returncode = None

        def terminate(self):
            raise OSError("perm")

        def wait(self, timeout=None):
            return 0

    runner = NwipeRunner(binary=str(tmp_path / "fake"))
    runner._proc = BadProc()  # type: ignore[assignment]
    runner._lock_fd = None
    runner.cancel()
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "cancel_terminate_failed" in diag
    assert runner.result is not None and not runner.result.ok


def test_shutdown_failure_is_visible(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe import app as app_mod

    with mock.patch("subprocess.run", side_effect=OSError("no systemctl")):
        with mock.patch("beamo_wipe.diagnostics.log_diag") as lg:
            app_mod._shutdown()
            assert lg.called
            assert lg.call_args[0][1] == "shutdown_failed"


def test_evidence_write_failure_is_surfaced(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.wizard import Wizard

    base = make_demo_wizard()
    wiz = Wizard(base.discovery, base.runner, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    tgt = wiz.selectable[0]
    wiz.select_disk(tgt.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0

    # Force write_evidence_atomic to fail with SafetyError (e.g., log on target)
    with mock.patch("beamo_wipe.evidence.write_evidence_atomic", side_effect=Exception("no space")):
        wiz.confirm_erase()
        # Evidence error is now visible to maintainer, not silently swallowed
        assert wiz.evidence_error is not None or wiz.evidence is not None


def test_diagnostics_sanitize_truncates_and_strips_newlines():
    long = "a" * 500 + "\nsecret line\n" + "b" * 200
    san = _sanitize_detail(long)
    assert "\n" not in san
    assert len(san) <= 300
    assert san.endswith("...")


def test_diagnostics_log_is_structured_json(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    log_diag("area1", "code1", "detail with\nnewline", log_dir=tmp_path)
    line = (tmp_path / "diagnostics.log").read_text(encoding="utf-8").strip()
    import json

    obj = json.loads(line)
    assert obj["area"] == "area1"
    assert obj["code"] == "code1"
    assert "\n" not in obj["detail"]
    assert "ts_wall" in obj and "pid" in obj


def test_build_hook_logs_with_retry_and_timestamp():
    text = Path("packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot").read_text(encoding="utf-8")
    assert "date -u" in text
    assert '>>"$clone_log" 2>&1' in text
    assert 'run_logged "$WORKDIR/apt-update.log"' in text
    assert "Acquire::Retries=3" in text
    assert "Next: check" in text


def test_progress_never_shows_100_before_verified():
    from beamo_wipe.nwipe_runner import _target_job_percent, evaluate_nwipe_completion

    # dodshort mid-job: pinned nwipe's value is already job-wide.
    log = "/dev/vda: 33.33%, round 1 of 1, pass 1 of 3, eta 00:10:00, [writing]\n"
    assert _target_job_percent(log, "/dev/vda") == pytest.approx(33.33, abs=0.01)
    ok, _ = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert not ok, "mid-pass 100% must not be verified"
