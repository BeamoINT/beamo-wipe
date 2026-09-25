"""Interrupted evidence publication must only clean up its own temporary inode."""

import os

import pytest

from beamo_wipe import evidence


def test_failed_temp_cleanup_preserves_replacement_file(tmp_path, monkeypatch):
    destination = tmp_path / "result.json"
    replacement = tmp_path / "other-writer.json"
    replacement.write_bytes(b"other writer's data")
    original_unlink = os.unlink
    temp_path = None

    def replace_before_temp_unlink(name, *args, **kwargs):
        nonlocal temp_path
        if temp_path is None and str(name).startswith(".result.json.tmp."):
            temp_path = tmp_path / str(name)
            os.replace(replacement, temp_path)
            raise OSError("interrupted temporary cleanup")
        return original_unlink(name, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "unlink", replace_before_temp_unlink)
    with pytest.raises(evidence.EvidenceFinalizationError):
        evidence._atomic_write_bytes(destination, b"our result")

    assert temp_path is not None
    assert temp_path.read_bytes() == b"other writer's data"
    assert not destination.exists()


def test_exclusive_temp_collision_preserves_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence.time, "time_ns", lambda: 123456)
    destination = tmp_path / "result.json"
    temporary = tmp_path / f".result.json.tmp.{os.getpid()}.123456"
    temporary.write_bytes(b"existing private file")

    with pytest.raises(FileExistsError):
        evidence._atomic_write_bytes(destination, b"our result")

    assert temporary.read_bytes() == b"existing private file"
    assert not destination.exists()


def test_replaced_temp_source_cannot_be_published_as_our_evidence(
    tmp_path, monkeypatch
):
    destination = tmp_path / "result.json"
    replacement = tmp_path / "other-writer.json"
    replacement.write_bytes(b"foreign evidence")
    original_link = os.link

    def replace_before_link(source, dest, *args, **kwargs):
        if str(source).startswith(".result.json.tmp."):
            os.replace(replacement, tmp_path / str(source))
        return original_link(source, dest, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "link", replace_before_link)
    with pytest.raises(evidence.EvidenceFinalizationError):
        evidence._atomic_write_bytes(destination, b"our result")

    assert destination.read_bytes() == b"foreign evidence"
