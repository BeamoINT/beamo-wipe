"""A checksum generation retry must not write through a linked output."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_generator_preserves_linked_sha256sums_destination(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "generate-release-manifest.sh"
    script.write_bytes((ROOT / "scripts/generate-release-manifest.sh").read_bytes())
    dist = project / "dist"
    dist.mkdir()
    (dist / "beamo-wipe-0.2.9-amd64.iso").write_bytes(b"fixture ISO")
    outside = tmp_path / "preserve.txt"
    outside.write_text("user data must survive\n")
    (dist / "SHA256SUMS").symlink_to(outside)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = fake_bin / "python3"
    python.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = -c ]; then exec \"$BEAMO_REAL_PYTHON\" \"$@\"; fi\n"
        "printf fixture > \"$BEAMO_WIPE_MANIFEST_DEST\"\n"
        "(cd dist && sha256sum \"${BEAMO_WIPE_MANIFEST_DEST##*/}\" > \"${BEAMO_WIPE_MANIFEST_DEST##*/}.sha256\")\n"
        "(cd dist && sha256sum beamo-wipe-0.2.9-amd64.iso > beamo-wipe-0.2.9-amd64.iso.sha256)\n"
    )
    python.chmod(0o755)

    result = subprocess.run(
        ["sh", str(script)],
        cwd=project,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "ALLOW_DIRTY": "1",
            "BEAMO_WIPE_VERSION": "0.2.9",
            "BEAMO_REAL_PYTHON": sys.executable,
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert "beamo-wipe-0.2.9-amd64.manifest.json: OK" in result.stdout, result.stderr
    assert result.returncode != 0
    assert outside.read_text() == "user data must survive\n"


@pytest.mark.parametrize("sidecar_state", ["missing", "dangling-link"])
def test_manifest_generator_rebuilds_missing_iso_sidecar_safely(tmp_path, sidecar_state):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "generate-release-manifest.sh"
    script.write_bytes((ROOT / "scripts/generate-release-manifest.sh").read_bytes())
    dist = project / "dist"
    dist.mkdir()
    (dist / "beamo-wipe-0.2.9-amd64.iso").write_bytes(b"fixture ISO")
    outside = tmp_path / "foreign-sidecar.txt"
    if sidecar_state == "dangling-link":
        (dist / "beamo-wipe-0.2.9-amd64.iso.sha256").symlink_to(outside)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = fake_bin / "python3"
    python.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = -c ]; then exec \"$BEAMO_REAL_PYTHON\" \"$@\"; fi\n"
        "printf fixture > \"$BEAMO_WIPE_MANIFEST_DEST\"\n"
        "(cd dist && sha256sum \"${BEAMO_WIPE_MANIFEST_DEST##*/}\" > \"${BEAMO_WIPE_MANIFEST_DEST##*/}.sha256\")\n"
    )
    python.chmod(0o755)

    result = subprocess.run(
        ["sh", str(script)],
        cwd=project,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "ALLOW_DIRTY": "1",
            "BEAMO_WIPE_VERSION": "0.2.9",
            "BEAMO_REAL_PYTHON": sys.executable,
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    if sidecar_state == "missing":
        assert result.returncode == 0, result.stderr
        assert "dist/" not in (dist / "beamo-wipe-0.2.9-amd64.iso.sha256").read_text()
        assert (dist / "SHA256SUMS").is_file()
    else:
        assert result.returncode != 0
        assert not outside.exists()
