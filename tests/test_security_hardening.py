# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the safety/security pass. Fake lsblk only."""

from __future__ import annotations

from pathlib import Path

import pytest

from beamo_wipe.app import _parser
from beamo_wipe.models import ConfirmSpec, MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner, build_nwipe_argv, validate_argv
from beamo_wipe.safety import (
    SafetyError,
    assert_log_not_on_target,
    default_log_dir,
    is_live_environment,
    require_live_or_dry_run,
    token_matches,
    truncate_log_file,
)

ROOT = Path(__file__).resolve().parents[1]


def test_live_env_var_alone_is_not_live():
    assert not is_live_environment(
        env={"BEAMO_WIPE_LIVE": "1"}, cmdline="", paths_exist=[]
    )
    with pytest.raises(SafetyError):
        require_live_or_dry_run(env={"BEAMO_WIPE_LIVE": "1"}, cmdline="")


def test_log_symlink_is_refused(tmp_path):
    real = tmp_path / "elsewhere.log"
    real.write_text("nope", encoding="utf-8")
    link = tmp_path / "nwipe-sda.log"
    link.symlink_to(real)
    with pytest.raises(SafetyError, match="symlink"):
        assert_log_not_on_target(str(link), "/dev/sda", log_dir=tmp_path)
    with pytest.raises(SafetyError):
        truncate_log_file(str(link), "/dev/sda")


def test_truncate_log_does_not_follow_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    victim = tmp_path / "victim.log"
    victim.write_text("keep me", encoding="utf-8")
    link = tmp_path / "nwipe-vda.log"
    link.symlink_to(victim)
    with pytest.raises(SafetyError):
        truncate_log_file(str(link), "/dev/vda")
    assert victim.read_text(encoding="utf-8") == "keep me"


def test_live_session_strips_preview_overrides(monkeypatch):
    from beamo_wipe.app import _build_wizard
    from beamo_wipe.demo import discovery_for_scenario

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.delenv("BEAMO_WIPE_LIVE", raising=False)
    monkeypatch.setattr("beamo_wipe.app.running_on_live_usb", lambda: True)
    monkeypatch.setattr("beamo_wipe.app.require_live_or_dry_run", lambda: None)
    monkeypatch.setattr(
        "beamo_wipe.app.discover",
        lambda **_k: discovery_for_scenario("happy"),
    )
    args = _parser().parse_args(
        ["--demo", "--dry-run", "--boot-device", "/dev/sda"]
    )
    wiz = _build_wizard(args)
    assert args.demo is False
    assert args.dry_run is False
    assert args.boot_device is None
    assert wiz.dry_run is False
    assert isinstance(wiz.runner, NwipeRunner)


def test_argv_rejects_second_device():
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile="/tmp/beamo-wipe/nwipe-vda.log",
    )
    argv = build_nwipe_argv(req)
    argv.insert(-1, "/dev/sdb")
    with pytest.raises(SafetyError):
        validate_argv(argv, req)


def test_default_log_dir_is_under_tmp():
    path = default_log_dir()
    resolved = path.resolve()
    tmp = Path("/tmp").resolve()
    resolved.relative_to(tmp)


def test_packaging_has_no_embedded_secrets():
    needles = (
        "BEGIN RSA PRIVATE KEY",
        "BEGIN OPENSSH PRIVATE KEY",
        "AKIA",
        "AWS_SECRET",
        "api_key=",
        "API_KEY=",
        "password=",
        "SECRET_KEY",
    )
    roots = (
        ROOT / "src",
        ROOT / "packaging",
        ROOT / "helper",
        ROOT / "scripts",
    )
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in {".pyc", ".png", ".jpg"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for needle in needles:
                assert needle not in text, f"{path} contains {needle}"


def test_token_matches_rejects_empty_and_wrong():
    spec = ConfirmSpec(token="256", prompt="type 256")
    assert token_matches("256", spec)
    assert not token_matches("", spec)
    assert not token_matches("255", spec)
