"""QEMU evidence hashing must stay inside the checked directory inode."""

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from beamo_wipe import ci_evidence
from beamo_wipe.ci_evidence import qemu_evidence_hashes


def test_qemu_hash_does_not_follow_replaced_directory(tmp_path, monkeypatch):
    evidence = tmp_path / "qemu-evidence"
    evidence.mkdir()
    (evidence / "summary.txt").write_bytes(b"real QEMU evidence\n")
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "summary.txt").write_bytes(b"unrelated private data\n")

    original_iterdir = Path.iterdir

    def swap_after_directory_check(path):
        if path == evidence:
            evidence.rename(tmp_path / "original-evidence")
            evidence.symlink_to(outside, target_is_directory=True)
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", swap_after_directory_check)
    private_digest = hashlib.sha256(b"unrelated private data\n").hexdigest()
    try:
        try:
            hashes = qemu_evidence_hashes(evidence)
        except RuntimeError:
            return
        assert hashes["summary.txt"] != private_digest
    finally:
        if evidence.is_symlink():
            evidence.unlink()


@pytest.mark.parametrize("change", ["in_place", "replace_name"])
def test_qemu_hash_rejects_file_changed_during_read(tmp_path, monkeypatch, change):
    evidence = tmp_path / "qemu-evidence"
    evidence.mkdir()
    source = evidence / "summary.txt"
    source.write_bytes(b"A" * 131072)
    original_stat = source.stat()
    real_sha256 = ci_evidence.hashlib.sha256
    changed = False

    class MutatingHash:
        def __init__(self):
            self.inner = real_sha256()

        def update(self, chunk):
            nonlocal changed
            if not changed:
                changed = True
                if change == "in_place":
                    source.write_bytes(b"B" * 131072)
                    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
                else:
                    replacement = tmp_path / "replacement"
                    replacement.write_bytes(b"B" * 131072)
                    os.replace(replacement, source)
            self.inner.update(chunk)

        def hexdigest(self):
            return self.inner.hexdigest()

    monkeypatch.setattr(ci_evidence.hashlib, "sha256", MutatingHash)
    if change == "in_place":
        # Overlay filesystems can report the same timestamp for a rapid
        # rewrite, and the test restores mtime. Hide metadata changes so the
        # content check, rather than host clock resolution, proves detection.
        real_fstat, real_stat = os.fstat, os.stat

        def stable_metadata(info):
            if (info.st_dev, info.st_ino) != (original_stat.st_dev, original_stat.st_ino):
                return info
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_size=info.st_size,
                st_mtime_ns=original_stat.st_mtime_ns,
                st_ctime_ns=original_stat.st_ctime_ns,
            )

        def stable_fstat(fd):
            return stable_metadata(real_fstat(fd))

        def stable_stat(path, *args, **kwargs):
            return stable_metadata(real_stat(path, *args, **kwargs))

        monkeypatch.setattr(ci_evidence.os, "fstat", stable_fstat)
        monkeypatch.setattr(ci_evidence.os, "stat", stable_stat)
    with pytest.raises(RuntimeError, match="changed"):
        qemu_evidence_hashes(evidence)
    assert changed
