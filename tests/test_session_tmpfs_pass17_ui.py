# SPDX-License-Identifier: GPL-3.0-or-later
"""Fake mount tables prove the live recovery journal stays in memory."""

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.session_recovery import SessionStore


BOOT = "00000000-0000-0000-0000-000000000001"
BUILD = "a" * 64


@pytest.mark.parametrize("filesystem", ["ext4", "overlay"])
def test_production_journal_refuses_disk_backed_tmp(
    tmp_path, monkeypatch, filesystem
):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 8:1 / / rw - ext4 /dev/sda1 rw\n"
        f"2 1 8:2 / {tmp_path} rw - {filesystem} /dev/sdb1 rw\n"
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    store = SessionStore(tmp_path / "journal", boot=BOOT, build=BUILD)
    # Use a disposable directory, exercising the production-only check.
    store._production_directory = True
    try:
        with pytest.raises(SafetyError):
            store.open()
    finally:
        store.close()


def test_production_journal_accepts_genuine_tmpfs(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 8:1 / / rw - ext4 /dev/sda1 rw\n"
        f"2 1 0:2 / {tmp_path} rw - tmpfs tmpfs rw\n"
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    store = SessionStore(tmp_path / "journal", boot=BOOT, build=BUILD)
    store._production_directory = True
    try:
        store.open()
        assert store.record is not None
    finally:
        store.close()
