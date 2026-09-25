"""A prior unstarted interface session may restart; erase state may not."""

import fcntl
import os

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.session_recovery import NAME, SessionStore
from beamo_wipe.wizard import RECOVERY_MAY_RUNNING
from test_session_recovery import armed


BOOT = "00000000-0000-0000-0000-000000000001"
BUILD = "a" * 64


def _store(directory):
    return SessionStore(directory, boot=BOOT, build=BUILD).open()


def _prior_preflight(directory):
    first = _store(directory)
    session = first.record["session"]
    first.close()
    return session


def test_previous_unstarted_preflight_starts_fresh_owner_flow(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    old_session = _prior_preflight(directory)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running",
        lambda **_kwargs: False,
    )
    second = _store(directory)
    try:
        assert second.previous and second.record["phase"] == "preflight"
        wizard = make_demo_wizard()
        wizard.enable_session_recovery(second)

        assert not second.previous and not second.invalid
        assert second.record["session"] != old_session
        assert second.record["phase"] == "preflight"
        assert not wizard._startup_blocked and not wizard._recovered
        assert wizard.screen == Screen.SPLASH
        assert not wizard.owner_ok and wizard._wipe_request is None
        wizard.skip_intro()
        assert wizard.screen == Screen.OWNER
        wizard.set_owner(True)
        wizard.continue_owner()
        assert wizard.screen == Screen.PICK
    finally:
        second.close()


@pytest.mark.parametrize("unsafe", ["armed", "invalid", "lock", "pinned", "probe_error"])
def test_previous_preflight_stays_blocked_when_erasure_cannot_be_ruled_out(
    tmp_path, monkeypatch, unsafe
):
    directory = tmp_path / "private"
    first = _store(directory)
    if unsafe == "armed":
        armed(first)
    old_session = first.record["session"]
    first.close()
    if unsafe == "invalid":
        (directory / NAME).write_bytes(b"invalid journal")

    held = None
    if unsafe == "lock":
        held = os.open(directory / "wipe.lock", os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def process_probe(**_kwargs):
        if unsafe == "probe_error":
            raise OSError("process state unknown")
        return unsafe == "pinned"

    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running", process_probe
    )
    second = _store(directory)
    try:
        wizard = make_demo_wizard()
        wizard.enable_session_recovery(second)

        assert second.previous
        assert second.record is None or second.record["session"] == old_session
        assert wizard._startup_blocked and wizard._recovered
        assert wizard.screen in {Screen.PICK_BLOCKED, Screen.DONE}
        assert wizard._wipe_request is None
        wizard.skip_intro()
        wizard.set_owner(True)
        wizard.continue_owner()
        assert wizard.screen in {Screen.PICK_BLOCKED, Screen.DONE}
    finally:
        second.close()
        if held is not None:
            os.close(held)


def test_previous_preflight_journal_rotation_failure_stays_blocked(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    old_session = _prior_preflight(directory)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running",
        lambda **_kwargs: False,
    )
    second = _store(directory)
    try:
        def failed_write(_changes):
            raise OSError("simulated journal failure")

        monkeypatch.setattr(second, "save", failed_write)
        wizard = make_demo_wizard()
        wizard.enable_session_recovery(second)

        assert second.previous and second.record["session"] == old_session
        assert wizard._startup_blocked and wizard.screen == Screen.PICK_BLOCKED
        assert wizard._wipe_request is None
    finally:
        second.close()


def test_previous_preflight_directory_sync_failure_stays_blocked(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    _prior_preflight(directory)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running",
        lambda **_kwargs: False,
    )
    second = _store(directory)
    real_fsync = os.fsync
    try:
        def failed_directory_sync(fd):
            if fd == second.fd:
                raise OSError("simulated uncertain directory sync")
            return real_fsync(fd)

        monkeypatch.setattr("beamo_wipe.session_recovery.os.fsync", failed_directory_sync)
        wizard = make_demo_wizard()
        wizard.enable_session_recovery(second)

        assert second.previous and second.invalid
        assert wizard._startup_blocked and wizard.screen == Screen.PICK_BLOCKED
        assert wizard._wipe_request is None
    finally:
        second.close()


@pytest.mark.parametrize("probe_error", [False, True])
def test_previous_preflight_refuses_shutdown_when_pinned_process_may_run(
    tmp_path, monkeypatch, probe_error
):
    directory = tmp_path / "private"
    _prior_preflight(directory)

    def process_probe(**_kwargs):
        if probe_error:
            raise OSError("process state unknown")
        return True

    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running", process_probe
    )
    second = _store(directory)
    try:
        wizard = make_demo_wizard()
        wizard.enable_session_recovery(second)
        assert wizard._startup_blocked and wizard.screen == Screen.PICK_BLOCKED
        assert wizard.error.startswith(RECOVERY_MAY_RUNNING)

        wizard.shutdown()
        assert wizard.screen == Screen.PICK_BLOCKED
        assert not wizard.wants_shutdown

        # A stale confirmation action must independently recheck liveness.
        wizard.screen = Screen.SHUTDOWN_CONFIRM
        wizard._shutdown_from = Screen.PICK_BLOCKED
        wizard.shutdown_generation += 1
        wizard.confirm_shutdown_without_saving(wizard.shutdown_generation)
        assert not wizard.wants_shutdown
    finally:
        second.close()
