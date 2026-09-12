# SPDX-License-Identifier: GPL-3.0-or-later
"""Publisher-authenticated signatures for the canonical release manifest.

The signed bytes are the exact manifest file bytes, so one signature covers
the artifact hashes, build identity, evidence/receipt hashes, and version
metadata together. Signatures are detached sidecars
(``<manifest>.sig``): the manifest hash stays stable and verifiable on its
own, and the signature binds those same bytes to a publisher key.

This is release signing, not Secure Boot: it proves *who published this
file* (the Beamo release key held by the operator), not *what a machine may
boot*. It says nothing about firmware trust, image contents beyond their
hashes, or the wiped-disk result. See ``docs/release-verification.md``.

Trust boundaries (enforced by tests, not just docs):

- Private signing material lives only in the operator's custody (Secret
  Manager for the release build) and is never committed, never printed, and
  never attached to pull-request builds. ``cloudbuild.yaml`` — the file a
  pull request can rewrite — must stay secret-free.
- Verification fails closed: unknown schema, unknown or non-active key,
  digest mismatch, altered bytes, missing sidecar, or a version below the
  acceptance floor all raise.
- No production keys are created, rotated, or published by this code path.
  Key generation below is for tests and the documented operator ceremony;
  production rotation/revocation needs separate operator authorization.

Ed25519 comes from the ``cryptography`` package, imported lazily so every
other module stays standard-library-only. The hosted test worker installs
it (see ``install_test_deps``); without it this module raises a clear
error instead of silently skipping verification.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

SIGNATURE_SCHEMA = "beamo-wipe-manifest-signature/1"
KEYS_SCHEMA = "beamo-wipe-release-keys/1"

UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
VERSION_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")
KEY_STATUSES = frozenset({"active", "retired", "revoked"})

CRYPTOGRAPHY_MINIMUM = "49.0.0"


def _ed25519() -> Any:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:
        raise RuntimeError(
            "release signing needs the 'cryptography' package "
            f"(>={CRYPTOGRAPHY_MINIMUM}); refusing to continue without it"
        ) from exc
    return ed25519, InvalidSignature


def utc_now_s() -> str:
    """Current UTC time at second precision, normalized form."""
    import datetime as _dt

    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_utc(value: object) -> str:
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            raise RuntimeError("naive datetime is not valid signature time")
        value = value.astimezone(datetime.timezone.utc).replace(microsecond=0)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("+00:00"):
            text = text[: -len("+00:00")] + "Z"
        if not UTC_RE.fullmatch(text):
            raise RuntimeError(f"time is not normalized UTC: {value!r}")
        return text
    raise RuntimeError(f"time must be a datetime or string, got {type(value).__name__}")


def fingerprint(public_raw: bytes) -> str:
    """Full public-key fingerprint: hex SHA-256 of the 32 raw bytes."""
    if not isinstance(public_raw, (bytes, bytearray)) or len(public_raw) != 32:
        raise RuntimeError("public key must be 32 raw Ed25519 bytes")
    return hashlib.sha256(bytes(public_raw)).hexdigest()


def key_id(public_raw: bytes) -> str:
    """Short key id: first 16 hex chars of the fingerprint."""
    return fingerprint(public_raw)[:16]


def generate_keypair() -> tuple:
    """Generate an ephemeral Ed25519 pair. Tests and ceremony use only.

    Production keys are created by the operator ceremony in
    ``packaging/release-keys/KEYS.md`` — never by automation, never here.
    """
    ed25519, _ = _ed25519()
    private = ed25519.Ed25519PrivateKey.generate()
    private_raw = private.private_bytes_raw()
    public_raw = private.public_key().public_bytes_raw()
    return private_raw, public_raw


def _b64decode(value: object, *, what: str) -> bytes:
    if not isinstance(value, str) or not value.strip() or not B64_RE.fullmatch(value.strip()):
        raise RuntimeError(f"{what} is not valid base64")
    try:
        return base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(f"{what} is not valid base64") from exc


def sign_manifest_bytes(
    manifest_bytes: bytes,
    private_raw: bytes,
    *,
    signed_at: object = None,
) -> Dict[str, Any]:
    """Sign exact manifest file bytes with a publisher key. Fail closed."""
    if not isinstance(manifest_bytes, (bytes, bytearray)) or not manifest_bytes:
        raise RuntimeError("cannot sign empty manifest bytes")
    if not isinstance(private_raw, (bytes, bytearray)) or len(private_raw) != 32:
        raise RuntimeError("signing key must be 32 raw Ed25519 bytes")
    ed25519, _ = _ed25519()
    try:
        private = ed25519.Ed25519PrivateKey.from_private_bytes(bytes(private_raw))
    except ValueError as exc:
        raise RuntimeError("signing key is not a valid Ed25519 key") from exc
    public_raw = private.public_key().public_bytes_raw()
    signature = private.sign(bytes(manifest_bytes))
    return {
        "schema": SIGNATURE_SCHEMA,
        "key_id": key_id(public_raw),
        "key_fingerprint": fingerprint(public_raw),
        "signature": base64.b64encode(signature).decode("ascii"),
        "manifest_sha256": hashlib.sha256(bytes(manifest_bytes)).hexdigest(),
        "signed_at": normalize_utc(signed_at or utc_now_s()),
    }


def verify_signature(
    manifest_bytes: bytes, signature: Mapping[str, Any], public_raw: bytes
) -> Dict[str, Any]:
    """Verify a detached sidecar against manifest bytes and one public key."""
    if not isinstance(manifest_bytes, (bytes, bytearray)) or not manifest_bytes:
        raise RuntimeError("cannot verify empty manifest bytes")
    if not isinstance(signature, Mapping):
        raise RuntimeError("signature sidecar must be an object")
    if signature.get("schema") != SIGNATURE_SCHEMA:
        raise RuntimeError("signature sidecar has an unknown schema")
    key = _require(signature, "key_id", "signature sidecar")
    if not HEX16_RE.fullmatch(key):
        raise RuntimeError("signature sidecar has a bad key id")
    blob = _require(signature, "signature", "signature sidecar")
    digest = _require(signature, "manifest_sha256", "signature sidecar")
    if not HEX64_RE.fullmatch(digest):
        raise RuntimeError("signature sidecar has a bad manifest digest")
    normalize_utc(_require(signature, "signed_at", "signature sidecar"))
    if digest != hashlib.sha256(bytes(manifest_bytes)).hexdigest():
        raise RuntimeError("signature sidecar is for different manifest bytes")
    if not isinstance(public_raw, (bytes, bytearray)) or len(public_raw) != 32:
        raise RuntimeError("verification key must be 32 raw Ed25519 bytes")
    if key_id(bytes(public_raw)) != key:
        raise RuntimeError("signature sidecar is for a different key")
    expected_fingerprint = signature.get("key_fingerprint")
    if expected_fingerprint is not None and expected_fingerprint != fingerprint(bytes(public_raw)):
        raise RuntimeError("signature sidecar fingerprint does not match its key")
    ed25519, InvalidSignature = _ed25519()
    try:
        verifier = ed25519.Ed25519PublicKey.from_public_bytes(bytes(public_raw))
        verifier.verify(_b64decode(blob, what="signature sidecar"), bytes(manifest_bytes))
    except (ValueError, InvalidSignature) as exc:
        raise RuntimeError("manifest signature is invalid") from exc
    return {"key_id": key, "manifest_sha256": digest}


def _require(mapping: Mapping[str, Any], name: str, what: str) -> Any:
    value = mapping.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{what} is missing {name!r}")
    return value.strip()


def load_key_registry(data: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Load and validate the public-key registry. No private material ever.

    Returns ``{key_id: {fingerprint, public_key, status}}`` for well-formed
    entries. Retired and revoked keys stay listed so old signatures fail
    with a precise reason instead of an unknown-key shrug.
    """
    if not isinstance(data, Mapping):
        raise RuntimeError("key registry must be an object")
    if data.get("schema") != KEYS_SCHEMA:
        raise RuntimeError("key registry has an unknown schema")
    entries = data.get("keys")
    if not isinstance(entries, dict):
        raise RuntimeError("key registry has no keys object")
    clean: Dict[str, Dict[str, Any]] = {}
    for key_id_text, entry in entries.items():
        if not isinstance(key_id_text, str) or not HEX16_RE.fullmatch(key_id_text):
            raise RuntimeError(f"key registry has a bad key id: {key_id_text!r}")
        if not isinstance(entry, Mapping):
            raise RuntimeError(f"key registry entry {key_id_text!r} must be an object")
        status = entry.get("status")
        if status not in KEY_STATUSES:
            raise RuntimeError(f"key registry entry {key_id_text!r} has a bad status")
        raw = _b64decode(entry.get("public_key"), what=f"key registry entry {key_id_text!r}")
        if len(raw) != 32:
            raise RuntimeError(f"key registry entry {key_id_text!r} is not 32 bytes")
        if key_id(raw) != key_id_text:
            raise RuntimeError(f"key registry entry {key_id_text!r} id does not match its key")
        if fingerprint(raw) != entry.get("fingerprint"):
            raise RuntimeError(f"key registry entry {key_id_text!r} fingerprint mismatch")
        clean[key_id_text] = {
            "fingerprint": fingerprint(raw),
            "public_key": raw,
            "status": status,
        }
    if not clean:
        raise RuntimeError("key registry lists no keys")
    return clean


def verify_with_registry(
    manifest_bytes: bytes, signature: Mapping[str, Any], registry: Mapping[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Verify a sidecar against the registry. Only active keys count.

    A retired key (rotated out) or revoked key (compromised) fails even when
    the cryptography is valid — that is the point of rotation/revocation.
    """
    if not isinstance(signature, Mapping):
        raise RuntimeError("signature sidecar must be an object")
    key = signature.get("key_id")
    if not isinstance(key, str) or key not in registry:
        raise RuntimeError(f"signature key {key!r} is not a known publisher key")
    entry = registry[key]
    if entry["status"] == "revoked":
        raise RuntimeError(f"publisher key {key!r} is revoked")
    if entry["status"] != "active":
        raise RuntimeError(f"publisher key {key!r} is not active ({entry['status']})")
    return verify_signature(manifest_bytes, signature, entry["public_key"])


def _version_tuple(version: str) -> tuple:
    match = VERSION_RE.fullmatch((version or "").strip())
    if not match:
        raise RuntimeError(f"version is not X.Y.Z: {version!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def verify_release_acceptance(
    manifest_bytes: bytes,
    signature: Mapping[str, Any],
    registry: Mapping[str, Dict[str, Any]],
    *,
    min_version: str,
) -> Dict[str, Any]:
    """Signature validity plus rollback protection.

    A correctly signed older manifest still verifies cryptographically;
    acceptance additionally requires its ``beamo_wipe_version`` to be at or
    above ``min_version`` so a replayed old release cannot pass as current.
    """
    result = verify_with_registry(manifest_bytes, signature, registry)
    try:
        manifest = json.loads(bytes(manifest_bytes).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("signed manifest bytes are not JSON") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("signed manifest is not an object")
    version = manifest.get("beamo_wipe_version", "")
    if _version_tuple(version) < _version_tuple(min_version):
        raise RuntimeError(
            f"manifest version {version!r} is below the acceptance floor {min_version!r}"
        )
    return {**result, "beamo_wipe_version": version}


def _read_json_file(path: Path, *, what: str) -> Any:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise RuntimeError(f"{what} cannot be read: {path}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"{what} is not JSON: {path}") from exc


def _read_bytes_file(path: Path, *, what: str) -> bytes:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise RuntimeError(f"{what} cannot be read: {path}") from exc
    if not data:
        raise RuntimeError(f"{what} is empty: {path}")
    return data


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="release-signing")
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="generate an operator key pair (ceremony use)")
    keygen.add_argument("--private-out", required=True)
    keygen.add_argument("--public-out", required=True)

    sign = sub.add_parser("sign", help="sign exact manifest bytes")
    sign.add_argument("--manifest", required=True)
    sign.add_argument("--key-file", required=True)
    sign.add_argument("--signed-at", default="")
    sign.add_argument("--out", required=True)

    verify = sub.add_parser("verify", help="verify a manifest against a registry")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--signature", required=True)
    verify.add_argument("--registry", required=True)
    verify.add_argument("--min-version", default="")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "keygen":
        private_raw, public_raw = generate_keypair()
        private_path = Path(args.private_out)
        private_path.write_bytes(private_raw)
        try:
            private_path.chmod(0o600)
        except OSError as exc:
            raise RuntimeError("cannot protect the generated key file") from exc
        Path(args.public_out).write_bytes(public_raw)
        print(f"key id {key_id(public_raw)}; guard the private file accordingly")
        return 0
    if args.command == "sign":
        key_raw = _read_bytes_file(Path(args.key_file), what="signing key")
        if len(key_raw) != 32:
            raise RuntimeError("signing key file must hold 32 raw bytes")
        sidecar = sign_manifest_bytes(
            _read_bytes_file(Path(args.manifest), what="manifest"),
            key_raw,
            signed_at=args.signed_at or None,
        )
        Path(args.out).write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
        print(f"signed with key {sidecar['key_id']}")
        return 0
    manifest_bytes = _read_bytes_file(Path(args.manifest), what="manifest")
    sidecar = _read_json_file(Path(args.signature), what="signature sidecar")
    registry_data = _read_json_file(Path(args.registry), what="key registry")
    registry = load_key_registry(registry_data)
    if args.min_version:
        result = verify_release_acceptance(
            manifest_bytes, sidecar, registry, min_version=args.min_version
        )
        print(f"accepted version {result['beamo_wipe_version']} key {result['key_id']}")
    else:
        result = verify_with_registry(manifest_bytes, sidecar, registry)
        print(f"signature ok key {result['key_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
