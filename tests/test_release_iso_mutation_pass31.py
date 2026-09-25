"""Release ISO hashing must reject an in-place mutation during the read."""

import os

import pytest

from beamo_wipe import release_manifest


def test_iso_hash_rejects_same_size_in_place_change(tmp_path, monkeypatch):
    iso = tmp_path / "fixture.iso"
    iso.write_bytes(b"A" * 16384)
    real_sha256 = release_manifest.hashlib.sha256
    changed = False

    class MutatingHash:
        def __init__(self):
            self.inner = real_sha256()

        def update(self, chunk):
            nonlocal changed
            if not changed:
                changed = True
                iso.write_bytes(b"B" * 16384)
                os.utime(iso, ns=(iso.stat().st_atime_ns, iso.stat().st_mtime_ns + 1_000_000_000))
            self.inner.update(chunk)

        def hexdigest(self):
            return self.inner.hexdigest()

    monkeypatch.setattr(release_manifest.hashlib, "sha256", MutatingHash)
    with pytest.raises(RuntimeError, match="changed"):
        release_manifest.sha256_file_with_stat(iso)
    assert changed
