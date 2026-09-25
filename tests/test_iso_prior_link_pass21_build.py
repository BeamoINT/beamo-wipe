"""An ISO rebuild must preserve unfamiliar links at old bundle names."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_iso_bundle_preflight_rejects_prior_symlink(tmp_path):
    source = (ROOT / "scripts/build-iso.sh").read_text()
    # Execute the real bundle preflight without Docker work. The checked
    # filename is a disposable link; its target is a separate sentinel.
    preflight = (
        "require_prior_bundle_paths() {"
        + source.split("require_prior_bundle_paths() {", 1)[1].split(
            "\ncleanup()", 1
        )[0]
    )
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "build-iso.sh").write_text(
        '#!/bin/sh\nset -eu\nOUT_DIR="$1"\n'
        'BUNDLE_FILES="beamo-wipe-0.2.9-amd64.iso"\n'
        + preflight
        + "\nrequire_prior_bundle_paths\n"
    )
    dist = project / "dist"
    dist.mkdir()
    sentinel = tmp_path / "prior-asset"
    sentinel.write_text("keep")
    prior = dist / "beamo-wipe-0.2.9-amd64.iso"
    prior.symlink_to(sentinel)

    result = subprocess.run(
        ["sh", str(scripts / "build-iso.sh"), str(dist)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Unsafe prior ISO bundle path" in result.stderr
    assert prior.is_symlink()
    assert sentinel.read_text() == "keep"


def test_iso_bundle_rechecks_link_moved_after_preflight(tmp_path):
    source = (ROOT / "scripts/build-iso.sh").read_text()
    backup_loop = source[
        source.index("for name in $BUNDLE_FILES; do", source.index("bundle_in_progress=1")):
        source.index("\nbundle_in_progress=2", source.index("bundle_in_progress=1"))
    ]
    dist = tmp_path / "dist"
    backup = tmp_path / "backup"
    dist.mkdir()
    backup.mkdir()
    sentinel = tmp_path / "personal-file"
    sentinel.write_text("keep")
    name = "beamo-wipe-0.2.9-amd64.iso"
    # The link appears after the early preflight, just before the backup
    # loop moves the path. The moved entry still has to be rejected.
    program = (
        "set -eu\n"
        f"OUT_DIR={shlex.quote(str(dist))}\n"
        f"BACKUP_DIR={shlex.quote(str(backup))}\n"
        f"BUNDLE_FILES={shlex.quote(name)}\n"
        f"ln -s {shlex.quote(str(sentinel))} {shlex.quote(str(dist / name))}\n"
        + backup_loop
    )
    result = subprocess.run(
        ["sh", "-c", program], capture_output=True, text=True, timeout=10
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Unsafe prior ISO bundle path changed during backup" in result.stderr
    assert (backup / name).is_symlink()
    assert sentinel.read_text() == "keep"
