# SPDX-License-Identifier: GPL-3.0-or-later
"""Export must reach a second USB outside the log dir (fake devices only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from beamo_wipe.evidence import (
    export_evidence,
    verify_evidence_checksum,
    write_evidence_atomic,
)
from beamo_wipe.safety import SafetyError


def _seed_evidence(path: Path) -> None:
    write_evidence_atomic(
        {"schema_version": 1, "outcome": "completed"},
        log_dir=path.parent,
        device_path="/dev/sda",
        target_device="/dev/sda",
    )
    # write_evidence_atomic mints its own timestamped name; link it to the
    # expected seed name plus sidecar so the export has a checksum to carry.
    minted = sorted(path.parent.glob("result-sda-*.json"))
    assert minted, "seed evidence was not written"
    newest = minted[-1]
    sidecar = Path(str(newest) + ".sha256")
    assert sidecar.exists()
    path.write_bytes(newest.read_bytes())
    Path(str(path) + ".sha256").write_bytes(sidecar.read_bytes())


def test_export_to_second_usb_outside_log_dir(tmp_path, monkeypatch):
    """The log dir (/tmp/beamo-wipe) is not the export dest (second USB).

    Regression: export_evidence required the dest to live under the log
    directory, so every real export to /media/... failed closed with
    "Log file must live under the Beamo Wipe log directory."
    """
    import beamo_wipe.safety as safety

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(safety, "default_log_dir", lambda: log_dir)
    src = log_dir / "result-sda-1.json"
    _seed_evidence(src)
    second = tmp_path / "second_usb"
    second.mkdir()
    assert second not in log_dir.parents and log_dir not in second.parents
    out = export_evidence(src, second, target_device="/dev/sda", boot_device="/dev/sdb")
    assert Path(out).exists()
    assert Path(out).parent == second
    assert verify_evidence_checksum(Path(out))


def test_export_still_refuses_dest_on_target(tmp_path, monkeypatch):
    """Off-target checks stay fail-closed after the log-dir fix."""
    import beamo_wipe.safety as safety

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(safety, "default_log_dir", lambda: log_dir)
    src = log_dir / "result-sda-1.json"
    _seed_evidence(src)
    second = tmp_path / "second_usb"
    second.mkdir()
    # Dest filesystem IS the target: path-prefix check must still refuse.
    with pytest.raises(SafetyError):
        export_evidence(src, second, target_device=str(second))
    assert not list(second.glob("result-*"))
