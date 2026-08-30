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
        "BEGIN PRIVATE KEY",
        "sk-live-",
        "ghp_",
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


def test_mkdir_run_live_is_not_a_live_session():
    """A directory named /run/live on a desktop must not enable real wipes."""
    assert not is_live_environment(
        env={}, cmdline="BOOT_IMAGE=/vmlinuz root=UUID=abc ro", paths_exist=["/run/live"]
    )
    assert not is_live_environment(
        env={}, cmdline="boot=live quiet", paths_exist=["/run/live"]
    )
    with pytest.raises(SafetyError):
        require_live_or_dry_run(
            env={}, cmdline="BOOT_IMAGE=/vmlinuz root=UUID=abc ro"
        )


def test_log_directory_symlink_is_refused(tmp_path):
    real = tmp_path / "real-logs"
    real.mkdir()
    link = tmp_path / "beamo-wipe"
    link.symlink_to(real)
    with pytest.raises(SafetyError, match="symlink"):
        assert_log_not_on_target(str(link / "nwipe-sda.log"), "/dev/sda", log_dir=link)


def test_log_dir_on_other_device_is_refused(monkeypatch, tmp_path):
    import os
    from beamo_wipe import safety as safety_mod

    log_dir = tmp_path / "beamo-wipe"
    log_dir.mkdir()
    monkeypatch.setattr(safety_mod, "DEFAULT_LOG_DIR", log_dir)

    real_stat = os.stat

    class DevMismatch:
        def __init__(self, st, dev):
            self._st = st
            self.st_dev = dev

        def __getattr__(self, name):
            return getattr(self._st, name)

    def fake_stat(path, *args, **kwargs):
        st = real_stat(path, *args, **kwargs)
        if os.path.realpath(str(path)) == os.path.realpath("/tmp"):
            return DevMismatch(st, st.st_dev + 99)
        return st

    monkeypatch.setattr(os, "stat", fake_stat)
    with pytest.raises(SafetyError, match="/tmp filesystem"):
        default_log_dir()


def test_protected_mount_marks_disk_boot_not_selectable():
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.safety import selectable_disks

    payload = {
        "blockdevices": [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Wrong USB",
                "serial": "WRONGUSB01",
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "sata",
                "model": "Actual live medium",
                "serial": "LIVEUSB001",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "DEBIAN",
                        "mountpoint": "/run/live/medium",
                    }
                ],
            },
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "size": 256060514304,
                "type": "disk",
                "tran": "nvme",
                "model": "SSD",
                "serial": "N1",
            },
        ]
    }
    # Identification wrongly named sda (another USB) as boot.
    result = parse_lsblk_json(payload, boot_path="/dev/sda")
    assert result.boot_identified
    paths = {d.path for d in selectable_disks(result)}
    assert "/dev/sdb" not in paths
    assert "/dev/sda" not in paths
    assert "/dev/nvme0n1" in paths
    sdb = next(d for d in result.disks if d.path == "/dev/sdb")
    assert sdb.is_boot


def test_protected_mount_refuses_ready_to_wipe(monkeypatch, tmp_path):
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.safety import assert_ready_to_wipe, selectable_disks
    from beamo_wipe.models import MethodId

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    payload = {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "model": "ST500",
                "serial": "Z9A",
                "mountpoint": "/",
            },
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    assert selectable_disks(result) == ()
    sda = next(d for d in result.disks if d.path == "/dev/sda")
    with pytest.raises(SafetyError):
        assert_ready_to_wipe(
            owner_ok=True,
            disk=sda,
            discovery=result,
            typed_token="500",
            countdown_complete=True,
            method=MethodId.EVERYDAY,
        )


def test_nwipe_binary_is_pinned_path_not_path_lookup():
    from beamo_wipe import NWIPE_PINNED_PATH
    from beamo_wipe.nwipe_runner import resolve_nwipe_binary

    assert resolve_nwipe_binary("nwipe") == NWIPE_PINNED_PATH
    assert resolve_nwipe_binary(NWIPE_PINNED_PATH) == NWIPE_PINNED_PATH
    with pytest.raises(SafetyError, match="pinned path"):
        resolve_nwipe_binary("/usr/local/bin/nwipe")
    with pytest.raises(SafetyError, match="relative"):
        resolve_nwipe_binary("fake_nwipe")


def test_argv_rejects_unknown_flag_and_method():
    from beamo_wipe.models import MethodId, WipeRequest
    from beamo_wipe.nwipe_runner import build_nwipe_argv, validate_argv

    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile="/tmp/beamo-wipe/nwipe-vda.log",
    )
    argv = build_nwipe_argv(req)
    argv.insert(-1, "--sync")
    with pytest.raises(SafetyError, match="unexpected"):
        validate_argv(argv, req)
    argv = build_nwipe_argv(req)
    argv[argv.index("--method=prng")] = "--method=ops2"
    with pytest.raises(SafetyError):
        validate_argv(argv, req)
    argv = build_nwipe_argv(req)
    argv[argv.index("--PDFreportpath=noPDF")] = "--PDFreportpath=/dev/sda"
    with pytest.raises(SafetyError):
        validate_argv(argv, req)


def test_nwipe_start_does_not_makedirs():
    import inspect

    from beamo_wipe.nwipe_runner import NwipeRunner

    source = inspect.getsource(NwipeRunner.start)
    assert "makedirs" not in source


def test_unknown_method_refuses_wipe(monkeypatch, tmp_path):
    from beamo_wipe.discover import discover, load_lsblk_json_text
    from beamo_wipe.safety import assert_ready_to_wipe, confirm_spec, selectable_disks

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    payload = load_lsblk_json_text(
        (ROOT / "tests/fixtures/lsblk_vm_iso.json").read_text(encoding="utf-8")
    )
    d = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    disk = selectable_disks(d)[0]
    spec = confirm_spec(disk, selectable_disks(d))
    with pytest.raises(SafetyError, match="method"):
        assert_ready_to_wipe(
            owner_ok=True,
            disk=disk,
            discovery=d,
            typed_token=spec.token,
            countdown_complete=True,
            method="not-a-method",
        )


def test_preview_env_does_not_mask_a_live_usb(monkeypatch):
    """BEAMO_WIPE_DRY_RUN=1 on the kiosk must not produce a fake Finished."""
    from beamo_wipe.safety import running_on_live_usb

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr(
        "beamo_wipe.discover.read_cmdline", lambda: "boot=live components"
    )
    monkeypatch.setattr(
        "beamo_wipe.discover.live_medium_is_mounted", lambda **_k: True
    )
    assert running_on_live_usb()


def test_live_session_strips_web_and_helper(monkeypatch):
    from beamo_wipe.app import apply_live_session_overrides, _parser

    monkeypatch.setattr("beamo_wipe.app.running_on_live_usb", lambda: True)
    args = _parser().parse_args(
        ["--web", "--helper", "--demo", "--boot-device", "/dev/sda"]
    )
    apply_live_session_overrides(args)
    assert args.web is False
    assert args.helper is False
    assert args.demo is False
    assert args.boot_device is None


def test_optical_is_never_a_wipe_target():
    from beamo_wipe.models import MethodId, WipeRequest
    from beamo_wipe.nwipe_runner import build_nwipe_argv
    from beamo_wipe.safety import normalize_whole_disk

    with pytest.raises(SafetyError, match="optical"):
        normalize_whole_disk("/dev/sr0")
    normalize_whole_disk("/dev/sr0", allow_optical=True)
    req = WipeRequest(
        device="/dev/sr0",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sdb",
        logfile="/tmp/beamo-wipe/nwipe-sr0.log",
    )
    with pytest.raises(SafetyError, match="optical"):
        build_nwipe_argv(req)


def test_exclude_flag_rejects_comma_list():
    from beamo_wipe.models import MethodId, WipeRequest
    from beamo_wipe.nwipe_runner import build_nwipe_argv, validate_argv

    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile="/tmp/beamo-wipe/nwipe-vda.log",
    )
    argv = build_nwipe_argv(req)
    argv[argv.index("--exclude=/dev/sr0")] = "--exclude=/dev/sr0,/dev/vda"
    with pytest.raises(SafetyError):
        validate_argv(argv, req)


def test_duplicate_method_flag_is_rejected():
    from beamo_wipe.models import MethodId, WipeRequest
    from beamo_wipe.nwipe_runner import build_nwipe_argv, validate_argv

    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile="/tmp/beamo-wipe/nwipe-vda.log",
    )
    argv = build_nwipe_argv(req)
    argv.insert(-1, "--method=zero")
    with pytest.raises(SafetyError, match="Exactly one"):
        validate_argv(argv, req)


def test_unsafe_serial_is_not_used_as_confirm_token():
    from beamo_wipe.models import Disk, DiskKind
    from beamo_wipe.safety import confirm_spec

    dirty = Disk(
        path="/dev/sda",
        name="sda",
        model="A",
        serial="../sda",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    other = Disk(
        path="/dev/sdb",
        name="sdb",
        model="B",
        serial="../sdb",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    spec = confirm_spec(dirty, [dirty, other])
    assert "/" not in spec.token
    assert ".." not in spec.token
    assert spec.token in {"sda", "sdb"}


def test_listed_disks_omit_non_selectable_non_boot():
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard

    payload = {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 0,
                "type": "disk",
                "tran": "sata",
                "model": "Empty",
                "serial": "ZERO",
            },
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "size": 256060514304,
                "type": "disk",
                "tran": "nvme",
                "model": "SSD",
                "serial": "N1",
            },
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    wiz = Wizard(result, DryRunRunner(), dry_run=True)
    paths = {d.path for d in wiz.listed_disks}
    assert "/dev/sda" not in paths
    assert "/dev/sdb" in paths
    assert "/dev/nvme0n1" in paths
    from beamo_wipe.models import Screen

    wiz.screen = Screen.PICK
    wiz.select_disk("/dev/sda")
    assert wiz.selected is None
    wiz.select_disk("/dev/nvme0n1")
    assert wiz.selected is not None
    assert wiz.selected.path == "/dev/nvme0n1"


def test_select_disk_refuses_boot_alias(monkeypatch):
    from beamo_wipe.models import Screen
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import make_demo_wizard, Wizard

    base = make_demo_wizard()
    wiz = Wizard(base.discovery, DryRunRunner(), dry_run=True)
    wiz.screen = Screen.PICK
    boot = wiz.discovery.boot
    assert boot is not None
    real = __import__("os").path.realpath
    monkeypatch.setattr(
        "os.path.realpath",
        lambda p, _real=real, boot_path=boot.path: boot_path
        if p == "/dev/alias-boot"
        else _real(p),
    )
    wiz.select_disk("/dev/alias-boot")
    assert wiz.selected is None


def test_popen_inherits_wipe_lock_fd(tmp_path, monkeypatch):
    import subprocess
    from beamo_wipe.models import MethodId, WipeRequest
    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    captured = {}

    class FakeProc:
        def poll(self):
            return None

        def send_signal(self, _sig):
            return None

        def terminate(self):
            return None

        def kill(self):
            return None

        def wait(self, timeout=None):
            return 0

        returncode = 0

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(tmp_path / "fake_engine"))
    script = tmp_path / "fake_engine"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    runner.start(req)
    assert "pass_fds" in captured["kwargs"]
    assert captured["kwargs"]["pass_fds"]
    assert captured["kwargs"]["cwd"] == "/"
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["start_new_session"] is True
    runner.cancel()


def test_nwipe_script_is_not_a_safe_engine(tmp_path):
    from beamo_wipe.nwipe_runner import assert_nwipe_binary_safe

    script = tmp_path / "nwipe"
    script.write_text("#!/bin/sh\necho 0.42\n", encoding="utf-8")
    script.chmod(0o755)
    with pytest.raises(SafetyError, match="ELF"):
        assert_nwipe_binary_safe(str(script))


def test_overlay_mount_source_is_not_a_dev_node():
    from beamo_wipe.discover import normalize_mount_source

    assert normalize_mount_source("sdb1") == "/dev/sdb1"
    assert normalize_mount_source("overlay") == "overlay"
    assert normalize_mount_source("tmpfs") == "tmpfs"


def test_live_medium_mount_requires_block_source():
    from beamo_wipe.discover import live_medium_is_mounted

    overlay = (
        "22 1 0:21 / /run rw - tmpfs tmpfs rw\n"
        "25 22 0:24 / /run/live/medium rw - overlay overlay rw\n"
    )
    assert not live_medium_is_mounted(text=overlay)
    real = (
        "22 1 0:21 / /run rw - tmpfs tmpfs rw\n"
        "25 22 8:17 / /run/live/medium ro - iso9660 /dev/sr0 ro\n"
    )
    assert live_medium_is_mounted(text=real)


def test_findmnt_nonzero_stdout_is_ignored(monkeypatch):
    from beamo_wipe import discover as discover_mod

    class FakeProc:
        returncode = 1
        stdout = "/dev/sda"

    monkeypatch.setattr(discover_mod, "_run_findmnt", lambda _mp: FakeProc())
    monkeypatch.setattr(discover_mod, "read_mountinfo_sources", lambda _p=None: [])
    assert discover_mod.read_mount_sources(["/run/live/medium"]) == []


def test_log_on_target_mount_is_refused(tmp_path, monkeypatch):
    from beamo_wipe.safety import assert_log_not_on_target, _log_filesystem_is_target

    log = tmp_path / "nwipe-sda.log"
    log.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        "beamo_wipe.safety.is_preview_env", lambda env=None: False
    )
    monkeypatch.setattr(
        "beamo_wipe.safety._log_filesystem_is_target",
        lambda _log, _target: True,
    )
    with pytest.raises(SafetyError, match="target disk"):
        assert_log_not_on_target(str(log), "/dev/sda", log_dir=tmp_path)
    # helper itself: tmpfs source is not the target
    assert _log_filesystem_is_target(log, "") is False


def test_same_rdev_is_treated_as_boot(monkeypatch):
    import os
    import stat as statmod
    from beamo_wipe.safety import assert_not_boot

    class Fake:
        def __init__(self, rdev):
            self.st_mode = statmod.S_IFBLK
            self.st_rdev = rdev

    def fake_lstat(path):
        if path in ("/dev/sda", "/dev/nvme0n1"):
            return Fake(0x800)
        raise FileNotFoundError(path)

    monkeypatch.setattr(os, "lstat", fake_lstat)
    monkeypatch.setattr(os.path, "realpath", lambda p: p)
    with pytest.raises(SafetyError, match="boot"):
        assert_not_boot("/dev/sda", "/dev/nvme0n1")


def test_missing_block_device_required_for_real_wipe(monkeypatch):
    from beamo_wipe.safety import assert_existing_is_block_device

    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    with pytest.raises(SafetyError, match="missing"):
        assert_existing_is_block_device("/dev/definitely-not-a-disk-beamo", required=True)
    assert_existing_is_block_device("/dev/definitely-not-a-disk-beamo", required=False)


def _disk(**kwargs):
    from beamo_wipe.models import Disk, DiskKind

    fields = dict(
        path="/dev/sda",
        name="sda",
        model="ST500",
        serial="Z9A",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    fields.update(kwargs)
    return Disk(**fields)


def test_ready_to_wipe_refuses_iscsi_and_mounted(monkeypatch, tmp_path):
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.models import MethodId
    from beamo_wipe.safety import assert_ready_to_wipe

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    payload = {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "iscsi",
                "model": "SAN LUN",
                "serial": "IQN1",
            },
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    lun = next(d for d in result.disks if d.path == "/dev/sda")
    with pytest.raises(SafetyError, match="No target disk"):
        assert_ready_to_wipe(
            owner_ok=True,
            disk=lun,
            discovery=result,
            typed_token="500",
            countdown_complete=True,
            method=MethodId.EVERYDAY,
        )


def test_iscsi_disk_is_not_selectable():
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.safety import is_remote_disk, selectable_disks

    payload = {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "iscsi",
                "model": "SAN LUN",
                "serial": "IQN1",
            },
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    assert result.boot_identified
    assert selectable_disks(result) == ()
    lun = next(d for d in result.disks if d.path == "/dev/sda")
    assert lun.bus == "ISCSI"
    assert is_remote_disk(lun)


def test_fc_disk_is_not_selectable():
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.safety import selectable_disks

    payload = {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "fc",
                "model": "SAN",
                "serial": "FC1",
            },
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    assert selectable_disks(result) == ()


def test_mounted_media_disk_is_not_selectable():
    """A disk mounted at /media is in use. nwipe without --force would skip it."""
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.safety import selectable_disks

    payload = {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
            },
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 500107862016,
                "type": "disk",
                "tran": "sata",
                "model": "ST500",
                "serial": "Z9A",
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "mountpoint": "/media/data",
                    }
                ],
            },
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    assert "/dev/sda" not in {d.path for d in selectable_disks(result)}
    sda = next(d for d in result.disks if d.path == "/dev/sda")
    assert not sda.is_boot


def test_selectable_requires_identified_boot_object():
    from beamo_wipe.models import DiscoveryResult
    from beamo_wipe.safety import selectable_disks

    disk = _disk()
    bogus = DiscoveryResult(
        disks=(disk,),
        selectable=(disk,),
        boot=None,
        error=None,
        boot_identified=True,
    )
    assert selectable_disks(bogus) == ()


def test_live_size_check_refuses_missing_sysfs(monkeypatch):
    from beamo_wipe.safety import assert_size_unchanged

    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda env=None: False)
    monkeypatch.setattr("beamo_wipe.safety.block_size_bytes", lambda _path: None)
    with pytest.raises(SafetyError, match="Cannot read disk size"):
        assert_size_unchanged("/dev/vda", 10_000_000_000)


def test_zero_expected_size_is_not_a_skip(monkeypatch):
    from beamo_wipe.safety import assert_size_unchanged

    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda env=None: False)
    with pytest.raises(SafetyError, match="zero-size"):
        assert_size_unchanged("/dev/vda", 0)


def test_log_mountinfo_unreadable_is_fail_closed_on_live(tmp_path, monkeypatch):
    from beamo_wipe.safety import _log_filesystem_is_target

    log = tmp_path / "nwipe-sda.log"
    log.write_text("x", encoding="utf-8")
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda env=None: False)
    monkeypatch.setattr(
        "beamo_wipe.discover.MOUNTINFO_PATH", str(tmp_path / "missing-mountinfo")
    )
    assert _log_filesystem_is_target(log, "/dev/sda") is True


def test_log_mountinfo_unreadable_is_ignored_in_preview(tmp_path, monkeypatch):
    from beamo_wipe.safety import _log_filesystem_is_target

    log = tmp_path / "nwipe-sda.log"
    log.write_text("x", encoding="utf-8")
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr(
        "beamo_wipe.discover.MOUNTINFO_PATH", str(tmp_path / "missing-mountinfo")
    )
    assert _log_filesystem_is_target(log, "/dev/sda") is False


def test_lsblk_and_findmnt_are_absolute_paths():
    from beamo_wipe.discover import FINDMNT_BINARIES, LSBLK_BINARIES

    assert LSBLK_BINARIES == ("/usr/bin/lsblk",)
    assert FINDMNT_BINARIES == ("/usr/bin/findmnt",)
    for binary in LSBLK_BINARIES + FINDMNT_BINARIES:
        assert binary.startswith("/")


def test_lsblk_and_nwipe_version_use_clean_env():
    import inspect

    from beamo_wipe.discover import _run_findmnt, run_lsblk
    from beamo_wipe.nwipe_runner import _verify_pinned_nwipe

    assert "CLEAN_SUBPROCESS_ENV" in inspect.getsource(run_lsblk)
    assert "CLEAN_SUBPROCESS_ENV" in inspect.getsource(_run_findmnt)
    src = inspect.getsource(_verify_pinned_nwipe)
    assert "env=NWIPE_CLEAN_ENV" in src
    assert "LD_PRELOAD" not in src
