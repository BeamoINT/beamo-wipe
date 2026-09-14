# SPDX-License-Identifier: GPL-3.0-or-later
"""Publisher-authenticated manifest signatures: valid, altered, wrong-key,
missing, rotated/revoked, rollback — plus registry and trust-boundary pins."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "cryptography",
    reason="release signing needs the cryptography package (see install_test_deps)",
)

from beamo_wipe import release_signing as rs

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_wipe_release_publisher",
    ROOT / "scripts" / "publish_release_gcs.py",
)
assert SPEC and SPEC.loader
PUBLISHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PUBLISHER
SPEC.loader.exec_module(PUBLISHER)


def _manifest_bytes(version: str = "0.2.7") -> bytes:
    body = {
        "beamo_wipe_version": version,
        "artifact": {"iso_sha256": "8" * 64},
        "build": {"release_build_id": "local"},
        "source": {"commit": "a" * 40},
    }
    return json.dumps(body, sort_keys=True).encode("utf-8")


def _registry(*entries: tuple, statuses: dict | None = None) -> dict:
    keys = {}
    for private_raw, public_raw in entries:
        entry_id = rs.key_id(public_raw)
        keys[entry_id] = {
            "fingerprint": rs.fingerprint(public_raw),
            "public_key": base64.b64encode(public_raw).decode("ascii"),
            "status": (statuses or {}).get(entry_id, "active"),
        }
    return rs.load_key_registry({"schema": rs.KEYS_SCHEMA, "keys": keys})


def test_valid_signature_verifies():
    private_raw, public_raw = rs.generate_keypair()
    manifest = _manifest_bytes()
    sidecar = rs.sign_manifest_bytes(manifest, private_raw, signed_at="2026-09-11T00:00:00Z")
    assert sidecar["key_id"] == rs.key_id(public_raw)
    assert sidecar["manifest_sha256"] == hashlib.sha256(manifest).hexdigest()
    result = rs.verify_with_registry(manifest, sidecar, _registry((private_raw, public_raw)))
    assert result["key_id"] == sidecar["key_id"]
    accepted = rs.verify_release_acceptance(
        manifest, sidecar, _registry((private_raw, public_raw)), min_version="0.2.7"
    )
    assert accepted["beamo_wipe_version"] == "0.2.7"


def test_altered_manifest_bytes_fail():
    private_raw, public_raw = rs.generate_keypair()
    manifest = _manifest_bytes()
    sidecar = rs.sign_manifest_bytes(manifest, private_raw, signed_at="2026-09-11T00:00:00Z")
    registry = _registry((private_raw, public_raw))
    with pytest.raises(RuntimeError, match="different manifest bytes"):
        rs.verify_with_registry(manifest + b" ", sidecar, registry)
    tampered = bytearray(manifest)
    tampered[-2] ^= 0x01
    with pytest.raises(RuntimeError, match="different manifest bytes"):
        rs.verify_with_registry(bytes(tampered), sidecar, registry)


def test_altered_sidecar_blob_fails():
    private_raw, public_raw = rs.generate_keypair()
    manifest = _manifest_bytes()
    sidecar = dict(
        rs.sign_manifest_bytes(manifest, private_raw, signed_at="2026-09-11T00:00:00Z")
    )
    blob = bytearray(base64.b64decode(sidecar["signature"]))
    blob[0] ^= 0x01
    sidecar["signature"] = base64.b64encode(bytes(blob)).decode("ascii")
    with pytest.raises(RuntimeError, match="invalid"):
        rs.verify_with_registry(manifest, sidecar, _registry((private_raw, public_raw)))


def test_wrong_key_fails():
    first = rs.generate_keypair()
    second = rs.generate_keypair()
    manifest = _manifest_bytes()
    sidecar = rs.sign_manifest_bytes(manifest, first[0], signed_at="2026-09-11T00:00:00Z")
    registry = _registry(second)
    with pytest.raises(RuntimeError, match="not a known publisher key|different key"):
        rs.verify_with_registry(manifest, sidecar, registry)


def test_missing_sidecar_key_or_registry_entry_fails():
    private_raw, public_raw = rs.generate_keypair()
    manifest = _manifest_bytes()
    sidecar = rs.sign_manifest_bytes(manifest, private_raw, signed_at="2026-09-11T00:00:00Z")
    with pytest.raises(RuntimeError, match="not a known publisher key"):
        rs.verify_with_registry(manifest, sidecar, _registry(rs.generate_keypair()))
    with pytest.raises(RuntimeError, match="not a known publisher key"):
        rs.verify_with_registry(manifest, {"schema": rs.SIGNATURE_SCHEMA}, _registry((private_raw, public_raw)))
    with pytest.raises(RuntimeError, match="lists no keys"):
        rs.load_key_registry({"schema": rs.KEYS_SCHEMA, "keys": {}})
    other = rs.generate_keypair()
    with pytest.raises(RuntimeError, match="not a known publisher key"):
        rs.verify_with_registry(manifest, sidecar, _registry(other))


def test_rotated_key_old_retired_new_accepted():
    old = rs.generate_keypair()
    new = rs.generate_keypair()
    manifest = _manifest_bytes()
    old_sidecar = rs.sign_manifest_bytes(manifest, old[0], signed_at="2026-09-11T00:00:00Z")
    new_sidecar = rs.sign_manifest_bytes(manifest, new[0], signed_at="2026-09-11T00:00:01Z")
    registry = _registry(old, new, statuses={rs.key_id(old[1]): "retired"})
    with pytest.raises(RuntimeError, match="not active"):
        rs.verify_with_registry(manifest, old_sidecar, registry)
    assert rs.verify_with_registry(manifest, new_sidecar, registry)["key_id"] == rs.key_id(new[1])


def test_revoked_key_fails_despite_valid_crypto():
    private_raw, public_raw = rs.generate_keypair()
    manifest = _manifest_bytes()
    sidecar = rs.sign_manifest_bytes(manifest, private_raw, signed_at="2026-09-11T00:00:00Z")
    registry = _registry((private_raw, public_raw), statuses={rs.key_id(public_raw): "revoked"})
    with pytest.raises(RuntimeError, match="revoked"):
        rs.verify_with_registry(manifest, sidecar, registry)


def test_rollback_old_version_rejected_new_accepted():
    private_raw, public_raw = rs.generate_keypair()
    registry = _registry((private_raw, public_raw))
    old_bytes = _manifest_bytes("0.2.0")
    old_sidecar = rs.sign_manifest_bytes(old_bytes, private_raw, signed_at="2026-09-11T00:00:00Z")
    with pytest.raises(RuntimeError, match="acceptance floor"):
        rs.verify_release_acceptance(old_bytes, old_sidecar, registry, min_version="0.2.7")
    assert (
        rs.verify_release_acceptance(old_bytes, old_sidecar, registry, min_version="0.2.0")[
            "beamo_wipe_version"
        ]
        == "0.2.0"
    )


def test_registry_rejects_mismatched_fingerprint_and_bad_status():
    private_raw, public_raw = rs.generate_keypair()
    entry_id = rs.key_id(public_raw)
    good = {
        "fingerprint": rs.fingerprint(public_raw),
        "public_key": base64.b64encode(public_raw).decode("ascii"),
        "status": "active",
    }
    bad_fingerprint = dict(good, fingerprint="0" * 64)
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        rs.load_key_registry({"schema": rs.KEYS_SCHEMA, "keys": {entry_id: bad_fingerprint}})
    bad_status = dict(good, status="super-active")
    with pytest.raises(RuntimeError, match="bad status"):
        rs.load_key_registry({"schema": rs.KEYS_SCHEMA, "keys": {entry_id: bad_status}})


def test_committed_registry_has_no_private_material():
    registry_path = ROOT / "packaging" / "release-keys" / "keys.json"
    assert registry_path.is_file()
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    assert data.get("schema") == rs.KEYS_SCHEMA
    assert isinstance(data.get("keys"), dict)
    blob = registry_path.read_text(encoding="utf-8")
    for needle in ("PRIVATE", "SECRET_KEY", "password=", "api_key=", "sk-live-"):
        assert needle not in blob


def test_pull_request_build_config_is_secret_free():
    text = (ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
    for needle in ("availableSecrets", "secretEnv", "SIGNING_KEY", "SECRET_MANAGER"):
        assert needle not in text, f"cloudbuild.yaml must stay secret-free: {needle}"


def test_publisher_requires_signing_material_and_uploads_sidecar(monkeypatch, tmp_path):
    monkeypatch.delenv("BEAMO_WIPE_SIGNING_KEY_FILE", raising=False)
    with pytest.raises(PUBLISHER.PublishError, match="without signing material"):
        PUBLISHER._read_signing_key()
    names = {p.name for p in PUBLISHER._release_inputs("0.2.6")}
    assert "beamo-wipe-0.2.6-amd64.manifest.json.sig" in names


def test_signing_key_file_permissions_fail_closed(tmp_path, monkeypatch):
    key = tmp_path / "rel.key"
    key.write_bytes(b"0" * 32)
    key.chmod(0o644)
    monkeypatch.setenv("BEAMO_WIPE_SIGNING_KEY_FILE", str(key))
    with pytest.raises(PUBLISHER.PublishError, match="0600 or 0400"):
        PUBLISHER._read_signing_key()
    key.chmod(0o600)
    assert PUBLISHER._read_signing_key() == b"0" * 32


def test_release_signing_is_not_secure_boot():
    text = (ROOT / "docs" / "release-verification.md").read_text(encoding="utf-8")
    assert "not Secure Boot" in text
    assert "Threat model" in text


def test_cli_keygen_sign_verify_round_trip(tmp_path):
    from beamo_wipe.release_signing import main

    private_path = tmp_path / "rel.priv"
    public_path = tmp_path / "rel.pub"
    assert main(["keygen", "--private-out", str(private_path), "--public-out", str(public_path)]) == 0
    assert len(private_path.read_bytes()) == 32 and len(public_path.read_bytes()) == 32
    import stat as _stat

    assert _stat.S_IMODE(private_path.stat().st_mode) == 0o600
    manifest = tmp_path / "m.json"
    manifest.write_bytes(_manifest_bytes())
    sidecar_path = tmp_path / "m.json.sig"
    assert (
        main(
            [
                "sign",
                "--manifest", str(manifest),
                "--key-file", str(private_path),
                "--signed-at", "2026-09-11T00:00:00Z",
                "--out", str(sidecar_path),
            ]
        )
        == 0
    )
    registry_path = tmp_path / "keys.json"
    public_raw = public_path.read_bytes()
    registry_path.write_text(
        json.dumps(
            {
                "schema": rs.KEYS_SCHEMA,
                "keys": {
                    rs.key_id(public_raw): {
                        "fingerprint": rs.fingerprint(public_raw),
                        "public_key": base64.b64encode(public_raw).decode("ascii"),
                        "status": "active",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "verify",
                "--manifest", str(manifest),
                "--signature", str(sidecar_path),
                "--registry", str(registry_path),
                "--min-version", "0.2.7",
            ]
        )
        == 0
    )
