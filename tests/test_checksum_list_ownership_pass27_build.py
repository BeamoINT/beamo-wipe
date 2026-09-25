"""Finalization must preserve unrelated checksum lists and accept verified ones."""

import hashlib
import json

import pytest

from beamo_wipe import ci_evidence, release_manifest


def test_finalizer_preserves_unverified_checksum_list(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_ID", "local")
    dist = tmp_path / "dist"
    evidence = dist / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "packages.json").write_text("{}")
    sums = dist / "SHA256SUMS"
    sums.write_bytes(b"unrelated owner notes\n")
    artifact = {"iso_name": "beamo-wipe-0.2.9-amd64.iso"}
    previous = {
        "source": {"commit": "a" * 40},
        "build": {"release_build_id": "local"},
        "artifact": artifact,
        "beamo_wipe_version": "0.2.9",
        "dependencies": {},
        "live_build_inputs": {},
        "nwipe": {},
    }
    monkeypatch.setattr(
        release_manifest,
        "verify_build_manifest",
        lambda *_args, **_kwargs: json.dumps(previous).encode(),
    )
    monkeypatch.setattr(release_manifest, "git_commit", lambda: "a" * 40)
    monkeypatch.setattr(
        release_manifest, "generate_manifest", lambda **_kwargs: previous
    )
    monkeypatch.setattr(release_manifest, "write_manifest", lambda *_args: None)
    monkeypatch.setattr(
        release_manifest, "verify_manifest", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(release_manifest, "sha256_file", lambda *_args: "b" * 64)
    monkeypatch.setattr(ci_evidence, "load_receipts", lambda *_args: [])
    monkeypatch.setattr(ci_evidence, "_require_evidence_directory", lambda *_args: None)

    with pytest.raises(RuntimeError, match="unverified prior checksum list"):
        ci_evidence.finalize(tmp_path)

    assert sums.read_bytes() == b"unrelated owner notes\n"


@pytest.mark.parametrize("schema,version", [(1, "0.1.0"), (2, "0.2.9")])
def test_prior_checksum_list_accepts_verified_bundle(tmp_path, schema, version):
    dist = tmp_path / "dist"
    dist.mkdir()
    iso_name = f"beamo-wipe-{version}-amd64.iso"
    manifest_name = f"beamo-wipe-{version}-amd64.manifest.json"
    iso = dist / iso_name
    iso.write_bytes(b"disposable old ISO")
    iso_sha = hashlib.sha256(iso.read_bytes()).hexdigest()
    manifest = {
        "schema_version": schema,
        "beamo_wipe_version": version,
        "artifact": {
            "iso_name": iso_name,
            "iso_path": iso_name if schema == 2 else f"/old/build/dist/{iso_name}",
            "iso_sha256": iso_sha,
            "iso_size_bytes": iso.stat().st_size,
        },
    }
    canonical = json.dumps(
        manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    manifest["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    prior = dist / manifest_name
    prior.write_text(json.dumps(manifest))
    manifest_sha = hashlib.sha256(prior.read_bytes()).hexdigest()
    (dist / f"{iso_name}.sha256").write_text(f"{iso_sha}  {iso_name}\n")
    manifest_sidecar = dist / f"{manifest_name}.sha256"
    manifest_sidecar.write_text(f"{manifest_sha}  {manifest_name}\n")
    (dist / "SHA256SUMS").write_text(
        f"{iso_sha}  {iso_name}\n{manifest_sha}  {manifest_name}\n"
    )

    release_manifest.require_verified_prior_checksum_list(dist)

    manifest_sidecar.write_text("unrelated checksum\n")
    with pytest.raises(RuntimeError, match="unverified prior checksum list"):
        release_manifest.require_verified_prior_checksum_list(dist)
