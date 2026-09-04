# SPDX-License-Identifier: GPL-3.0-or-later
"""Risk-matrix comprehensive tests: normal/boundary/empty/malformed/duplicate/
permission/failure/retry/concurrent/cancellation/recovery across all critical
subsystems. Fake lsblk JSON, isolated tmp_path, deterministic clocks, no host disk."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from beamo_wipe.discover import (
    classify_bus,
    classify_kind,
    discover,
    live_medium_is_mounted,
    load_lsblk_json_text,
    parse_lsblk_json,
    parse_mountinfo,
)
from beamo_wipe.evidence import (
    EVIDENCE_PREFIX,
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_INTERRUPTED,
    OUTCOME_STARTED,
    OUTCOME_VERIFIED,
    build_evidence,
    verify_evidence_checksum,
    write_evidence_atomic,
)
from beamo_wipe.methods import DEFAULT_METHOD, METHODS
from beamo_wipe.models import Disk, DiskKind, MethodId, Screen, WipeRequest, WipeResult
from beamo_wipe.nwipe_runner import DryRunRunner, build_nwipe_argv, evaluate_nwipe_completion, validate_argv
from beamo_wipe.safety import (
    SafetyError,
    assert_log_not_on_target,
    assert_not_boot,
    block_rdev,
    is_protected_mountpoint,
    is_wipeable_disk,
    normalize_whole_disk,
    selectable_disks,
)
from beamo_wipe.wizard import Wizard, format_progress_percent, make_demo_wizard

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


# ---------------------------------------------------------------------------
# 1. Device classification
# ---------------------------------------------------------------------------


def test_classify_kind_normal_and_boundary():
    assert classify_kind("sda", "sata", True) == DiskKind.HDD
    assert classify_kind("sda", "sata", False) == DiskKind.SSD
    assert classify_kind("sda", "usb", False) == DiskKind.SSD
    # exact nvme tran only
    assert classify_kind("sda", "nvme", False) == DiskKind.NVME
    assert classify_kind("sda", "my-nvme-evil", False) == DiskKind.SSD  # spoof substring must not be NVMe
    assert classify_kind("nvme0n1", "", False) == DiskKind.NVME
    assert classify_kind("nvme0n1", "usb", False) == DiskKind.SSD  # usb tran overrides nvme name, but rota False -> SSD, not NVMe spoof
    assert classify_kind("nvme0n1", "usb", None) == DiskKind.UNKNOWN  # without rota, nvme+usb mismatch -> UNKNOWN not NVMe
    assert classify_kind("nvme0n1", "nvme", False) == DiskKind.NVME
    assert classify_kind("sda", "", None) == DiskKind.UNKNOWN
    assert classify_kind("sda", None, None) == DiskKind.UNKNOWN
    assert classify_kind("", "", None) == DiskKind.UNKNOWN


def test_classify_bus_variants():
    assert classify_bus("nvme") == "NVMe"
    assert classify_bus("sata") == "SATA"
    assert classify_bus("ata") == "SATA"
    assert classify_bus("usb") == "USB"
    assert classify_bus("sas") == "SAS"
    assert classify_bus("virtio") == "other"
    assert classify_bus("spi") == "other"
    assert classify_bus("mystery") == "MYSTERY"
    assert classify_bus("") == "other"
    assert classify_bus(None) == "other"


def test_is_wipeable_disk_protects_remote_and_zero_and_boot(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # remote bus nbd -> not wipeable
    remote = Disk(path="/dev/nbd0", name="nbd0", model="X", serial="S", size_bytes=1000, size_gb_label="1", kind=DiskKind.HDD, bus="nbd", label="")
    assert not is_wipeable_disk(remote)
    # booted disk
    booted = Disk(path="/dev/sda", name="sda", model="M", serial="S", size_bytes=1000, size_gb_label="1", kind=DiskKind.HDD, bus="SATA", label="", is_boot=True)
    assert not is_wipeable_disk(booted)
    # zero size
    zero = Disk(path="/dev/sda", name="sda", model="M", serial="S", size_bytes=0, size_gb_label="0", kind=DiskKind.HDD, bus="SATA", label="")
    assert not is_wipeable_disk(zero)
    # partition path
    part = Disk(path="/dev/sda1", name="sda1", model="M", serial="S", size_bytes=1000, size_gb_label="1", kind=DiskKind.HDD, bus="SATA", label="")
    assert not is_wipeable_disk(part)
    # mounted
    mounted = Disk(path="/dev/sda", name="sda", model="M", serial="S", size_bytes=1000, size_gb_label="1", kind=DiskKind.HDD, bus="SATA", label="", mountpoints=("/",))
    assert not is_wipeable_disk(mounted)


def test_hidden_emmc_boot_partitions_never_selectable():
    payload = {
        "blockdevices": [
            {"name": "mmcblk0", "path": "/dev/mmcblk0", "size": 32000000000, "type": "disk", "tran": "", "rota": False, "model": "EMMC", "serial": "EMMC001"},
            {"name": "mmcblk0boot0", "path": "/dev/mmcblk0boot0", "size": 4194304, "type": "disk", "tran": "", "rota": False, "model": "EMMC boot", "serial": "EMMC001"},
            {"name": "mmcblk0boot1", "path": "/dev/mmcblk0boot1", "size": 4194304, "type": "disk", "tran": "", "rota": False, "model": "EMMC boot", "serial": "EMMC001"},
            {"name": "mmcblk0rpmb", "path": "/dev/mmcblk0rpmb", "size": 4194304, "type": "disk", "tran": "", "rota": False, "model": "EMMC rpmb", "serial": "EMMC001"},
            {"name": "sdb", "path": "/dev/sdb", "size": 16000000000, "type": "disk", "tran": "usb", "model": "Beamo", "serial": "BEAMO001", "children": [{"name": "sdb1", "path": "/dev/sdb1", "type": "part", "label": "BEAMO_WIPE"}]},
        ]
    }
    result = parse_lsblk_json(payload, boot_path="/dev/sdb")
    paths = {d.path for d in result.selectable}
    assert "/dev/mmcblk0" in paths
    assert "/dev/mmcblk0boot0" not in paths
    assert "/dev/mmcblk0boot1" not in paths
    assert "/dev/mmcblk0rpmb" not in paths


def test_usb_sata_bridge_is_not_live_label_fallback_but_mount_wins():
    # payload with USB stick behind SATA bridge (tran sata) holding BEAMO_WIPE
    payload = {
        "blockdevices": [
            {"name": "sda", "path": "/dev/sda", "size": 16000000000, "type": "disk", "tran": "sata", "model": "Bridge", "serial": "BRIDGE01", "children": [{"name": "sda1", "path": "/dev/sda1", "type": "part", "label": "BEAMO_WIPE"}]},
            {"name": "sdb", "path": "/dev/sdb", "size": 500000000000, "type": "disk", "tran": "sata", "model": "ST500", "serial": "ST50001"},
            {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 256000000000, "type": "disk", "tran": "nvme", "model": "NVMe", "serial": "NVME01"},
        ]
    }
    # Without mount, label fallback must NOT pick sda (tran sata not usb) -> fail-closed
    result_no_mount = discover(lsblk_payload=payload, boot_path=None, mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    assert not result_no_mount.boot_identified
    assert result_no_mount.selectable == ()
    # With live mount, it correctly identifies sda even though tran sata
    result_mount = discover(lsblk_payload=payload, boot_path=None, mount_sources=["/dev/sda1"], cmdline="boot=live", env={"BEAMO_WIPE_DRY_RUN": "1"})
    assert result_mount.boot_identified
    assert result_mount.boot.path == "/dev/sda"


# ---------------------------------------------------------------------------
# 2. Boot-media exclusion & system-disk protection
# ---------------------------------------------------------------------------


def test_live_medium_mounted_empty_and_overlay(tmp_path):
    # empty mountinfo -> not live
    assert not live_medium_is_mounted(text="")
    assert not live_medium_is_mounted(text="36 1 8:1 / /run/live/medium - tmpfs tmpfs rw\n")
    # overlay alone must not count as block device source
    overlay_text = "100 0 0:100 / / - overlay overlay rw\n10 1 8:1 / /run/live/medium - overlay overlay rw\n"
    assert not live_medium_is_mounted(text=overlay_text)
    # but /dev/sda1 on /run/live/medium must count
    good = "10 1 8:1 / /run/live/medium - ext4 /dev/sda1 rw\n"
    assert live_medium_is_mounted(text=good)
    # typed LABEL source counts
    typed = "10 1 8:1 / /run/live/medium - ext4 LABEL=BEAMO_WIPE rw\n"
    assert live_medium_is_mounted(text=typed)
    # bare kernel name sda1 counts via KERNEL_NAME_RE
    bare = "10 1 8:1 / /run/live/medium - ext4 sda1 rw\n"
    assert live_medium_is_mounted(text=bare)


def test_parse_mountinfo_uses_octal_unescape():
    text = "30 1 8:1 / /run/live\\040medium - ext4 /dev/sda1 rw\n"
    pairs = parse_mountinfo(text)
    assert pairs == [("/dev/sda1", "/run/live medium")]


def test_is_protected_mountpoint_boundary():
    assert is_protected_mountpoint("/")
    assert is_protected_mountpoint("/run/live/medium")
    assert is_protected_mountpoint("/run/live/medium/sub")
    assert is_protected_mountpoint("/lib/live/mount/medium")
    assert not is_protected_mountpoint("")
    assert not is_protected_mountpoint("/media/data")
    assert not is_protected_mountpoint("/mnt/other")
    assert is_protected_mountpoint("/proc")
    assert is_protected_mountpoint("/dev")


def test_normalize_whole_disk_rejects_malformed_and_partitions(monkeypatch):
    monkeypatch.setattr("os.path.realpath", lambda p: p)
    assert normalize_whole_disk("/dev/sda") == "/dev/sda"
    assert normalize_whole_disk("/dev/nvme0n1") == "/dev/nvme0n1"
    assert normalize_whole_disk("/dev/mmcblk0") == "/dev/mmcblk0"
    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/sda1")
    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/nvme0n1p1")
    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/sda/../sdb")
    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/sda,")
    with pytest.raises(SafetyError):
        normalize_whole_disk("sda")
    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/nbd0")
    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/sr0")
    assert normalize_whole_disk("/dev/sr0", allow_optical=True) == "/dev/sr0"


def test_assert_log_not_on_target_via_mountinfo_equality(monkeypatch, tmp_path):
    # Make default_log_dir point to tmp_path isolated
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # normal log under /tmp passes
    assert_log_not_on_target(str(tmp_path / "nwipe-vda.log"), "/dev/vda", log_dir=tmp_path)
    # forbidden root fails
    with pytest.raises(SafetyError):
        assert_log_not_on_target("/mnt/target/log.txt", "/dev/vda", log_dir=Path("/mnt/target"))
    # symlink log should raise
    real = tmp_path / "real.log"
    real.write_text("x")
    link = tmp_path / "link.log"
    link.symlink_to(real)
    with pytest.raises(SafetyError):
        assert_log_not_on_target(str(link), "/dev/vda", log_dir=tmp_path)


def test_permissions_block_rdev_and_mountinfo_fail_closed(monkeypatch, tmp_path):
    # block_rdev: lstat raises EPERM -> None, then build_nwipe_argv should fail via size or rdev check in real NwipeRunner
    monkeypatch.setattr("os.lstat", lambda p: (_ for _ in ()).throw(OSError(13, "Permission denied")))
    assert block_rdev("/dev/sda") is None
    # assert_log_not_on_target with lstat failure should still raise or be fail-closed?
    # Instead test that discover with unreadable mountinfo returns fail-closed discovery
    with mock.patch("builtins.open", side_effect=OSError(13, "Permission denied")):
        assert not live_medium_is_mounted(text=None, paths=("/run/live/medium",))
        # discover with lsblk payload but mountinfo unreadable -> still should identify via env_boot if present? Without mount, fallback to label may win
        # But if mountinfo open fails, live_medium_is_mounted returns False, not crash
        payload = _load("lsblk_same_size.json")
        result = discover(lsblk_payload=payload, boot_path="/dev/sdb", mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
        # boot_path override still works even if mountinfo fails (since we pass mount_sources=[])
        assert result.boot_identified


def test_empty_lsblk_payload_fails_closed():
    empty = {"blockdevices": []}
    result = parse_lsblk_json(empty, boot_path=None, require_boot=True)
    assert not result.boot_identified
    assert result.error is not None
    assert result.selectable == ()
    # With require_boot False, empty still yields no selectable but not error? Actually code returns empty but boot None
    result2 = parse_lsblk_json(empty, boot_path=None, require_boot=False)
    assert result2.selectable == ()


# ---------------------------------------------------------------------------
# 3. Wipe command construction
# ---------------------------------------------------------------------------


def test_build_nwipe_argv_all_methods_single_device(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    payload = _load("lsblk_vm_iso.json")
    d = discover(lsblk_payload=payload, boot_path="/dev/sr0", mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    disk = selectable_disks(d)[0]
    for method, expected in [
        (MethodId.EVERYDAY, {"--method=prng", "--verify=last", "--noblank"}),
        (MethodId.EXTRA, {"--method=dodshort", "--verify=last", "--noblank"}),
        (MethodId.QUICK_ZERO, {"--method=zero", "--verify=off", "--noblank"}),
    ]:
        req = WipeRequest(device=disk.path, method=method, boot_device="/dev/sr0", logfile=str(tmp_path / f"nwipe-{method.value}.log"))
        argv = build_nwipe_argv(req)
        validate_argv(argv, req)
        assert argv[0] == "nwipe"
        assert argv[-1] == disk.path
        assert argv.count(disk.path) == 1
        for flag in expected:
            assert flag in argv
        assert "--autonuke" in argv and "--nogui" in argv and "--nowait" in argv
        assert "--force" not in argv
        assert "--PDFreportpath=noPDF" in argv
        assert f"--exclude=/dev/sr0" in argv
        assert f"--logfile={req.logfile}" in argv
        # exactly one of each prefix
        for prefix in ("--method=", "--verify=", "--rounds=", "--logfile=", "--exclude="):
            assert len([a for a in argv if a.startswith(prefix)]) == 1


def test_build_nwipe_argv_rejects_second_device_and_comma_list(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    payload = _load("lsblk_vm_iso.json")
    d = discover(lsblk_payload=payload, boot_path="/dev/sr0", mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    disk = selectable_disks(d)[0]
    req = WipeRequest(device=disk.path, method=MethodId.EVERYDAY, boot_device="/dev/sr0", logfile=str(tmp_path / "nwipe.log"))
    argv = build_nwipe_argv(req)
    argv2 = argv.copy()
    argv2.insert(-1, "/dev/sdb")
    with pytest.raises(SafetyError):
        validate_argv(argv2, req)
    argv3 = argv.copy()
    argv3[argv3.index("--exclude=/dev/sr0")] = "--exclude=/dev/sr0,/dev/vda"
    with pytest.raises(SafetyError):
        validate_argv(argv3, req)


def test_wipe_request_unknown_method_is_safety_error(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    req = WipeRequest(device="/dev/vda", method="bogus", boot_device="/dev/sr0", logfile=str(tmp_path / "nwipe.log"))  # type: ignore[arg-type]
    with pytest.raises(SafetyError, match="Unknown wipe method"):
        build_nwipe_argv(req)


# ---------------------------------------------------------------------------
# 4. Confirmation gates & progress/error parsing
# ---------------------------------------------------------------------------


def test_format_progress_never_shows_100_before_100():
    assert format_progress_percent(99.99) == "99%"
    assert format_progress_percent(99.5) == "99%"
    assert format_progress_percent(100.0) == "100%"
    assert format_progress_percent(0.0) == "0%"
    assert format_progress_percent(-1) == "0%"
    assert format_progress_percent(0.1) == "0%"
    assert format_progress_percent(50.9) == "50%"


def test_evaluate_progress_boundary_99_99_and_zero_summary(tmp_path):
    # 99.99% not finished, 0.00% erasure summary not finished
    log_99 = "/dev/vda: 99.99%, round 1 of 1, pass 1 of 1, eta 00:00:10, [writing]\nNwipe successfully completed\n"
    ok, _ = evaluate_nwipe_completion(0, log_99, "/dev/vda")
    assert not ok
    log_zero = " ! vda |                 0 |        10000000000 |             0.00%\nNwipe successfully completed\n"
    ok2, _ = evaluate_nwipe_completion(0, log_zero, "/dev/vda")
    assert not ok2
    # 100% last pass is finished
    log_100 = "/dev/vda: 100.00%, round 1 of 1, pass 1 of 1, eta 00:00:00, [verifying]\nNwipe successfully completed\n"
    ok3, _ = evaluate_nwipe_completion(0, log_100, "/dev/vda")
    assert ok3
    # dodshort mid pass 100% not finished
    log_mid = "/dev/vda: 100.00%, round 1 of 1, pass 2 of 3, eta 00:05:00, [writing]\nNwipe successfully completed\n"
    ok4, _ = evaluate_nwipe_completion(0, log_mid, "/dev/vda")
    assert not ok4
    # device-scoped: busy on other device does not fail target
    log_other_busy = "/dev/sdb is reported as IN USE\n/dev/vda: 100.00%, round 1 of 1\nNwipe successfully completed\n"
    ok5, _ = evaluate_nwipe_completion(0, log_other_busy, "/dev/vda")
    assert ok5


def test_malformed_typed_source_rejected():
    payload = {
        "blockdevices": [
            {"name": "sda", "path": "/dev/sda", "size": 1000, "type": "disk", "tran": "sata", "model": "A", "serial": "S1", "label": "GOOD", "uuid": "uuid-1"},
            {"name": "sdb", "path": "/dev/sdb", "size": 1000, "type": "disk", "tran": "usb", "model": "B", "serial": "S2", "label": "CTRL\nINJECT", "uuid": "uuid\n2"},
        ]
    }
    # Label with control chars -> _clean strips them, but typed source with newline should not match
    result = discover(lsblk_payload=payload, boot_path=None, mount_sources=["LABEL=CTRL\nINJECT"], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    # normalize_mount_source will keep LABEL=... but _resolve_typed_source will look for clean label without newline -> None -> fail-closed
    assert not result.boot_identified
    # Also test SIZE with control chars in lsblk _clean truncates and strips
    from beamo_wipe.discover import _clean

    assert "\n" not in _clean("BAD\nLABEL")
    assert "\x00" not in _clean("BAD\x00LABEL")
    assert len(_clean("a" * 200)) == 128


def test_duplicate_uuid_or_label_fails_closed():
    # duplicate UUID on two partitions -> typed source ambiguous -> None
    payload = _load("lsblk_adversarial_duplicate_uuid.json")
    result = discover(lsblk_payload=payload, boot_path=None, mount_sources=["UUID=11111111-2222-3333-4444-555555555555"], cmdline="boot=live", env={"BEAMO_WIPE_DRY_RUN": "1"})
    assert not result.boot_identified
    assert result.selectable == ()
    # duplicate BEAMO_WIPE label already tested but add size duplicate token check
    same_size_payload = _load("lsblk_same_size.json")
    disc = discover(lsblk_payload=same_size_payload, boot_path="/dev/sdb", mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    # two nvme same size -> selectable 2, but token for each must be unique suffix
    assert len(selectable_disks(disc)) >= 2
    from beamo_wipe.safety import confirm_spec

    for d in selectable_disks(disc):
        spec = confirm_spec(d, selectable_disks(disc))
        assert spec.token
        # token must not be another disk's name if serial suffix collides? The safety logic ensures peer_names check
        assert "/" not in spec.token and ".." not in spec.token


# ---------------------------------------------------------------------------
# 5. Retry / concurrent / cancellation / recovery
# ---------------------------------------------------------------------------


def test_retry_after_flock_contention_deterministic(tmp_path, monkeypatch):
    import fcntl

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    payload = _load("lsblk_vm_iso.json")
    d = discover(lsblk_payload=payload, boot_path="/dev/sr0", mount_sources=[], cmdline="", env={"BEAMO_WIPE_DRY_RUN": "1"})
    disk = selectable_disks(d)[0]
    req = WipeRequest(device=disk.path, method=MethodId.EVERYDAY, boot_device="/dev/sr0", logfile=str(tmp_path / "nwipe.log"))

    # Hold flock manually to simulate contention
    lock_path = tmp_path / "wipe.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    from beamo_wipe.nwipe_runner import NwipeRunner

    runner = NwipeRunner(binary=str(tmp_path / "fake"))
    # first try must fail with SafetyError
    with pytest.raises(SafetyError, match="already running"):
        runner._acquire_wipe_lock(req)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    # after release, acquire succeeds
    runner._acquire_wipe_lock(req)
    assert runner._lock_fd is not None
    runner._release_wipe_lock()
    assert runner._lock_fd is None
    # retry 3 times deterministically
    for _ in range(3):
        runner._acquire_wipe_lock(req)
        runner._release_wipe_lock()


def test_concurrent_double_confirm_erase_single_start_deterministic(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()

    clock = Clock()

    wiz = Wizard(base.discovery, DryRunRunner(duration_s=0.5, clock=clock), clock=clock, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0
    barrier = threading.Barrier(2)

    def do_erase():
        try:
            barrier.wait(timeout=2)
            wiz.confirm_erase()
        except Exception:
            pass

    t1 = threading.Thread(target=do_erase)
    t2 = threading.Thread(target=do_erase)
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)
    evidence_files = list(tmp_path.glob(f"{EVIDENCE_PREFIX}*.json"))
    assert len(evidence_files) == 1
    assert wiz.screen == Screen.WORKING


def test_cancellation_during_sigusr1_armed_yields_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()
    clock = Clock()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=1.0, clock=clock), clock=clock, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    # Simulate SIGUSR1 armed progress
    wiz.runner.progress = 45.0
    wiz.cancel_wipe()
    assert wiz.screen == Screen.DONE
    assert wiz.evidence is not None
    assert wiz.evidence["outcome"] == OUTCOME_INTERRUPTED
    assert wiz.wipe_result is not None and not wiz.wipe_result.ok


def test_recovery_power_loss_atomic_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()
    disc = base.discovery
    disk = next(d for d in disc.selectable if d.path == "/dev/sda")
    # Build evidence then truncate mid-write then recover
    ev = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=WipeRequest(device=disk.path, method=MethodId.EVERYDAY, boot_device="/dev/sdb", logfile="/tmp/beamo-wipe/nwipe-sda.log"),
        result=None,
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall=None,
        started_mono=0.0,
        ended_mono=None,
        argv=["nwipe", "--autonuke", "/dev/sda"],
        log_text="",
    )
    assert ev["outcome"] == OUTCOME_STARTED
    p = write_evidence_atomic(ev, log_dir=tmp_path, device_path=disk.path)
    assert p.exists()
    assert verify_evidence_checksum(p)
    # Simulate power loss truncation: write partial file
    partial = tmp_path / "partial.json"
    partial.write_text('{"incomplete": ', encoding="utf-8")
    assert not verify_evidence_checksum(partial)
    # Recovery: rewrite atomically succeeds
    ev2 = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=WipeRequest(device=disk.path, method=MethodId.EVERYDAY, boot_device="/dev/sdb", logfile="/tmp/beamo-wipe/nwipe-sda.log"),
        result=WipeResult(ok=False, exit_code=143, summary="interrupted", logfile="/tmp/beamo-wipe/nwipe-sda.log"),
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="2026-01-01T00:01:00Z",
        started_mono=0.0,
        ended_mono=60.0,
        argv=["nwipe", "--autonuke", "/dev/sda"],
        log_text="interrupted",
        cancelled=True,
        interrupted=True,
    )
    assert ev2["outcome"] == OUTCOME_INTERRUPTED
    p2 = write_evidence_atomic(ev2, log_dir=tmp_path, device_path=disk.path)
    assert verify_evidence_checksum(p2)
    # No partial tmp files leaked
    assert not any(tmp_path.glob(".*.tmp.*"))


def test_evidence_verification_outcomes_truthful(tmp_path):
    base = make_demo_wizard()
    disc = base.discovery
    disk = next(d for d in disc.selectable if d.path == "/dev/sda")
    # verify off -> completed, not verified
    ev_off = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.QUICK_ZERO,
        request=WipeRequest(device=disk.path, method=MethodId.QUICK_ZERO, boot_device="/dev/sdb", logfile="/tmp/beamo-wipe/log"),
        result=WipeResult(ok=True, exit_code=0, summary="finished", logfile="/tmp/beamo-wipe/log"),
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="2026-01-01T00:01:00Z",
        started_mono=0.0,
        ended_mono=1.0,
        argv=[],
        log_text=" sda | Erased | 1 MB/s | 00:01 | model/serial",
    )
    assert ev_off["outcome"] == OUTCOME_COMPLETED
    assert ev_off["verification"]["verified"] is False
    assert ev_off["verification"]["requested"] == "off"
    # verify last -> verified
    ev_last = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=WipeRequest(device=disk.path, method=MethodId.EVERYDAY, boot_device="/dev/sdb", logfile="/tmp/beamo-wipe/log"),
        result=WipeResult(ok=True, exit_code=0, summary="finished", logfile="/tmp/beamo-wipe/log"),
        started_at_wall="2026-01-01T00:00:00Z",
        ended_at_wall="2026-01-01T00:01:00Z",
        started_mono=0.0,
        ended_mono=1.0,
        argv=[],
        log_text=" sda | Erased | 1 MB/s | 00:01 | model/serial",
    )
    assert ev_last["outcome"] == OUTCOME_VERIFIED
    assert ev_last["verification"]["verified"] is True


def test_empty_mountinfo_and_cmdline_not_live_and_fail_closed():
    assert not live_medium_is_mounted(text="", paths=("/run/live/medium",))
    assert not live_medium_is_mounted(text="5 1 0:5 / /proc - proc proc rw\n", paths=("/run/live/medium",))
    # No cmdline boot=live -> is_live_environment False even if mount false
    from beamo_wipe.safety import is_live_environment

    assert not is_live_environment(cmdline="", live_medium_mounted=False)  # type: ignore[arg-type]
    assert is_live_environment(cmdline="boot=live", live_medium_mounted=True)  # type: ignore[arg-type]


def test_wizard_lifecycle_empty_blocked_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    # empty scenario: no selectable
    empty = make_demo_wizard(scenario="empty")
    empty.skip_splash()
    empty.accept_what()
    empty.set_owner(True)
    empty.continue_owner()
    assert empty.screen == Screen.PICK_EMPTY
    # cannot select or continue
    empty.select_disk("/dev/sda")
    assert empty.selected is None
    # blocked scenario
    blocked = make_demo_wizard(scenario="blocked")
    blocked.skip_splash()
    blocked.accept_what()
    blocked.set_owner(True)
    blocked.continue_owner()
    assert blocked.screen == Screen.PICK_BLOCKED
    # wizard cancel before working does nothing harmful
    blocked.cancel_wipe()
    assert blocked.screen == Screen.PICK_BLOCKED


def test_wizard_countdown_and_countdown_left_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()
    clock = Clock()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=0.5, clock=clock), clock=clock, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    assert wiz.countdown_left > 4.9
    assert not wiz.erase_enabled
    clock.add(4.9)
    assert not wiz.erase_enabled
    clock.add(0.2)
    wiz.tick()
    assert wiz.erase_enabled
    assert wiz.countdown_left == 0.0
    # go back invalidates timer
    wiz.back()
    assert wiz._erase_until is None
    assert not wiz.erase_enabled


def test_nbd_and_iscsi_never_wipeable_even_if_whole_disk(monkeypatch):
    monkeypatch.setattr("os.path.realpath", lambda p: p)
    for path in ["/dev/nbd0", "/dev/nbd1p1", "/dev/sda"]:
        if "nbd" in path:
            with pytest.raises(SafetyError):
                normalize_whole_disk(path)
        else:
            # sda passes
            assert normalize_whole_disk(path) == path
    # bus token iscsi must be rejected via is_wipeable
    iscsi_disk = Disk(path="/dev/sda", name="sda", model="X", serial="S", size_bytes=1000, size_gb_label="1", kind=DiskKind.HDD, bus="iscsi", label="")
    assert not is_wipeable_disk(iscsi_disk)
