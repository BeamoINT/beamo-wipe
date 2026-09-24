"""A proven pre-spawn failure must leave an explicit retry usable."""

import errno
import json
import os

from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.session_recovery import NAME, SessionStore
from test_refresh_disks import authorized


def test_failed_engine_spawn_can_be_retried_after_fresh_countdown(
    tmp_path, monkeypatch
):
    directory = tmp_path / "private"
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.dry_run = False
        wizard.preview = False
        wizard._rediscover = lambda: wizard.discovery
        wizard.runner = NwipeRunner(binary="/bin/true")
        wizard.enable_session_recovery(store)
        attempts = []

        def failed_spawn(_argv, **_kwargs):
            attempts.append(1)
            raise FileNotFoundError(errno.ENOENT, "simulated exec failure", "/bin/true")

        monkeypatch.setattr("beamo_wipe.nwipe_runner.subprocess.Popen", failed_spawn)
        wizard.confirm_erase()
        assert wizard.screen == Screen.LAST_CHANCE
        assert len(attempts) == 1
        assert store.record["phase"] == "preflight"

        wizard._erase_until = 0
        wizard.confirm_erase()
        assert len(attempts) == 2
        assert store.record["phase"] == "preflight"
    finally:
        store.close()


def test_uncertain_spawn_keeps_journal_armed_and_shutdown_blocked(
    tmp_path, monkeypatch
):
    directory = tmp_path / "private"
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.dry_run = False
        wizard.preview = False
        wizard._rediscover = lambda: wizard.discovery
        runner = NwipeRunner(binary="/bin/true")
        wizard.runner = runner
        wizard.enable_session_recovery(store)

        def uncertain_start(_request):
            runner._proc = object()  # Models a process registered before an error.
            raise OSError(5, "simulated uncertain launch")

        runner.start = uncertain_start
        wizard.confirm_erase()
        assert store.record["phase"] == "armed"
        assert wizard.screen == Screen.WORKING
        wizard.shutdown()
        assert not wizard.wants_shutdown
    finally:
        store.close()


def test_earlier_terminal_result_does_not_block_pre_spawn_retry(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.dry_run = False
        wizard.preview = False
        wizard._rediscover = lambda: wizard.discovery
        runner = NwipeRunner(binary="/bin/true")
        runner.result = WipeResult(True, 0, "finished", str(directory / "previous.log"))
        wizard.runner = runner
        wizard.enable_session_recovery(store)

        def fail_before_spawn(_binary):
            raise OSError(5, "simulated preflight I/O error")

        monkeypatch.setattr(
            "beamo_wipe.nwipe_runner.resolve_nwipe_binary", fail_before_spawn
        )
        wizard.confirm_erase()
        assert wizard.screen == Screen.LAST_CHANCE
        assert store.record["phase"] == "preflight"
    finally:
        store.close()


def test_close_before_spawn_releases_new_journal_reservation(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.dry_run = False
        wizard.preview = False
        wizard._rediscover = lambda: wizard.discovery
        runner = NwipeRunner(binary="/bin/true")
        runner.result = WipeResult(True, 0, "finished", str(directory / "previous.log"))
        wizard.runner = runner
        wizard.enable_session_recovery(store)
        original_arm = store.arm

        def close_after_arm(discovery, request):
            original_arm(discovery, request)
            wizard._start_abort.set()

        monkeypatch.setattr(store, "arm", close_after_arm)
        wizard.confirm_erase()
        assert store.record["phase"] == "preflight"
        assert runner._proc is None
    finally:
        store.close()


def test_uncertain_journal_sync_blocks_retry_before_engine_start(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.dry_run = False
        wizard.preview = False
        wizard._rediscover = lambda: wizard.discovery
        wizard.enable_session_recovery(store)
        original_fsync = os.fsync

        def fail_directory_sync(fd):
            if fd == store.fd:
                raise OSError(5, "simulated directory sync failure")
            return original_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_directory_sync)
            wizard.confirm_erase()
        assert not wizard.runner.started
        wizard._erase_until = 0
        assert store.invalid
        assert store.record["phase"] == "armed"
        assert json.loads(store.read(NAME))["payload"]["phase"] == "armed"
        assert not wizard.erase_enabled
    finally:
        store.close()


def test_failed_disarm_sync_stays_blocked_after_spawn_error(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.dry_run = False
        wizard.preview = False
        wizard._rediscover = lambda: wizard.discovery
        wizard.runner = NwipeRunner(binary="/bin/true")
        wizard.enable_session_recovery(store)

        def failed_spawn(*_args, **_kwargs):
            raise FileNotFoundError(errno.ENOENT, "simulated exec failure", "/bin/true")

        monkeypatch.setattr(
            "beamo_wipe.nwipe_runner.subprocess.Popen",
            failed_spawn,
        )
        original_fsync = os.fsync
        directory_syncs = 0

        def fail_second_directory_sync(fd):
            nonlocal directory_syncs
            if fd == store.fd:
                directory_syncs += 1
                if directory_syncs == 2:
                    raise OSError(5, "simulated disarm sync failure")
            return original_fsync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_second_directory_sync)
            wizard.confirm_erase()
        assert directory_syncs == 2
        assert store.invalid
        assert store.record["phase"] == "preflight"
        wizard._erase_until = 0
        assert not wizard.erase_enabled
        assert wizard.screen == Screen.LAST_CHANCE
    finally:
        store.close()


def test_failed_quiescent_lock_close_blocks_retry(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.dry_run = False
        wizard.preview = False
        wizard._rediscover = lambda: wizard.discovery
        wizard.runner = NwipeRunner(binary="/bin/true")
        wizard.enable_session_recovery(store)

        def failed_spawn(*_args, **_kwargs):
            raise FileNotFoundError(errno.ENOENT, "simulated exec failure", "/bin/true")

        monkeypatch.setattr("beamo_wipe.nwipe_runner.subprocess.Popen", failed_spawn)
        original_close = os.close
        original_release = store._release_quiescent

        def fail_quiescent_release():
            quiescent_fd = store.quiescent

            def fail_quiescent_close(fd):
                if fd == quiescent_fd:
                    original_close(fd)
                    raise OSError(5, "simulated lock close failure")
                return original_close(fd)

            with monkeypatch.context() as patch:
                patch.setattr(os, "close", fail_quiescent_close)
                return original_release()

        monkeypatch.setattr(store, "_release_quiescent", fail_quiescent_release)
        wizard.confirm_erase()
        wizard._erase_until = 0
        assert store.record["phase"] == "preflight"
        assert store.invalid
        assert not wizard.erase_enabled
        assert wizard.screen == Screen.LAST_CHANCE
    finally:
        store.close()


def test_journal_temp_close_error_after_replace_blocks_retry(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    store = SessionStore(
        directory,
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        wizard = authorized()
        wizard.dry_run = False
        wizard.preview = False
        wizard._rediscover = lambda: wizard.discovery
        wizard.enable_session_recovery(store)
        temp_fds = set()
        original_file = store._file
        original_close = os.close

        def track_temp_file(name, *args, **kwargs):
            fd = original_file(name, *args, **kwargs)
            if name.startswith(".recovery-"):
                temp_fds.add(fd)
            return fd

        def close_then_report_error(fd):
            original_close(fd)
            if fd in temp_fds:
                temp_fds.remove(fd)
                raise OSError(5, "simulated temp close failure")

        with monkeypatch.context() as patch:
            patch.setattr(store, "_file", track_temp_file)
            patch.setattr(os, "close", close_then_report_error)
            wizard.confirm_erase()
        wizard._erase_until = 0
        assert store.record["phase"] == "armed"
        assert store.invalid
        assert not wizard.erase_enabled
        assert not wizard.runner.started
    finally:
        store.close()
