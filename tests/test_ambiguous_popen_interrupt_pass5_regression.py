"""An interrupted Popen can leave an unregistered child holding the wipe lock."""

import pytest

from beamo_wipe.models import MethodId, Screen, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner
from test_refresh_disks import authorized


def test_interrupted_popen_keeps_shutdown_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running", lambda **_: False
    )
    wizard = authorized()
    wizard.dry_run = False
    wizard.preview = False
    wizard._rediscover = lambda: wizard.discovery
    runner = NwipeRunner(binary="/bin/true")
    wizard.runner = runner
    attempted = []

    def interrupted_after_spawn(_argv, **_kwargs):
        attempted.append(True)
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.subprocess.Popen", interrupted_after_spawn
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            wizard.confirm_erase()
        assert attempted
        assert runner._proc is None
        assert runner._lock_fd is not None
        assert not runner.start_not_spawned()
        wizard.shutdown()
        assert wizard.wants_shutdown is False
        assert wizard.screen == Screen.WORKING
    finally:
        runner._release_wipe_lock()


def test_interrupted_pre_spawn_log_preparation_releases_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    runner = NwipeRunner(binary="/bin/true")
    request = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )

    def interrupted_log_preparation(_logfile, _device):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.truncate_log_file", interrupted_log_preparation
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            runner.start(request)
        assert runner.start_not_spawned()
    finally:
        if runner._lock_fd is not None:
            runner._release_wipe_lock()


def test_interrupted_pre_spawn_inhibitor_releases_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.resolve_nwipe_binary", lambda _: "/usr/bin/nwipe"
    )
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running", lambda **_: False
    )
    for name in (
        "require_real_live_for_nwipe",
        "_verify_pinned_nwipe",
        "assert_existing_is_block_device",
        "assert_size_unchanged",
        "assert_local_device_transport",
        "assert_not_boot",
        "_recheck_identity_under_lock",
    ):
        monkeypatch.setattr("beamo_wipe.nwipe_runner." + name, lambda *_, **__: None)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.block_rdev",
        lambda path: 11 if path == "/dev/vda" else 22,
    )
    runner = NwipeRunner()
    request = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
        device_rdev=11,
        boot_rdev=22,
    )

    def interrupted_inhibitor():
        raise KeyboardInterrupt

    monkeypatch.setattr(runner._sleep_inhibit, "start", interrupted_inhibitor)
    try:
        with pytest.raises(KeyboardInterrupt):
            runner.start(request)
        assert runner.start_not_spawned()
    finally:
        if runner._lock_fd is not None:
            runner._release_wipe_lock()
