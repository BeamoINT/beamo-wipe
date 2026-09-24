"""Ambiguous release metadata must fail at the publisher boundary."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from beamo_wipe.release_signing import fingerprint, generate_keypair, key_id
from beamo_wipe.release_signing import load_key_registry, verify_with_registry


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_wipe_publisher_pass9", ROOT / "scripts" / "publish_release_gcs.py"
)
assert SPEC and SPEC.loader
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


def test_usb_metadata_rejects_duplicate_checksum_field(tmp_path):
    version = "0.2.9"
    iso = tmp_path / f"beamo-wipe-{version}-amd64.iso"
    image = tmp_path / f"beamo-wipe-{version}-amd64.img"
    iso.write_bytes(b"fixture ISO")
    image.write_bytes(b"fixture USB")

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    image.with_suffix(".img.sha256").write_text(f"{digest(image)}  {image.name}\n")
    metadata = {
        "schema_version": 1,
        "image": image.name,
        "sha256": digest(image),
        "iso": iso.name,
        "iso_sha256": digest(iso),
        "layout": "MBR, one active FAT32 partition at sector 2048",
        "size": image.stat().st_size,
    }
    valid = json.dumps(metadata)
    ambiguous = valid.replace(
        '"iso_sha256":', '"iso_sha256": "' + "0" * 64 + '", "iso_sha256":'
    )
    image.with_suffix(".img.json").write_text(ambiguous)
    with pytest.raises(PUBLISHER.PublishError, match="duplicate"):
        PUBLISHER._verify_usb_image(tmp_path, version)


def test_registry_rejects_duplicate_key_status(tmp_path, monkeypatch):
    private, public = generate_keypair()
    key = key_id(public)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "beamo-wipe-0.2.9-amd64.manifest.json").write_bytes(b"{}")
    registry = tmp_path / "packaging" / "release-keys" / "keys.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema": "beamo-wipe-release-keys/1",
                "keys": {
                    key: {
                        "fingerprint": fingerprint(public),
                        "public_key": base64.b64encode(public).decode("ascii"),
                        "status": "active",
                    }
                },
            }
        ).replace('"status": "active"', '"status": "revoked", "status": "active"')
    )
    monkeypatch.setattr(PUBLISHER, "ROOT", tmp_path)
    monkeypatch.setattr(PUBLISHER, "_read_signing_key", lambda: private)
    with pytest.raises(PUBLISHER.PublishError, match="duplicate"):
        PUBLISHER._sign_release_manifest(dist, "0.2.9")


def test_signer_returns_digest_of_verified_signature_bytes(tmp_path, monkeypatch):
    private, public = generate_keypair()
    key = key_id(public)
    dist = tmp_path / "dist"
    dist.mkdir()
    manifest_bytes = b'{"beamo_wipe_version":"0.2.9"}'
    manifest = dist / "beamo-wipe-0.2.9-amd64.manifest.json"
    manifest.write_bytes(manifest_bytes)
    registry = tmp_path / "packaging" / "release-keys" / "keys.json"
    registry.parent.mkdir(parents=True)
    entry = {
        "fingerprint": fingerprint(public),
        "public_key": base64.b64encode(public).decode("ascii"),
        "status": "active",
    }
    registry.write_text(
        json.dumps({"schema": "beamo-wipe-release-keys/1", "keys": {key: entry}})
    )
    monkeypatch.setattr(PUBLISHER, "ROOT", tmp_path)
    monkeypatch.setattr(PUBLISHER, "_read_signing_key", lambda: private)
    signature_path, signature_sha = PUBLISHER._sign_release_manifest(
        dist, "0.2.9", manifest_bytes=manifest_bytes
    )
    assert signature_path == Path(f"{manifest}.sig")
    assert hashlib.sha256(signature_path.read_bytes()).hexdigest() == signature_sha
    assert (
        verify_with_registry(
            manifest_bytes,
            json.loads(signature_path.read_text()),
            load_key_registry(json.loads(registry.read_text())),
        )["key_id"]
        == key
    )


@pytest.mark.parametrize("replace_at", ["verify", "sign"])
def test_publication_rejects_manifest_replaced_after_validation(
    tmp_path, monkeypatch, replace_at
):
    """A signer must never publish different bytes than the verifier accepted."""
    from beamo_wipe import ci_evidence, release_manifest

    version = "0.2.9"
    build_id = "12345678-1234-1234-1234-123456789abc"
    commit = "a" * 40
    dist = tmp_path / "dist"
    dist.mkdir()
    manifest = dist / f"beamo-wipe-{version}-amd64.manifest.json"
    common = {
        "source": {"commit": commit},
        "build": {"release_build_id": build_id},
        "artifact": {"iso_sha256": "c" * 64},
        "test_evidence": {"gates": {}},
    }
    accepted = json.dumps({**common, "note": "validated"}).encode()
    replacement = json.dumps({**common, "note": "unverified replacement"}).encode()
    manifest.write_bytes(accepted)
    uploads = {}

    def verify_then_replace(path):
        assert path.read_bytes() == accepted
        if replace_at == "verify":
            path.write_bytes(replacement)
        return accepted

    def upload_file(path, object_name):
        uploads[object_name] = hashlib.sha256(path.read_bytes()).hexdigest()

    def upload_stream(object_name, stream, _size):
        uploads[object_name] = hashlib.sha256(stream.read()).hexdigest()

    def sign_manifest(_dist, _version, *, manifest_bytes):
        assert manifest_bytes == accepted
        signature = Path(f"{manifest}.sig")
        signature.write_bytes(b"fixture signature")
        if replace_at == "sign":
            manifest.write_bytes(replacement)
        return signature, hashlib.sha256(b"fixture signature").hexdigest()

    monkeypatch.setattr(PUBLISHER, "ROOT", tmp_path)
    monkeypatch.setattr(PUBLISHER, "_release_inputs", lambda _version: [manifest])
    monkeypatch.setattr(PUBLISHER, "_verify_source", lambda _version: commit)
    monkeypatch.setattr(PUBLISHER, "_sign_release_manifest", sign_manifest)
    monkeypatch.setattr(PUBLISHER, "_verify_sha256sums", lambda *_args: None)
    monkeypatch.setattr(PUBLISHER, "_qemu_tested_usb_sha", lambda _root: "b" * 64)
    monkeypatch.setattr(
        PUBLISHER, "_verify_usb_image", lambda *_args: ("b" * 64, "d" * 64)
    )
    monkeypatch.setattr(PUBLISHER, "_upload_file", upload_file)
    monkeypatch.setattr(PUBLISHER, "_upload_stream", upload_stream)
    monkeypatch.setattr(
        PUBLISHER, "_remote_sha256", lambda object_name: uploads[object_name]
    )
    monkeypatch.setattr(release_manifest, "verify_manifest", verify_then_replace)
    monkeypatch.setattr(ci_evidence, "load_receipts", lambda _path: [])
    monkeypatch.setenv("PUBLISH_RELEASE", "true")
    monkeypatch.setenv("SKIP_ISO", "false")
    monkeypatch.setenv("SKIP_QEMU", "false")
    monkeypatch.setenv("BEAMO_WIPE_VERSION", version)
    monkeypatch.setenv("BUILD_ID", build_id)
    with pytest.raises(PUBLISHER.PublishError, match="changed after verification"):
        PUBLISHER.publish()


@pytest.mark.parametrize(
    "scenario",
    [
        "matching",
        "all_sidecars_matching",
        "image_replaced",
        "log_replaced",
        "iso_replaced",
        "sidecar_replaced",
        "metadata_replaced",
        "sha256sums_replaced",
        "signature_replaced",
    ],
)
def test_publication_binds_usb_image_to_qemu(tmp_path, monkeypatch, scenario):
    """Matching metadata cannot make an untested image the tested QEMU input."""
    from beamo_wipe import ci_evidence, release_manifest

    version = "0.2.9"
    build_id = "12345678-1234-1234-1234-123456789abc"
    commit = "a" * 40
    dist = tmp_path / "dist"
    dist.mkdir()
    evidence = dist / "evidence"
    evidence.mkdir()
    tested_sha = hashlib.sha256(b"tested USB image").hexdigest()
    qemu_log = evidence / "qemu.log"
    qemu_log.write_text(f"[qemu-verify] usb_image_sha256={tested_sha}\n")
    receipt = {
        "gate": "qemu",
        "status": "pass",
        "log_sha256": hashlib.sha256(qemu_log.read_bytes()).hexdigest(),
    }
    iso = dist / f"beamo-wipe-{version}-amd64.iso"
    image = dist / f"beamo-wipe-{version}-amd64.img"
    original_iso_sha = hashlib.sha256(b"fixture ISO").hexdigest()
    iso.write_bytes(
        b"replacement ISO" if scenario == "iso_replaced" else b"fixture ISO"
    )
    image.write_bytes(
        b"different USB image"
        if scenario in {"image_replaced", "log_replaced"}
        else b"tested USB image"
    )
    image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
    iso_sha = hashlib.sha256(iso.read_bytes()).hexdigest()
    image.with_suffix(".img.sha256").write_text(f"{image_sha}  {image.name}\n")
    image.with_suffix(".img.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "image": image.name,
                "sha256": image_sha,
                "iso": iso.name,
                "iso_sha256": iso_sha,
                "layout": "MBR, one active FAT32 partition at sector 2048",
                "size": image.stat().st_size,
            }
        )
    )
    manifest = dist / f"beamo-wipe-{version}-amd64.manifest.json"
    manifest_bytes = json.dumps(
        {
            "source": {"commit": commit},
            "build": {"release_build_id": build_id},
            "artifact": {"iso_sha256": original_iso_sha},
            "test_evidence": {"gates": {"qemu": receipt}},
        }
    ).encode()
    manifest.write_bytes(manifest_bytes)
    iso_sidecar = Path(f"{iso}.sha256")
    image_sidecar = Path(f"{image}.sha256")
    manifest_sidecar = Path(f"{manifest}.sha256")
    sums = dist / "SHA256SUMS"
    iso_sidecar.write_text(f"{iso_sha}  {iso.name}\n")
    manifest_sidecar.write_text(
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  {manifest.name}\n"
    )
    sums.write_text(
        f"{iso_sha}  {iso.name}\n{hashlib.sha256(manifest_bytes).hexdigest()}  {manifest.name}\n"
    )
    uploads = {}

    def sign_manifest(_dist, _version, *, manifest_bytes):
        signature = Path(f"{manifest}.sig")
        signature.write_bytes(b"fixture signature")
        if scenario == "signature_replaced":
            signature.write_bytes(b"corrupted signature")
        return signature, hashlib.sha256(b"fixture signature").hexdigest()

    def upload_file(path, object_name):
        uploads[object_name] = hashlib.sha256(path.read_bytes()).hexdigest()

    def upload_stream(object_name, stream, _size):
        uploads[object_name] = hashlib.sha256(stream.read()).hexdigest()

    monkeypatch.setattr(PUBLISHER, "ROOT", tmp_path)
    inputs = [iso, image, qemu_log]
    if scenario in {"all_sidecars_matching", "sha256sums_replaced"}:
        inputs.extend([iso_sidecar, image_sidecar, manifest_sidecar, sums])
    if scenario == "sidecar_replaced":
        inputs.append(image_sidecar)
    if scenario == "metadata_replaced":
        inputs.append(image.with_suffix(".img.json"))
    if scenario == "signature_replaced":
        inputs.append(Path(f"{manifest}.sig"))
    monkeypatch.setattr(PUBLISHER, "_release_inputs", lambda _version: inputs)
    monkeypatch.setattr(PUBLISHER, "_verify_source", lambda _version: commit)
    monkeypatch.setattr(PUBLISHER, "_sign_release_manifest", sign_manifest)
    monkeypatch.setattr(PUBLISHER, "_verify_sha256sums", lambda *_args: None)
    monkeypatch.setattr(PUBLISHER, "_upload_file", upload_file)
    monkeypatch.setattr(PUBLISHER, "_upload_stream", upload_stream)
    monkeypatch.setattr(
        PUBLISHER, "_remote_sha256", lambda object_name: uploads[object_name]
    )
    if scenario in {"sidecar_replaced", "metadata_replaced", "sha256sums_replaced"}:
        verify_image = PUBLISHER._verify_usb_image

        def verify_then_replace(*args):
            digest = verify_image(*args)
            if scenario == "sidecar_replaced":
                image.with_suffix(".img.sha256").write_text(
                    "0" * 64 + f"  {image.name}\n"
                )
            else:
                if scenario == "metadata_replaced":
                    image.with_suffix(".img.json").write_text(
                        '{"sha256":"' + "0" * 64 + '"}'
                    )
                else:
                    sums.write_text(f"{'0' * 64}  {iso.name}\n")
            return digest

        monkeypatch.setattr(PUBLISHER, "_verify_usb_image", verify_then_replace)
    monkeypatch.setattr(
        release_manifest, "verify_manifest", lambda _path: manifest_bytes
    )

    def load_receipts(_path):
        assert (
            hashlib.sha256(qemu_log.read_bytes()).hexdigest() == receipt["log_sha256"]
        )
        if scenario == "log_replaced":
            qemu_log.write_text(f"[qemu-verify] usb_image_sha256={image_sha}\n")
        return [receipt]

    monkeypatch.setattr(ci_evidence, "load_receipts", load_receipts)
    monkeypatch.setenv("PUBLISH_RELEASE", "true")
    monkeypatch.setenv("SKIP_ISO", "false")
    monkeypatch.setenv("SKIP_QEMU", "false")
    monkeypatch.setenv("BEAMO_WIPE_VERSION", version)
    monkeypatch.setenv("BUILD_ID", build_id)
    if scenario not in {"matching", "all_sidecars_matching"}:
        with pytest.raises(
            PUBLISHER.PublishError,
            match="QEMU-tested USB image|execution log|verified manifest|checksum sidecar|USB image metadata|signature changed",
        ):
            PUBLISHER.publish()
        if scenario == "image_replaced":
            assert not Path(f"{manifest}.sig").exists()
            image.write_bytes(b"tested USB image")
            image_sidecar.write_text(f"{tested_sha}  {image.name}\n")
            metadata = json.loads(image.with_suffix(".img.json").read_text())
            metadata["sha256"] = tested_sha
            metadata["size"] = image.stat().st_size
            image.with_suffix(".img.json").write_text(json.dumps(metadata))
            assert (
                PUBLISHER.publish() == f"gs://{PUBLISHER.BUCKET}/releases/{build_id}/"
            )
    else:
        assert PUBLISHER.publish() == f"gs://{PUBLISHER.BUCKET}/releases/{build_id}/"
