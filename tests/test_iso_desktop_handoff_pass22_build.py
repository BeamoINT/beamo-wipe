"""The ISO must package the exact launcher pair described by its manifest."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from test_iso_live_assets_pass20 import _fixture


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "scripts/stage_live_assets.py"


def test_staging_rejects_launcher_changed_after_bundle_verification(tmp_path):
    project, live, _ = _fixture(tmp_path)
    altered = project / "dist/desktop/Start Beamo Wipe.exe"
    altered.write_bytes(b"changed after desktop verification")

    result = subprocess.run(
        [sys.executable, str(ASSETS), str(project), str(live)],
        cwd=project,
        env={**os.environ, "BUILD_ID": "local"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert "desktop launcher" in result.stderr
