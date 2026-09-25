"""A release must publish the same QEMU evidence that passed the gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_wipe_publisher_pass10", ROOT / "scripts" / "publish_release_gcs.py"
)
assert SPEC and SPEC.loader
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


@pytest.mark.parametrize("mutation_stage", ["before_preflight", "after_preflight"])
def test_publisher_rejects_qemu_evidence_changed_after_gate(tmp_path, monkeypatch, mutation_stage):
    from beamo_wipe import ci_evidence, release_manifest

    version = "0.2.9"
    build_id = "12345678-1234-1234-1234-123456789abc"
    commit = "a" * 40
    dist = tmp_path / "dist"
    dist.mkdir()
    evidence = dist / "evidence"
    evidence.mkdir()
    qemu_evidence = tmp_path / "qemu-evidence"
    qemu_evidence.mkdir()
    summary = qemu_evidence / "summary.txt"
    original = b"everyday=pass\n"
    summary.write_bytes(original)
    expected_tree = _sha(
        json.dumps(
            {summary.name: _sha(original)}, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    if mutation_stage == "before_preflight":
        summary.write_bytes(b"everyday=fail\n")

    iso = dist / f"beamo-wipe-{version}-amd64.iso"
    image = dist / f"beamo-wipe-{version}-amd64.img"
    iso.write_bytes(b"fixture ISO")
    image.write_bytes(b"fixture USB")
    qemu_log = evidence / "qemu.log"
    qemu_log.write_text(f"[qemu-verify] usb_image_sha256={_sha(image.read_bytes())}\n")
    receipt = {
        "gate": "qemu",
        "status": "pass",
        "log_sha256": _sha(qemu_log.read_bytes()),
        "environment": {"qemu_evidence_sha256": expected_tree},
    }
    manifest = dist / f"beamo-wipe-{version}-amd64.manifest.json"
    manifest_bytes = json.dumps(
        {
            "source": {"commit": commit},
            "build": {"release_build_id": build_id},
            "artifact": {"iso_sha256": _sha(iso.read_bytes())},
            "test_evidence": {"gates": {"qemu": receipt}},
        }
    ).encode()
    manifest.write_bytes(manifest_bytes)
    uploads = {}

    def sign_manifest(_dist, _version, *, manifest_bytes):
        signature = Path(f"{manifest}.sig")
        signature.write_bytes(b"fixture signature")
        if mutation_stage == "after_preflight":
            summary.write_bytes(b"everyday=fail\n")
        return signature, _sha(signature.read_bytes())

    def upload_file(path, object_name):
        uploads[object_name] = _sha(path.read_bytes())

    def upload_stream(object_name, stream, _size):
        uploads[object_name] = _sha(stream.read())

    monkeypatch.setattr(PUBLISHER, "ROOT", tmp_path)
    monkeypatch.setattr(PUBLISHER, "_release_inputs", lambda _version: [iso, image, qemu_log, summary])
    monkeypatch.setattr(PUBLISHER, "_verify_source", lambda _version: commit)
    monkeypatch.setattr(PUBLISHER, "_sign_release_manifest", sign_manifest)
    monkeypatch.setattr(PUBLISHER, "_verify_sha256sums", lambda *_args: None)
    monkeypatch.setattr(PUBLISHER, "_verify_usb_image", lambda *_args: (_sha(image.read_bytes()), "b" * 64))
    monkeypatch.setattr(PUBLISHER, "_upload_file", upload_file)
    monkeypatch.setattr(PUBLISHER, "_upload_stream", upload_stream)
    monkeypatch.setattr(PUBLISHER, "_remote_sha256", lambda object_name: uploads[object_name])
    monkeypatch.setattr(release_manifest, "verify_manifest", lambda _path: manifest_bytes)
    monkeypatch.setattr(ci_evidence, "load_receipts", lambda _path: [receipt])
    monkeypatch.setenv("PUBLISH_RELEASE", "true")
    monkeypatch.setenv("SKIP_ISO", "false")
    monkeypatch.setenv("SKIP_QEMU", "false")
    monkeypatch.setenv("BEAMO_WIPE_VERSION", version)
    monkeypatch.setenv("BUILD_ID", build_id)

    with pytest.raises(PUBLISHER.PublishError, match="QEMU evidence changed"):
        PUBLISHER.publish()
    assert Path(f"{manifest}.sig").exists() is (mutation_stage == "after_preflight")


def test_qemu_receipt_binds_copied_evidence_bytes(tmp_path, monkeypatch):
    from beamo_wipe import ci_evidence

    qemu_evidence = tmp_path / "qemu-evidence"
    qemu_evidence.mkdir()
    summary = qemu_evidence / "summary.txt"
    summary.write_bytes(b"everyday=pass\n")
    monkeypatch.setattr(ci_evidence.subprocess, "check_output", lambda *_args, **_kw: "a" * 40)
    receipt = ci_evidence.run_gate(
        "qemu",
        [sys.executable, "-c", "print('fixture QEMU gate')"],
        root=tmp_path,
        evidence_dir=tmp_path / "dist" / "evidence",
        build_id="local",
    )
    expected_tree = _sha(
        json.dumps(
            {summary.name: _sha(summary.read_bytes())}, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    assert receipt["environment"]["qemu_evidence_sha256"] == expected_tree
