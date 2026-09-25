"""The manifest command must not block on a planted evidence pipe."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO only")
def test_manifest_generator_rejects_fifo_gate_receipt(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/generate-release-manifest.sh", tmp_path / "scripts")
    evidence = tmp_path / "dist/evidence"
    evidence.mkdir(parents=True)
    os.mkfifo(evidence / "lint.receipt.json")
    (evidence / "packages.json").write_text("{}")
    env = dict(os.environ, ALLOW_DIRTY="1", PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run(
        ["sh", str(tmp_path / "scripts/generate-release-manifest.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode != 0
    assert "safely read" in result.stderr.lower() or "unsafe" in result.stderr.lower()
