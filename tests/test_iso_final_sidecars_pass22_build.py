"""The ISO builder must not report success with swapped provenance sidecars."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_iso_finalization_rejects_linked_manifest_checksum(tmp_path: Path) -> None:
    project = tmp_path / "project"
    dist = project / "dist"
    dist.mkdir(parents=True)
    stage = dist / ".build-output.test"
    stage.mkdir()
    backup = dist / ".bundle-backup.test"
    backup.mkdir()
    version = "0.2.9"
    iso_name = f"beamo-wipe-{version}-amd64.iso"
    manifest_name = f"beamo-wipe-{version}-amd64.manifest.json"
    staged_iso = stage / iso_name
    staged_iso.write_bytes(b"iso fixture")
    os.link(staged_iso, dist / iso_name)
    manifest = dist / manifest_name
    manifest.write_bytes(b"manifest fixture")
    iso_sha = hashlib.sha256(staged_iso.read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    (dist / f"{iso_name}.sha256").write_text(f"{iso_sha}  {iso_name}\n")
    (dist / "SHA256SUMS").write_text(
        f"{iso_sha}  {iso_name}\n{manifest_sha}  {manifest_name}\n"
    )
    outside = tmp_path / "outside-checksum"
    outside.write_text(f"{manifest_sha}  {manifest_name}\n")
    (dist / f"{manifest_name}.sha256").symlink_to(outside)

    source = (ROOT / "scripts/build-iso.sh").read_text()
    finalizer = 'for _f in "dist/' + source.rsplit('for _f in "dist/', 1)[1]
    finalizer = finalizer.split('\nls -lh "dist/', 1)[0]
    script = project / "finalize.sh"
    script.write_text(
        "#!/bin/sh\nset -eu\n"
        f"OUT_DIR={dist}\n"
        f"BUILD_OUT={stage}\n"
        f"BACKUP_DIR={backup}\n"
        f"VERSION={version}\n"
        f"ISO_NAME={iso_name}\n"
        f"BUNDLE_FILES='{iso_name} {manifest_name} {manifest_name}.sha256 {iso_name}.sha256 SHA256SUMS'\n"
        + source[
            source.index("same_regular_inode() {") : source.index(
                "\nrequire_prior_bundle_paths() {"
            )
        ]
        + "\n"
        + finalizer
    )
    result = subprocess.run(
        ["sh", str(script)], cwd=project, capture_output=True, text=True, timeout=10
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert (dist / f"{manifest_name}.sha256").is_symlink()
    assert outside.is_file()
