"""Manifest generation must preserve unidentified files at its output names."""

import hashlib
import json

import pytest

from beamo_wipe import release_manifest as rm


ISO_NAME = "beamo-wipe-0.2.9-amd64.iso"


def _fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "ROOT", tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    iso = dist / ISO_NAME
    iso.write_bytes(b"disposable ISO fixture")
    digest = hashlib.sha256(iso.read_bytes()).hexdigest()
    manifest = {
        "artifact": {
            "iso_name": ISO_NAME,
            "iso_path": ISO_NAME,
            "iso_sha256": digest,
        },
        "schema_version": 2,
        "beamo_wipe_version": "0.2.9",
    }
    canonical = json.dumps(
        manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    manifest["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return dist / "beamo-wipe-0.2.9-amd64.manifest.json", manifest


@pytest.mark.parametrize("occupied", ["manifest", "checksum", "iso checksum"])
def test_manifest_writer_preserves_unidentified_prior_output(
    tmp_path, monkeypatch, occupied
):
    output, manifest = _fixture(tmp_path, monkeypatch)
    prior = {
        "manifest": output,
        "checksum": output.with_name(output.name + ".sha256"),
        "iso checksum": tmp_path / "dist" / f"{ISO_NAME}.sha256",
    }[occupied]
    prior.write_bytes(b"unrelated user data\n")

    with pytest.raises(RuntimeError, match="unverified prior manifest output"):
        rm.write_manifest(manifest, output)

    assert prior.read_bytes() == b"unrelated user data\n"


def test_manifest_writer_can_update_verified_prior(tmp_path, monkeypatch):
    output, manifest = _fixture(tmp_path, monkeypatch)
    rm.write_manifest(manifest, output)
    updated = {**manifest, "test_evidence": {"measured": True}}
    unsigned = {
        key: value for key, value in updated.items() if key != "_manifest_sha256"
    }
    canonical = json.dumps(
        unsigned, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    updated["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    rm.write_manifest(updated, output)
    assert json.loads(output.read_text())["test_evidence"] == {"measured": True}
