"""Ambiguous release JSON must not pass checksum verification."""

import hashlib
import json

import pytest

from beamo_wipe import __version__
from beamo_wipe.release_manifest import verify_build_manifest


def _sidecar(path, digest):
    path.with_name(path.name + ".sha256").write_text(
        f"{digest}  {path.name}\n", encoding="ascii"
    )


def test_build_manifest_rejects_duplicate_field_with_recomputed_checksums(tmp_path):
    iso = tmp_path / f"beamo-wipe-{__version__}-amd64.iso"
    iso.write_bytes(b"synthetic ISO bytes")
    iso_sha = hashlib.sha256(iso.read_bytes()).hexdigest()
    _sidecar(iso, iso_sha)

    data = {
        "schema_version": 2,
        "beamo_wipe_version": __version__,
        "nwipe": {"version": "0.42", "commit": "a" * 40},
        "source": {"commit": "b" * 40, "dirty": False},
        "build": {"release_build_id": "local"},
        "artifact": {
            "iso_name": iso.name,
            "iso_path": iso.name,
            "iso_sha256": iso_sha,
            "iso_size_bytes": iso.stat().st_size,
        },
    }
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    data["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    manifest = tmp_path / "build.manifest.json"
    raw = json.dumps(data, indent=2, sort_keys=True) + "\n"
    manifest.write_text(raw, encoding="utf-8")
    _sidecar(manifest, hashlib.sha256(raw.encode()).hexdigest())
    verify_build_manifest(manifest)

    # A last-key-wins reader sees the checked source; a first-key-wins
    # reader sees a different source even though both sidecars are valid.
    raw = raw.replace(
        '  "source": {',
        '  "source": {"commit": "' + "c" * 40 + '", "dirty": true},\n  "source": {',
        1,
    )
    manifest.write_text(raw, encoding="utf-8")
    _sidecar(manifest, hashlib.sha256(raw.encode()).hexdigest())
    with pytest.raises(RuntimeError, match="duplicate JSON field"):
        verify_build_manifest(manifest)
