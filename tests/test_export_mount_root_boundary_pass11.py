"""A linked report mount root must not redirect worker writes."""

import stat
import subprocess
from types import SimpleNamespace

import pytest

from beamo_wipe import support_export as export
from beamo_wipe.safety import SafetyError


def test_export_worker_rejects_linked_mount_root_before_writing(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o755)
    root = tmp_path / "mount-root"
    root.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(export, "MOUNT_ROOT", root)
    monkeypatch.setattr(
        export,
        "_run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1),
    )
    monkeypatch.setattr(export, "_mounted_exact", lambda *_args: False)

    with pytest.raises(SafetyError):
        export._persist_and_verify_report(
            SimpleNamespace(fstype="vfat"), None, b"", "unavailable", 0
        )

    assert stat.S_IMODE(outside.stat().st_mode) == 0o755
    assert list(outside.iterdir()) == []
