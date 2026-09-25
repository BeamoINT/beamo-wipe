"""A signed release must describe the engine bytes configured for this build."""

from __future__ import annotations

import hashlib
import json

import pytest

from beamo_wipe import NWIPE_PINNED_COMMIT, __version__
from beamo_wipe import release_manifest as manifest


@pytest.mark.parametrize(
    ("engine", "accepted"),
    [
        ({"commit": "a" * 40, "pinned_path": "/usr/lib/beamo-wipe/nwipe"}, False),
        ({"commit": NWIPE_PINNED_COMMIT, "pinned_path": "/usr/bin/nwipe"}, False),
        ({"commit": NWIPE_PINNED_COMMIT, "pinned_path": "/usr/lib/beamo-wipe/nwipe"}, True),
    ],
)
def test_release_verifier_requires_configured_nwipe_pin(tmp_path, monkeypatch, engine, accepted):
    iso = tmp_path / f"beamo-wipe-{__version__}-amd64.iso"
    iso.write_bytes(b"synthetic ISO bytes")
    iso_sha = hashlib.sha256(iso.read_bytes()).hexdigest()
    (tmp_path / f"{iso.name}.sha256").write_text(f"{iso_sha}  {iso.name}\n")
    source_commit = "b" * 40
    data = {
        "schema_version": manifest.SCHEMA_VERSION,
        "beamo_wipe_version": __version__,
        "source": {"commit": source_commit, "dirty": False},
        "build": {"release_build_id": "local"},
        "nwipe": {"version": "0.42", **engine},
        "artifact": {
            "iso_name": iso.name,
            "iso_path": iso.name,
            "iso_sha256": iso_sha,
            "iso_size_bytes": iso.stat().st_size,
        },
        "test_evidence": {"measured": True},
        "installed_packages": {"measured": True},
    }
    # The real evidence validator has its own coverage. Keep the complete
    # release-verifier path and isolate the engine provenance contract here.
    monkeypatch.setattr(
        manifest,
        "verify_release_evidence",
        lambda _value: {"iso": {"source_commit": source_commit, "build_id": "local"}},
    )
    monkeypatch.setattr(
        manifest,
        "verify_package_inventory",
        lambda _value: {"source_commit": source_commit},
    )
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    data["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    target = tmp_path / "release.manifest.json"
    raw = (json.dumps(data, sort_keys=True) + "\n").encode()
    target.write_bytes(raw)
    (tmp_path / f"{target.name}.sha256").write_text(
        f"{hashlib.sha256(raw).hexdigest()}  {target.name}\n"
    )

    if accepted:
        assert manifest.verify_manifest(target) == raw
    else:
        with pytest.raises(RuntimeError, match="nwipe pin"):
            manifest.verify_manifest(target)
