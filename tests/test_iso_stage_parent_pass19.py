"""ISO staging cleanup must not traverse a redirected live-build parent."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_iso_stage_cleanup_refuses_linked_parent(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts" / "build-iso.sh", scripts / "build-iso.sh")
    shutil.copyfile(
        ROOT / "scripts" / "stage_wrapper_sources.py",
        scripts / "stage_wrapper_sources.py",
    )
    package = project / "src" / "beamo_wipe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.9"\n')

    foreign = tmp_path / "foreign"
    target = foreign / "beamo_wipe"
    target.mkdir(parents=True)
    sentinel = target / "keep.txt"
    sentinel.write_text("outside live-build staging")
    linked_parent = (
        project / "packaging/live/config/includes.chroot/usr/lib/python3/dist-packages"
    )
    linked_parent.parent.mkdir(parents=True)
    linked_parent.symlink_to(foreign, target_is_directory=True)

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

    assert result.returncode != 0
    assert "wrapper staging failed" in result.stderr
    assert sentinel.read_text() == "outside live-build staging"


def test_iso_stage_preparation_clears_only_generated_directories(tmp_path):
    live = tmp_path / "packaging" / "live"
    staged = live / "config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe"
    nested = staged / "old" / "nested"
    nested.mkdir(parents=True)
    (nested / "stale.py").write_text("stale")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("safe")
    (staged / "link").symlink_to(foreign, target_is_directory=True)

    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "stage_wrapper_sources.py"),
            "--prepare",
            str(live),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert list(staged.iterdir()) == []
    assert (foreign / "keep.txt").read_text() == "safe"
    assert (live / "config/includes.chroot/usr/share/beamo-wipe/helper").is_dir()
    assert (live / "config/includes.binary").is_dir()


def test_iso_stage_preparation_rejects_linked_binary_output(tmp_path):
    live = tmp_path / "packaging" / "live"
    binary = live / "config/includes.binary"
    binary.mkdir(parents=True)
    foreign = tmp_path / "foreign.html"
    foreign.write_text("foreign")
    (binary / "START-HERE.html").symlink_to(foreign)

    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "stage_wrapper_sources.py"),
            "--prepare",
            str(live),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert foreign.read_text() == "foreign"
