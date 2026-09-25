"""The compatibility export must not remove another writer's file on failure."""

import hashlib
import os
from pathlib import Path

import pytest

from beamo_wipe import evidence


def test_sidecar_failure_preserves_replaced_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    data = b'{"test":true}\n'
    source.write_bytes(data)
    Path(str(source) + ".sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  {source.name}\n", encoding="ascii"
    )
    destination = tmp_path / "usb"
    destination.mkdir()
    exported = destination / source.name
    replacement_data = b"a different writer's file"
    replacement = destination / "replacement.json"
    replacement.write_bytes(replacement_data)
    original_writer = evidence._atomic_write_bytes
    calls = 0

    def replace_before_sidecar_error(path, contents):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_writer(path, contents)
        os.replace(replacement, exported)
        raise OSError("sidecar write failed")

    monkeypatch.setattr(evidence, "_atomic_write_bytes", replace_before_sidecar_error)
    with pytest.raises(OSError, match="sidecar write failed"):
        evidence.export_evidence(source, destination)

    assert exported.read_bytes() == replacement_data


def test_atomic_writer_finalization_preserves_replaced_destination(tmp_path, monkeypatch):
    """A failed temporary-link cleanup cannot delete a new owner of the path."""
    dest = tmp_path / "result.json"
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b"replacement")
    original_unlink = os.unlink
    injected = False

    def fail_temp_unlink(path, *args, **kwargs):
        nonlocal injected
        if not injected and str(path).startswith(".result.json.tmp."):
            injected = True
            os.replace(replacement, dest)
            raise OSError("temporary link cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "unlink", fail_temp_unlink)
    with pytest.raises(evidence.EvidenceFinalizationError):
        evidence._atomic_write_bytes(dest, b"original")
    assert dest.read_bytes() == b"replacement"
