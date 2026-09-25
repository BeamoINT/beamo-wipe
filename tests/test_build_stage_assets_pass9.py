"""Live asset staging preserves the intended launcher behavior."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "beamo_iso_live_assets_fixture_pass9",
    ROOT / "tests" / "test_iso_live_assets_pass20.py",
)
assert FIXTURE_SPEC and FIXTURE_SPEC.loader
FIXTURE = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(FIXTURE)


def test_staged_linux_launcher_is_executable_even_if_cached_mode_is_lost(tmp_path):
    project, live, _source = FIXTURE._fixture(tmp_path)
    cached = project / "dist/desktop/Start Beamo Wipe Linux"
    cached.chmod(0o644)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "stage_live_assets.py"),
            str(project),
            str(live),
        ],
        cwd=project,
        env={**os.environ, "BUILD_ID": "local"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    staged = live / "config/includes.binary/Start Beamo Wipe Linux"
    assert staged.stat().st_mode & 0o111
