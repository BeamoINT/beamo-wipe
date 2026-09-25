"""Malformed release data must be rejected with a controlled verifier error."""

import hashlib
import json

import pytest

from beamo_wipe import __version__
from beamo_wipe.release_manifest import verify_build_manifest


@pytest.mark.parametrize(
    "field",
    [
        None,
        "source",
        "build",
        "nwipe",
        "artifact",
        "nwipe.commit",
        "artifact.iso_size_bytes",
        "source.dirty",
    ],
)
def test_malformed_manifest_sections_fail_with_runtime_error(tmp_path, field):
    iso = tmp_path / f"beamo-wipe-{__version__}-amd64.iso"
    iso.write_bytes(b"synthetic ISO bytes")
    iso_sha = hashlib.sha256(iso.read_bytes()).hexdigest()
    (tmp_path / f"{iso.name}.sha256").write_text(f"{iso_sha}  {iso.name}\n")
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
    if field is None:
        data = []
    else:
        if "." in field:
            section, item = field.split(".")
            data[section][item] = 0 if field == "source.dirty" else []
        else:
            data[field] = []
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        data["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    manifest = tmp_path / "manifest.json"
    raw = json.dumps(data)
    manifest.write_text(raw)
    (tmp_path / "manifest.json.sha256").write_text(
        f"{hashlib.sha256(raw.encode()).hexdigest()}  {manifest.name}\n"
    )

    with pytest.raises(RuntimeError, match="invalid release manifest"):
        verify_build_manifest(manifest)
