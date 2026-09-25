"""Manifest generation refuses source state it cannot verify."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_script_stops_when_git_status_fails(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "generate-release-manifest.sh"
    script.write_bytes((ROOT / "scripts/generate-release-manifest.sh").read_bytes())
    tools = tmp_path / "bin"
    tools.mkdir()
    marker = tmp_path / "python-invoked"
    git = tools / "git"
    git.write_text("#!/bin/sh\nexit 42\n")
    git.chmod(0o755)
    python = tools / "python3"
    python.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n")
    python.chmod(0o755)

    result = subprocess.run(
        ["sh", str(script)],
        cwd=project,
        env={**os.environ, "PATH": f"{tools}:{os.environ['PATH']}", "ALLOW_DIRTY": "0"},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert not marker.exists(), "manifest generation continued after git status failed"
