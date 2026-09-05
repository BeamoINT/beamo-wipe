# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

import pytest

from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.models import MethodId
from beamo_wipe.safety import (
    SafetyError,
    assert_boot_excluded,
    assert_log_not_on_target,
    assert_not_boot,
    assert_ready_to_wipe,
    confirm_spec,
    is_live_environment,
    require_live_or_dry_run,
    selectable_disks,
    token_matches,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _disc(name: str, boot: str | None):
    payload = load_lsblk_json_text((FIXTURES / name).read_text(encoding="utf-8"))
    return discover(
        lsblk_payload=payload,
        boot_path=boot,
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )


def test_boot_never_selectable():
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    assert_boot_excluded(d)
    assert all(not x.is_boot for x in selectable_disks(d))
    assert "/dev/sdb" not in {x.path for x in selectable_disks(d)}


def test_unidentified_boot_raises():
    d = _disc("lsblk_no_boot.json", None)
    with pytest.raises(SafetyError, match="cannot tell which disk"):
        assert_boot_excluded(d)


def test_refuse_wipe_boot_path():
    with pytest.raises(SafetyError):
        assert_not_boot("/dev/sdb", "/dev/sdb")
    with pytest.raises(SafetyError):
        assert_not_boot("/dev/sdb1", "/dev/sdb")
    assert_not_boot("/dev/nvme0n1", "/dev/sdb")


def test_nvme_sibling_namespaces_are_not_treated_as_boot():
    assert_not_boot("/dev/nvme0n11", "/dev/nvme0n1")
    assert_not_boot("/dev/nvme0n1", "/dev/nvme0n11")
    with pytest.raises(SafetyError):
        assert_not_boot("/dev/nvme0n1p1", "/dev/nvme0n1")
    with pytest.raises(SafetyError):
        assert_not_boot("/dev/nvme0n1", "/dev/nvme0n1p1")


def test_logfile_for_is_unique_per_call(tmp_path, monkeypatch):
    from beamo_wipe.safety import logfile_for

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    first = logfile_for("/dev/sda")
    second = logfile_for("/dev/sda")
    assert first != second
    assert str(tmp_path) in first
    assert str(tmp_path) in second


def test_logs_not_on_target_name():
    with pytest.raises(SafetyError):
        assert_log_not_on_target("/mnt/target/log.txt", "/dev/nvme0n1")
    with pytest.raises(SafetyError):
        assert_log_not_on_target("/dev/sda", "/dev/nvme0n1")
    assert_log_not_on_target("/tmp/beamo-wipe/nwipe-nvme0n1.log", "/dev/nvme0n1")


def test_live_markers():
    assert not is_live_environment(env={"BEAMO_WIPE_DRY_RUN": "1"}, paths_exist=[])
    assert not is_live_environment(
        env={"BEAMO_WIPE_LIVE": "1"}, cmdline="", paths_exist=[]
    )
    assert is_live_environment(
        env={}, cmdline="boot=live quiet", live_medium_mounted=True
    )
    assert is_live_environment(
        env={}, cmdline="quiet boot=live components", live_medium_mounted=True
    )
    assert is_live_environment(env={}, cmdline="boot=casper", live_medium_mounted=True)
    assert not is_live_environment(
        env={}, cmdline="boot=live quiet", live_medium_mounted=False
    )
    assert not is_live_environment(env={}, cmdline="boot=live quiet", paths_exist=[])
    assert not is_live_environment(env={}, cmdline="", paths_exist=[])
    assert not is_live_environment(
        env={}, cmdline="", paths_exist=["/run/live", "/lib/live/mount"]
    )
    assert not is_live_environment(env={}, cmdline="debug=boot=live")
    assert not is_live_environment(env={}, cmdline="boot=live-extra")
    require_live_or_dry_run(env={"BEAMO_WIPE_DRY_RUN": "1"}, cmdline="")
    with pytest.raises(SafetyError):
        require_live_or_dry_run(env={}, cmdline="")
    with pytest.raises(SafetyError):
        require_live_or_dry_run(env={"BEAMO_WIPE_LIVE": "1"}, cmdline="")
    require_live_or_dry_run(
        env={}, cmdline="boot=live", live_medium_mounted=True
    )
    with pytest.raises(SafetyError):
        require_live_or_dry_run(
            env={}, cmdline="boot=live", live_medium_mounted=False
        )


def test_owner_and_token_required_before_wipe(monkeypatch, tmp_path):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disk = selectable_disks(d)[0]
    spec = confirm_spec(disk, selectable_disks(d))
    with pytest.raises(SafetyError, match="Owner"):
        assert_ready_to_wipe(
            owner_ok=False,
            disk=disk,
            discovery=d,
            typed_token=spec.token,
            countdown_complete=True,
            method=MethodId.EVERYDAY,
        )
    with pytest.raises(SafetyError, match="token"):
        assert_ready_to_wipe(
            owner_ok=True,
            disk=disk,
            discovery=d,
            typed_token="nope",
            countdown_complete=True,
            method=MethodId.EVERYDAY,
        )
    with pytest.raises(SafetyError, match="delay"):
        assert_ready_to_wipe(
            owner_ok=True,
            disk=disk,
            discovery=d,
            typed_token=spec.token,
            countdown_complete=False,
            method=MethodId.EVERYDAY,
        )
    req = assert_ready_to_wipe(
        owner_ok=True,
        disk=disk,
        discovery=d,
        typed_token=spec.token,
        countdown_complete=True,
        method=MethodId.EVERYDAY,
    )
    assert req.device == disk.path
    assert req.boot_device == "/dev/sdb"
    assert str(tmp_path) in req.logfile


def test_preview_size_check_ignores_host_sysfs(monkeypatch, tmp_path):
    """Fake lsblk JSON reuses /dev names. Host sysfs for that name is another disk."""
    from beamo_wipe.safety import assert_size_unchanged

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr("beamo_wipe.safety.block_size_bytes", lambda _path: 99)
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disk = selectable_disks(d)[0]
    spec = confirm_spec(disk, selectable_disks(d))
    assert_size_unchanged(disk.path, disk.size_bytes)
    req = assert_ready_to_wipe(
        owner_ok=True,
        disk=disk,
        discovery=d,
        typed_token=spec.token,
        countdown_complete=True,
        method=MethodId.EVERYDAY,
    )
    assert req.device == disk.path


def test_live_size_check_still_refuses_sysfs_mismatch(monkeypatch):
    from beamo_wipe.safety import assert_size_unchanged

    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda env=None: False)
    monkeypatch.setattr("beamo_wipe.safety.block_size_bytes", lambda _path: 99)
    with pytest.raises(SafetyError, match="size changed"):
        assert_size_unchanged("/dev/vda", 10_000_000_000)


def test_empty_confirm_token_never_matches():
    from beamo_wipe.models import ConfirmSpec

    spec = ConfirmSpec(token="", prompt="x")
    assert not token_matches("", spec)
    assert not token_matches("   ", spec)
    spec_ws = ConfirmSpec(token="  ", prompt="x")
    assert not token_matches("  ", spec_ws)
    assert not token_matches("256", spec_ws)


def test_nbd_is_not_a_wipe_target():
    from beamo_wipe.safety import normalize_whole_disk

    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/nbd0")
    with pytest.raises(SafetyError):
        normalize_whole_disk("/dev/nbd1")


def test_wwn_change_is_identity_change(monkeypatch, tmp_path):
    from dataclasses import replace

    from beamo_wipe.safety import assert_disk_identity

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disk = selectable_disks(d)[0]
    swapped = replace(disk, wwn="WWN-CHANGED")
    with pytest.raises(SafetyError, match="identity"):
        assert_disk_identity(swapped, d)


def test_char_device_is_not_a_wipe_target():
    from beamo_wipe.safety import assert_existing_is_block_device

    if not Path("/dev/null").exists():
        pytest.skip("no /dev/null")
    with pytest.raises(SafetyError, match="block device"):
        assert_existing_is_block_device("/dev/null")


def test_identity_change_refuses_wipe(monkeypatch, tmp_path):
    from dataclasses import replace

    from beamo_wipe.safety import assert_disk_identity

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disk = selectable_disks(d)[0]
    swapped = replace(disk, serial="DIFFERENT-SERIAL")
    with pytest.raises(SafetyError, match="identity"):
        assert_disk_identity(swapped, d)
