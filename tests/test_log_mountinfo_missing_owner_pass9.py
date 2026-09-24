"""A readable but unusable mount table must not permit log placement."""

from pathlib import Path

from beamo_wipe.safety import _log_filesystem_is_target


def test_empty_mountinfo_cannot_prove_log_is_off_target(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("", encoding="utf-8")
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    assert _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")


def test_unrelated_mount_rows_cannot_prove_log_owner(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / /media/other rw - ext4 /dev/sdb1 rw\n", encoding="utf-8"
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    assert _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")


def test_tmpfs_mount_owner_proves_log_is_off_target(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - overlay overlay rw\n2 1 0:2 / /tmp rw - tmpfs tmpfs rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)
    assert not _log_filesystem_is_target(Path("/tmp/beamo-wipe/wipe.log"), "/dev/sda")
