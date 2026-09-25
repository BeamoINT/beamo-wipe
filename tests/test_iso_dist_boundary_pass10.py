"""ISO publication must not follow a linked repository output directory."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_iso_builder_rejects_linked_dist_before_any_docker_work(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    source = (ROOT / "scripts/build-iso.sh").read_text()
    # Run the real preflight, then stop before Docker inspection or staging.
    (scripts / "build-iso.sh").write_text(
        source.split("DOCKER_INFO=", 1)[0] + "exit 0\n"
    )
    package = project / "src/beamo_wipe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.10"\n')

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    sentinel = foreign / "keep.txt"
    sentinel.write_text("foreign output")
    (project / "dist").symlink_to(foreign, target_is_directory=True)

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

    assert result.returncode == 2
    assert "regular output directory" in result.stderr
    assert sentinel.read_text() == "foreign output"


def test_iso_builder_rechecks_output_after_long_build_window(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    source = (ROOT / "scripts/build-iso.sh").read_text()
    staging = source.index('echo "Staging live-build includes…"')
    docker_failure = source.index('if [ "$docker_status" -ne 0 ]; then', staging)
    post_docker = source.index("\nfi\n", docker_failure) + len("\nfi\n")
    source = (
        source[:staging]
        + 'BUILD_OUT="$(mktemp -d "$OUT_DIR/.build-output.XXXXXX")"\n'
        + 'mv "$OUT_DIR" "$ROOT/original-dist"\n'
        + 'ln -s "$BEAMO_FIXTURE_FOREIGN" "$OUT_DIR"\n'
        + 'foreign_stage="$BEAMO_FIXTURE_FOREIGN/${BUILD_OUT##*/}"\n'
        + 'mkdir "$foreign_stage"\n'
        + 'printf fake > "$foreign_stage/$ISO_NAME"\n'
        + source[post_docker:]
    )
    # A swapped path can appear to contain the staged ISO. Stop before backup
    # or publication, after the builder's staged-output and boundary checks.
    source = (
        source.split('BACKUP_DIR="$(mktemp -d "$OUT_DIR/.bundle-backup.', 1)[0]
        + "exit 0\n"
    )
    (scripts / "build-iso.sh").write_text(source)
    package = project / "src/beamo_wipe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.10"\n')
    (project / "dist").mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    sentinel = foreign / "keep.txt"
    sentinel.write_text("foreign output")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("docker", "sha256sum"):
        command = fake_bin / name
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
    result = subprocess.run(
        ["sh", str(scripts / "build-iso.sh")],
        cwd=project,
        env={
            **os.environ,
            "BEAMO_FIXTURE_FOREIGN": str(foreign),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "regular output directory" in result.stderr
    assert sentinel.read_text() == "foreign output"
