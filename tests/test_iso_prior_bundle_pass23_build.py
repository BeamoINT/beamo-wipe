"""A rebuild must preserve unrelated files at its output names."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ISO = "beamo-wipe-0.2.10-amd64.iso"
MANIFEST = "beamo-wipe-0.2.10-amd64.manifest.json"


def _preflight(tmp_path: Path, setup):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    source = (ROOT / "scripts/build-iso.sh").read_text()
    # Exercise the real shell preflight without Docker or a generated image.
    (scripts / "build-iso.sh").write_text(source.split("\nif ! docker info", 1)[0] + "\n")
    package = project / "src/beamo_wipe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.10"\n')
    out = project / "dist"
    out.mkdir()
    setup(out)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("docker", "sha256sum"):
        command = fake_bin / name
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
    result = subprocess.run(
        ["sh", str(scripts / "build-iso.sh")],
        cwd=project,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    return out, result


def _complete_bundle(out: Path):
    iso_blob = b"owned prior ISO fixture"
    (out / ISO).write_bytes(iso_blob)
    iso_sha = hashlib.sha256(iso_blob).hexdigest()
    fields = {
        "schema_version": 2,
        "beamo_wipe_version": "0.2.10",
        "artifact": {
            "iso_name": ISO,
            "iso_path": ISO,
            "iso_size_bytes": len(iso_blob),
            "iso_sha256": iso_sha,
            "iso_sha256_sidecar": f"{ISO}.sha256",
        },
    }
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    fields["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    manifest_blob = (json.dumps(fields, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    (out / MANIFEST).write_bytes(manifest_blob)
    manifest_sha = hashlib.sha256(manifest_blob).hexdigest()
    (out / f"{ISO}.sha256").write_text(f"{iso_sha}  {ISO}\n")
    (out / f"{MANIFEST}.sha256").write_text(f"{manifest_sha}  {MANIFEST}\n")
    (out / "SHA256SUMS").write_text(
        f"{iso_sha}  {ISO}\n{manifest_sha}  {MANIFEST}\n"
    )


def _previous_version_bundle(out: Path, version: str = "0.1.0"):
    iso = f"beamo-wipe-{version}-amd64.iso"
    manifest = f"beamo-wipe-{version}-amd64.manifest.json"
    iso_blob = b"previous ISO fixture"
    fields = {
        "beamo_wipe_version": version,
        "artifact": {
            "iso_name": iso,
            "iso_sha256": hashlib.sha256(iso_blob).hexdigest(),
            "iso_size_bytes": len(iso_blob),
        },
    }
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    fields["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    manifest_blob = json.dumps(fields).encode() + b"\n"
    (out / iso).write_bytes(iso_blob)
    (out / manifest).write_bytes(manifest_blob)
    iso_sha = hashlib.sha256(iso_blob).hexdigest()
    manifest_sha = hashlib.sha256(manifest_blob).hexdigest()
    (out / f"{iso}.sha256").write_text(f"{iso_sha}  {iso}\n")
    (out / f"{manifest}.sha256").write_text(f"{manifest_sha}  {manifest}\n")
    (out / "SHA256SUMS").write_text(
        f"{iso_sha}  {iso}\n{manifest_sha}  {manifest}\n"
    )


def test_iso_preflight_refuses_unowned_regular_output(tmp_path):
    out, result = _preflight(tmp_path, lambda out: (out / ISO).write_text("user bytes"))
    assert result.returncode != 0
    assert "Unverified prior ISO bundle" in result.stderr
    assert (out / ISO).read_text() == "user bytes"


def test_iso_preflight_accepts_verified_complete_prior_bundle(tmp_path):
    _, result = _preflight(tmp_path, _complete_bundle)
    assert result.returncode == 0, result.stderr


def test_iso_preflight_accepts_valid_checksum_list_from_previous_version(tmp_path):
    _, result = _preflight(tmp_path, _previous_version_bundle)
    assert result.returncode == 0, result.stderr


def test_iso_preflight_refuses_corrupt_previous_version_checksum_list(tmp_path):
    def corrupt(out):
        _previous_version_bundle(out)
        (out / "beamo-wipe-0.1.0-amd64.iso").write_bytes(b"changed prior ISO!!")

    _, result = _preflight(tmp_path, corrupt)
    assert result.returncode != 0
    assert "Unverified prior ISO bundle" in result.stderr


def test_iso_preflight_refuses_checksum_list_from_newer_version(tmp_path):
    _, result = _preflight(tmp_path, lambda out: _previous_version_bundle(out, "0.3.0"))
    assert result.returncode != 0
    assert "Unverified prior ISO bundle" in result.stderr


def test_iso_preflight_refuses_old_manifest_with_invalid_internal_digest(tmp_path):
    def corrupt(out):
        _previous_version_bundle(out)
        manifest = "beamo-wipe-0.1.0-amd64.manifest.json"
        fields = json.loads((out / manifest).read_text())
        fields["_manifest_sha256"] = "0" * 64
        raw = json.dumps(fields).encode() + b"\n"
        (out / manifest).write_bytes(raw)
        manifest_sha = hashlib.sha256(raw).hexdigest()
        (out / f"{manifest}.sha256").write_text(f"{manifest_sha}  {manifest}\n")
        sums = (out / "SHA256SUMS").read_text().splitlines()
        (out / "SHA256SUMS").write_text(f"{sums[0]}\n{manifest_sha}  {manifest}\n")

    _, result = _preflight(tmp_path, corrupt)
    assert result.returncode != 0
    assert "Unverified prior ISO bundle" in result.stderr


def test_iso_backup_accepts_verified_previous_version_sums(tmp_path):
    out = tmp_path / "dist"
    out.mkdir()
    _previous_version_bundle(out)
    backup = out / ".bundle-backup.fixture"
    backup.mkdir()
    (out / "SHA256SUMS").rename(backup / "SHA256SUMS")
    source = (ROOT / "scripts/build-iso.sh").read_text()
    helper = "verify_prior_bundle() {" + source.split("verify_prior_bundle() {", 1)[1].split(
        "\ncleanup() {", 1
    )[0]
    script = "#!/bin/sh\nset -eu\nVERSION=0.2.10\n" + helper + '\nverify_prior_bundle "$1" "$2"\n'
    result = subprocess.run(
        ["sh", "-c", script, "verify", str(backup), str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (backup / "SHA256SUMS").is_file()


def test_iso_preflight_rejects_corrupt_complete_bundle(tmp_path):
    def corrupt(out):
        _complete_bundle(out)
        (out / ISO).write_bytes(b"Z" * len(b"owned prior ISO fixture"))

    out, result = _preflight(tmp_path, corrupt)
    assert result.returncode != 0
    assert "Unverified prior ISO bundle" in result.stderr
    assert (out / ISO).read_bytes() == b"Z" * len(b"owned prior ISO fixture")


def test_iso_transaction_preserves_prior_name_swapped_to_foreign_regular_file(tmp_path):
    out = tmp_path / "dist"
    out.mkdir()
    _complete_bundle(out)
    source = (ROOT / "scripts/build-iso.sh").read_text()
    helpers = 'DOCKER_INFO="$(mktemp ' + source.split('DOCKER_INFO="$(mktemp ', 1)[1].split(
        "\ntrap cleanup EXIT", 1
    )[0]
    publication = 'BACKUP_DIR="$(mktemp -d "$OUT_DIR/.bundle-backup.XXXXXX")"' + source.split(
        'BACKUP_DIR="$(mktemp -d "$OUT_DIR/.bundle-backup.XXXXXX")"', 1
    )[1].split('\necho "Wrote ', 1)[0]
    script = tmp_path / "transaction.sh"
    script.write_text(
        f"#!/bin/sh\nset -eu\nOUT_DIR='{out}'\nVERSION=0.2.10\nISO_NAME={ISO}\n"
        + helpers
        + "\ntrap cleanup EXIT\n"
        + 'BUILD_OUT="$(mktemp -d "$OUT_DIR/.build-output.XXXXXX")"\n'
        + 'printf new > "$BUILD_OUT/$ISO_NAME"\n'
        + 'require_prior_bundle_paths\nverify_prior_bundle "$OUT_DIR"\n'
        + 'printf "foreign same-size!" > "$OUT_DIR/$ISO_NAME"\n'
        + publication
        + "\nexit 0\n"
    )
    result = subprocess.run(["sh", str(script)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Unverified prior ISO bundle" in result.stderr
    assert (out / ISO).read_text() == "foreign same-size!"
    assert not list(out.glob(".bundle-backup.*"))
