# SPDX-License-Identifier: GPL-3.0-or-later
"""Malformed discovery input must not persist device identifiers in diagnostics."""

from __future__ import annotations

import pytest
import subprocess

from beamo_wipe import discover as discovery
from beamo_wipe.models import DiscoveryResult
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard


def test_malformed_size_logs_code_without_raw_input(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    assert discovery._as_int("SERIAL_PRIVATE_123") == 0
    logged = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "size_parse_failed" in logged
    assert "SERIAL_PRIVATE_123" not in logged


@pytest.mark.parametrize("error_type", (ValueError, RuntimeError))
def test_discovery_failure_logs_type_without_exception_payload(tmp_path, monkeypatch, error_type):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)

    def malformed_inventory():
        raise error_type("disk serial SERIAL_PRIVATE_123 at /dev/disk/by-id/private")

    monkeypatch.setattr(discovery, "run_lsblk", malformed_inventory)
    result = discovery.discover(env={"BEAMO_WIPE_DRY_RUN": "1"})
    assert not result.boot_identified and not result.selectable
    logged = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    code = "failed" if error_type is ValueError else "unexpected"
    assert f'"code": "{code}"' in logged
    assert error_type.__name__ in logged
    assert "SERIAL_PRIVATE_123" not in logged
    assert "/dev/disk/by-id/private" not in logged


def test_alias_probe_failure_does_not_print_or_log_private_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(discovery.os.path, "realpath", lambda _path: (_ for _ in ()).throw(OSError("probe failed")))
    path = "/dev/SERIAL_PRIVATE_123"
    assert discovery._path_aliases(path) == {path}
    output = capsys.readouterr().err
    logged = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "alias_realpath_failed" in output + logged
    assert "SERIAL_PRIVATE_123" not in output + logged


def test_findmnt_failure_does_not_log_stderr_payload(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    secret = "/dev/disk/by-id/SERIAL_PRIVATE_123"
    failed = subprocess.CompletedProcess(
        args=["findmnt"], returncode=1, stdout="", stderr=f"cannot inspect {secret}"
    )
    monkeypatch.setattr(discovery.subprocess, "run", lambda *_args, **_kwargs: failed)
    assert discovery._run_findmnt("/run/live/medium") is failed
    logged = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "findmnt_stderr" in logged
    assert secret not in logged


def test_findmnt_aggregate_failure_does_not_log_stderr_payload(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    secret = "/dev/disk/by-id/SERIAL_PRIVATE_123"
    failed = subprocess.CompletedProcess(
        args=["findmnt"], returncode=1, stdout="", stderr=f"cannot inspect {secret}"
    )
    monkeypatch.setattr(discovery, "_run_findmnt", lambda _mountpoint: failed)
    monkeypatch.setattr(discovery, "read_mountinfo_sources", lambda _paths: [])
    assert discovery.read_mount_sources(paths=("/run/live/medium",)) == []
    logged = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "findmnt_failures" in logged
    assert secret not in logged


def test_blocked_picker_does_not_relog_raw_discovery_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    secret = "SERIAL_PRIVATE_123"
    wizard = Wizard(
        DiscoveryResult(
            error="Boot USB could not be identified",
            diagnostic=f"invalid device /dev/{secret}",
            error_code="discovery_failed",
            boot_identified=False,
        ),
        DryRunRunner(),
        dry_run=True,
    )
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    logged = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "pick_blocked" in logged
    assert secret not in logged
