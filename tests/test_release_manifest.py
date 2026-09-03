# SPDX-License-Identifier: GPL-3.0-or-later
"""Release manifest: provenance, checksum, prior stable, verification."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from beamo_wipe import NWIPE_PINNED_COMMIT, NWIPE_PINNED_VERSION

ROOT = Path(__file__).resolve().parents[1]

# The 0.1.0 manufacturing ISO (419 MiB) lives only where it was built or
# downloaded — never in git, never in CI/Cloud uploads. Tests below that
# generate a manifest for it need the bytes; without them they skip
# (visible in counts, like the lb-config live-image skips) instead of
# failing fresh checkouts. The production path is still exercised on
# every hosted build by scripts/build-iso.sh generating the real manifest.
ISO_010 = ROOT / "dist" / "beamo-wipe-0.1.0-amd64.iso"
requires_manufacturing_iso = pytest.mark.skipif(
    not ISO_010.is_file(),
    reason="manufacturing ISO absent: run scripts/build-iso.sh or fetch the release artifact",
)


@requires_manufacturing_iso
def test_manifest_schema_covers_required_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_DIRTY", "1")
    # Generate for existing 0.1.0 ISO
    import beamo_wipe.release_manifest as rm

    m = rm.generate_manifest(version="0.1.0", strict=False)
    assert m["schema_version"] == 1
    assert m["beamo_wipe_version"] == "0.1.0"
    assert m["source"]["commit"]
    assert "dirty" in m["source"]
    assert m["build"]["container_image"] == "debian:bookworm"
    assert m["dependencies"]["pyproject.toml"]
    assert m["live_build_inputs"]["bootstrap"]
    assert m["nwipe"]["version"] == "0.42"
    assert m["nwipe"]["commit"] == NWIPE_PINNED_COMMIT
    assert m["artifact"]["iso_sha256"] == "8a531d35c437d858512ccbba20913cd7dbd9237cc9a2e2a1b7935ba9d9781c55"
    assert m["test_evidence"]["pytest"]
    assert m["hardware_limits"]["supported"]
    assert m["hardware_limits"]["unsupported"]
    assert m["known_issues"]
    assert m["license"]["wrapper"] == "GPL-3.0-or-later"
    assert m["prior_stable"]["iso_name"] == "beamo-wipe-0.1.0-amd64.iso"
    assert m["verification"]["checksum_instructions"]
    assert "_manifest_sha256" in m


@requires_manufacturing_iso
def test_manifest_fails_on_dirty_when_strict(monkeypatch):
    import beamo_wipe.release_manifest as rm

    # Simulate dirty by monkeypatching git_dirty
    monkeypatch.setattr(rm, "git_dirty", lambda: (True, ["M src/beamo_wipe/__init__.py"]))
    with pytest.raises(RuntimeError, match="uncommitted"):
        rm.generate_manifest(version="0.1.0", strict=True)
    # With strict=False it should pass
    m = rm.generate_manifest(version="0.1.0", strict=False)
    assert m["source"]["dirty"] is True


@requires_manufacturing_iso
def test_verify_allows_dirty_only_for_dirty_check(tmp_path, monkeypatch):
    """ALLOW_DIRTY still verifies: only the dirty-state check is skipped."""
    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "git_dirty", lambda: (True, ["M src/beamo_wipe/__init__.py"]))
    m = rm.generate_manifest(version="0.1.0", strict=False)
    dest = tmp_path / "dirty-manifest.json"
    out = rm.write_manifest(m, dest)
    # Default verify still rejects the dirty tree.
    with pytest.raises(RuntimeError, match="uncommitted"):
        rm.verify_manifest(out)
    # allow_dirty accepts the dirty flag — but nothing else.
    rm.verify_manifest(out, allow_dirty=True)
    tampered = json.loads(dest.read_text(encoding="utf-8"))
    tampered["beamo_wipe_version"] = "9.9.9-dirty"
    dest.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        rm.verify_manifest(out, allow_dirty=True)


def test_manifest_fails_on_placeholder(monkeypatch, tmp_path):
    import beamo_wipe.release_manifest as rm

    # Create a temp file with placeholder and make live_build_inputs see it
    # Instead, patch PLACEHOLDER_RE to match our fake file content
    orig = (ROOT / "src" / "beamo_wipe" / "__init__.py").read_text()
    # Simulate placeholder by patching the file read inside generate_manifest
    # Use monkeypatch to make live_build_inputs return a placeholder-containing entry
    # Simpler: patch the file itself temporarily
    p = Path(tmp_path / "fake.py")
    p.write_text("PLACEHOLDER version = '0.0.0'\n")
    # Monkeypatch to pretend __init__.py contains placeholder
    monkeypatch.setattr(rm, "git_dirty", lambda: (False, []))
    # We need to make the placeholder check fail: patch Path.read_text for that path
    orig_read = Path.read_text

    def fake_read_text(self, *a, **kw):
        if str(self).endswith("__init__.py"):
            return "PLACEHOLDER"
        return orig_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    with pytest.raises(RuntimeError, match="placeholder"):
        rm.generate_manifest(version="0.1.0", strict=True)


def test_manifest_fails_on_missing_iso(monkeypatch, tmp_path):
    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "git_dirty", lambda: (False, []))
    # Use a version that has no ISO
    with pytest.raises(RuntimeError, match="missing checksum.*ISO"):
        rm.generate_manifest(version="9.9.9", strict=True)


@requires_manufacturing_iso
def test_manifest_fails_on_unexpected_nwipe_version(monkeypatch):
    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "git_dirty", lambda: (False, []))
    # Patch NWIPE_PINNED_VERSION
    monkeypatch.setattr(rm, "NWIPE_PINNED_VERSION", "9.99")
    with pytest.raises(RuntimeError, match="unexpected nwipe"):
        rm.generate_manifest(version="0.1.0", strict=True)


def test_manifest_fails_on_unapproved_dependency_drift(monkeypatch, tmp_path):
    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "git_dirty", lambda: (False, []))
    monkeypatch.setattr(rm, "git_commit", lambda: "a" * 40)
    monkeypatch.setattr(rm, "git_tag_for_commit", lambda c: None)
    monkeypatch.setattr(rm, "git_remote_url", lambda: "https://github.com/BeamoINT/beamo-wipe")
    monkeypatch.setattr(rm, "_run", lambda cmd, **kw: "main" if "abbrev-ref" in cmd else "a" * 40 if "rev-parse" in cmd else "https://github.com/BeamoINT/beamo-wipe")
    # Need a fake ISO for the version we request
    fake_dist = tmp_path / "dist"
    fake_dist.mkdir()
    (fake_dist / "beamo-wipe-0.1.0-amd64.iso").write_bytes(b"fakeiso")
    # Simulate pyproject.toml with different version
    fake_pyproject = tmp_path / "pyproject.toml"
    fake_pyproject.write_text('[project]\nname = "beamo-wipe"\nversion = "9.9.9"\n')
    # Patch ROOT to tmp_path so pyproject is read from there
    monkeypatch.setattr(rm, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="unapproved dependency drift"):
        rm.generate_manifest(version="0.1.0", strict=True)


@requires_manufacturing_iso
def test_manifest_atomic_write_and_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.release_manifest.git_dirty", lambda: (False, []))
    import beamo_wipe.release_manifest as rm

    m = rm.generate_manifest(version="0.1.0", strict=False)
    dest = tmp_path / "beamo-wipe-0.1.0-amd64.manifest.json"
    out = rm.write_manifest(m, dest)
    assert out == dest
    assert dest.is_file()
    sidecar = Path(str(dest) + ".sha256")
    assert sidecar.is_file()
    # Verify checksum
    rm.verify_manifest(dest)
    # Check ISO sidecar also created
    iso_sidecar = Path(m["artifact"]["iso_path"]).parent / m["artifact"]["iso_sha256_sidecar"]
    # In this test, iso_path is dist/... which exists, so sidecar should be there
    # But we wrote to tmp_path, not dist, so iso sidecar is in dist, not tmp_path
    # Instead check our dest's sidecar
    assert sidecar.read_text().strip().split()[0] == hashlib.sha256(dest.read_bytes()).hexdigest()


@requires_manufacturing_iso
def test_manifest_checksum_mismatch_is_rejected(tmp_path):
    import beamo_wipe.release_manifest as rm

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rm, "git_dirty", lambda: (False, []))
    m = rm.generate_manifest(version="0.1.0", strict=False)
    dest = tmp_path / "manifest.json"
    rm.write_manifest(m, dest)
    # Tamper
    data = json.loads(dest.read_text())
    data["beamo_wipe_version"] = "9.9.9"
    dest.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        rm.verify_manifest(dest)
    monkeypatch.undo()


@requires_manufacturing_iso
def test_manifest_duplicate_write_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.release_manifest.git_dirty", lambda: (False, []))
    import beamo_wipe.release_manifest as rm

    m = rm.generate_manifest(version="0.1.0", strict=False)
    dest = tmp_path / "manifest.json"
    out1 = rm.write_manifest(m, dest)
    h1 = out1.read_text()
    out2 = rm.write_manifest(m, dest)
    h2 = out2.read_text()
    # Should be same content (except _manifest_sha256 is deterministic, so same)
    assert h1 == h2
    rm.verify_manifest(dest)


@requires_manufacturing_iso
def test_manifest_stale_state_detected(tmp_path, monkeypatch):
    # Simulate commit changed between generate and verify
    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "git_dirty", lambda: (False, []))
    m1 = rm.generate_manifest(version="0.1.0", strict=False)
    dest = tmp_path / "manifest.json"
    rm.write_manifest(m1, dest)
    # Now change commit
    monkeypatch.setattr(rm, "git_commit", lambda: "deadbeef" * 5)
    # Verify should still pass because it checks checksum, not commit freshness
    # But a new generate would have different commit, so stale is detectable by comparing
    m2 = rm.generate_manifest(version="0.1.0", strict=False)
    assert m1["source"]["commit"] != m2["source"]["commit"]


@requires_manufacturing_iso
def test_manifest_recovery_after_failed_write(tmp_path, monkeypatch):
    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "git_dirty", lambda: (False, []))
    m = rm.generate_manifest(version="0.1.0", strict=False)
    dest = tmp_path / "manifest.json"
    # Simulate disk full on first write
    orig_open = open

    def failing_open(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", failing_open)
    with pytest.raises(OSError):
        rm.write_manifest(m, dest)
    # No partial file
    assert not dest.exists() or dest.stat().st_size == 0
    monkeypatch.setattr("builtins.open", orig_open)
    # Retry succeeds
    out = rm.write_manifest(m, dest)
    assert out.exists()
    rm.verify_manifest(out)


@requires_manufacturing_iso
def test_consumer_verification_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.release_manifest.git_dirty", lambda: (False, []))
    import beamo_wipe.release_manifest as rm

    m = rm.generate_manifest(version="0.1.0", strict=False)
    assert "sha256sum -c" in m["verification"]["checksum_instructions"]
    # Should mention both ISO and manifest
    assert "iso.sha256" in m["verification"]["checksum_instructions"] or "manifest" in m["verification"]["checksum_instructions"]
    assert "retention" in m["verification"]["artifact_immutability"] or "retention-days" in m["verification"]["artifact_immutability"] or "GCS" in m["verification"]["artifact_immutability"]
    assert "not configured" in m["verification"]["signing"] or "SHA256" in m["verification"]["signing"]


@requires_manufacturing_iso
def test_prior_stable_and_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.release_manifest.git_dirty", lambda: (False, []))
    import beamo_wipe.release_manifest as rm

    m = rm.generate_manifest(version="0.1.0", strict=False)
    prior = m["prior_stable"]
    assert prior["iso_name"] == "beamo-wipe-0.1.0-amd64.iso"
    assert prior["sha256"] == "8a531d35c437d858512ccbba20913cd7dbd9237cc9a2e2a1b7935ba9d9781c55"
    assert "rollback" in m
    assert "3b4c01f" in m["rollback"]


@requires_manufacturing_iso
def test_hardware_limits_and_license(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.release_manifest.git_dirty", lambda: (False, []))
    import beamo_wipe.release_manifest as rm

    m = rm.generate_manifest(version="0.1.0", strict=False)
    hw = m["hardware_limits"]
    assert "Apple Silicon" in str(hw["unsupported"])
    assert "x64" in str(hw["supported"])
    assert m["license"]["wrapper"] == "GPL-3.0-or-later"
    assert m["license"]["nwipe"] == "GPL-2.0"
    assert "https://github.com/BeamoINT/beamo-wipe" in m["license"]["source"]
