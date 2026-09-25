"""Hosted QEMU evidence must start in an unused output directory."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("stale_name", ["stale.txt", "SKIPPED.txt"])
def test_qemu_gate_rejects_unrelated_preexisting_evidence(
    tmp_path: Path, stale_name: str
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "ci-hosted.sh").write_bytes((ROOT / "scripts/ci-hosted.sh").read_bytes())
    invoked = tmp_path / "builder-invoked"
    (scripts / "build-usb-image.sh").write_text(
        f"#!/bin/sh\ntouch '{invoked}'\n", encoding="utf-8"
    )
    (scripts / "build-usb-image.sh").chmod(0o755)
    source = tmp_path / "generated-evidence"
    source.mkdir()
    (source / "run.txt").write_text("new evidence\n", encoding="utf-8")
    (scripts / "qemu-verify.sh").write_text(
        "#!/bin/sh\nprintf '%s\\n' '" + str(source) + "' > qemu-evidence/PATH\n",
        encoding="utf-8",
    )
    (scripts / "qemu-verify.sh").chmod(0o755)
    evidence = tmp_path / "qemu-evidence"
    evidence.mkdir()
    (evidence / stale_name).write_text("older run\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(scripts / "ci-hosted.sh"), "qemu"],
        cwd=tmp_path,
        env={**os.environ, "BEAMO_GATE_CHILD": "1"},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "stale QEMU evidence" in result.stderr
    assert not invoked.exists()
    assert (evidence / stale_name).read_text(encoding="utf-8") == "older run\n"
    assert not (evidence / "PATH").exists()
