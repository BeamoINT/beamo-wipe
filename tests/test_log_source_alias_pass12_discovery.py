"""Mount-source spelling must not make target-backed logs appear safe."""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

from beamo_wipe.safety import _log_filesystem_is_target


LOG = Path("/tmp/beamo-wipe/wipe.log")
TARGET = "/dev/sda"


def _mountinfo(tmp_path: Path, monkeypatch, source: str) -> None:
    path = tmp_path / "mountinfo"
    path.write_text(
        "1 0 0:1 / / rw - overlay overlay rw\n"
        f"2 1 8:1 / /tmp rw - ext4 {source} rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(path))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)


def test_brackets_inside_a_device_alias_do_not_change_log_owner(tmp_path, monkeypatch):
    source = "/dev/disk/by-label/TARGET[production]"
    _mountinfo(tmp_path, monkeypatch, source)
    realpath = os.path.realpath
    lstat = os.lstat

    def fake_realpath(path):
        if path == source:
            return TARGET
        if path == "/dev/disk/by-label/TARGET":
            return "/dev/sdb"
        return realpath(path)

    def fake_lstat(path):
        if path in {TARGET, "/dev/sdb"}:
            return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600,
                                   st_rdev=1 if path == TARGET else 2)
        return lstat(path)

    with monkeypatch.context() as patch:
        patch.setattr(os.path, "realpath", fake_realpath)
        patch.setattr(os, "lstat", fake_lstat)
        assert _log_filesystem_is_target(LOG, TARGET)


def test_typed_log_mount_source_without_physical_owner_is_unproven(tmp_path, monkeypatch):
    _mountinfo(tmp_path, monkeypatch, "LABEL=TARGET")
    assert _log_filesystem_is_target(LOG, TARGET)
