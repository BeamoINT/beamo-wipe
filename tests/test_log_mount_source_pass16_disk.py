"""A log mount must have a proven off-target filesystem owner."""

from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from beamo_wipe.safety import _log_filesystem_is_target


@pytest.mark.parametrize(
    ("filesystem", "source"),
    [
        ("overlay", "overlay"),
        ("ext4", "opaque"),
        ("ext4", "tmpfs"),
    ],
)
def test_non_device_log_mount_must_be_genuine_tmpfs(
    tmp_path, monkeypatch, filesystem, source
):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        f"1 0 0:1 / / rw - overlay overlay rw\n"
        f"2 1 0:2 / /tmp rw - {filesystem} {source} rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)

    assert _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")


def test_genuine_tmpfs_remains_off_target(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - overlay overlay rw\n"
        "2 1 0:2 / /tmp rw - tmpfs tmpfs rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)

    assert not _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")


def test_other_block_device_does_not_make_log_location_tmpfs(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - overlay overlay rw\n"
        "2 1 8:17 / /tmp rw - ext4 /dev/sdb1 rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    from beamo_wipe import safety

    real_lstat = safety.os.lstat

    def fake_lstat(path, *args, **kwargs):
        if str(path) in {"/dev/sda", "/dev/sdb1"}:
            return SimpleNamespace(
                st_mode=stat.S_IFBLK,
                st_rdev=11 if str(path) == "/dev/sda" else 12,
            )
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(safety.os, "lstat", fake_lstat)

    assert _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")


def test_non_tmpfs_mountinfo_does_not_block_fake_preview(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 8:17 / /tmp rw - ext4 /dev/sdb1 rw\n", encoding="utf-8"
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: True)

    assert not _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")
