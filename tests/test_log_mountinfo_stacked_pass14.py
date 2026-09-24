"""Equal-depth mountinfo sources cannot hide a target-backed log mount."""

from pathlib import Path

import pytest

from beamo_wipe.safety import _log_filesystem_is_target


@pytest.mark.parametrize("target_last", (True, False))
def test_stacked_tmp_mounts_are_unproven_when_sources_disagree(
    tmp_path, monkeypatch, target_last
):
    safe = "2 1 0:2 / /tmp rw - tmpfs tmpfs rw\n"
    target = "3 2 8:1 / /tmp rw - ext4 /dev/sda1 rw\n"
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - overlay overlay rw\n"
        + (safe + target if target_last else target + safe),
        encoding="utf-8",
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    log = Path("/tmp/beamo-wipe/wipe.log")
    assert _log_filesystem_is_target(log, "/dev/sda")


def test_single_tmpfs_mount_still_proves_logs_off_target(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - overlay overlay rw\n2 1 0:2 / /tmp rw - tmpfs tmpfs rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    assert not _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")


def test_partially_malformed_mountinfo_cannot_prove_log_owner(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - overlay overlay rw\n"
        "2 1 0:2 / /tmp rw - tmpfs tmpfs rw\n"
        "3 2 8:1 / /tmp rw - ext4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    assert _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")
