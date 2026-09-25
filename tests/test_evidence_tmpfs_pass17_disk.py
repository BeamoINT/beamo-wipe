# SPDX-License-Identifier: GPL-3.0-or-later
"""Even a report without a selected disk remains memory-only on live media."""

import pytest

from beamo_wipe.evidence import write_evidence_atomic
from beamo_wipe.safety import SafetyError


def test_targetless_live_evidence_rejects_persistent_log_directory(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("1 0 0:1 / / rw - ext4 /dev/root rw\n", encoding="utf-8")
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr("beamo_wipe.safety.is_preview_env", lambda: False)

    with pytest.raises(SafetyError, match="tmpfs"):
        write_evidence_atomic({"outcome": "failed"}, log_dir=tmp_path)

    assert not list(tmp_path.glob("result-*"))
