"""A local ISO build must not import an ignored ISO from an earlier run."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest


INSIDE_DOCKER = Path(__file__).resolve().parents[1] / "packaging/live/inside-docker.sh"


def _copy_excludes() -> list[str]:
    source = INSIDE_DOCKER.read_text()
    command = source.split("rsync -a \\\n", 1)[1].split("/src/ /build/", 1)[0]
    return re.findall(r"--exclude '([^']+)'", command)


def test_source_copy_explicitly_excludes_prior_iso_outputs():
    assert "*.iso" in _copy_excludes()


def test_source_copy_does_not_import_prior_iso(tmp_path):
    if shutil.which("rsync") is None:
        pytest.skip("rsync is installed in the live-build container")
    source = tmp_path / "source"
    target = tmp_path / "target"
    iso = source / "packaging/live/stale-previous-build.iso"
    iso.parent.mkdir(parents=True)
    iso.write_bytes(b"old image")
    (source / "packaging/live/inside-docker.sh").write_text("reviewed build input")
    target.mkdir()
    result = subprocess.run(
        [
            "rsync",
            "-an",
            "--out-format=%n",
            *(item for pattern in _copy_excludes() for item in ("--exclude", pattern)),
            f"{source}/",
            f"{target}/",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "packaging/live/stale-previous-build.iso" not in result.stdout
