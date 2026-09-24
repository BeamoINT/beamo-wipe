# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutation gate must never expose a fail-open shared source tree."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def test_negative_gate_mutates_only_private_source(tmp_path: Path) -> None:
    """Pause the fake checkout's gate during its pytest child and inspect source."""
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "src").mkdir()
    (checkout / "tests" / "fixtures").mkdir(parents=True)
    shutil.copy2(
        ROOT / "scripts" / "ci-hosted.sh", checkout / "scripts" / "ci-hosted.sh"
    )
    shutil.copy2(ROOT / "pyproject.toml", checkout / "pyproject.toml")
    shutil.copytree(
        ROOT / "src" / "beamo_wipe",
        checkout / "src" / "beamo_wipe",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copy2(
        ROOT / "tests" / "test_boot_exclusion_fails_closed.py",
        checkout / "tests" / "test_boot_exclusion_fails_closed.py",
    )
    shutil.copy2(
        ROOT / "tests" / "fixtures" / "lsblk_same_size.json",
        checkout / "tests" / "fixtures" / "lsblk_same_size.json",
    )
    safety = checkout / "src" / "beamo_wipe" / "safety.py"
    before = safety.read_bytes()
    original_mtime = safety.stat().st_mtime_ns
    original_mode = stat.S_IMODE(safety.stat().st_mode)

    wrappers = tmp_path / "bin"
    wrappers.mkdir()
    marker = tmp_path / "pytest-started"
    wrapper = wrappers / "python3"
    wrapper.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "pytest" ]; then\n'
        '  : > "$BEAMO_NEGATIVE_PROBE_MARKER"\n'
        "  sleep 1\n"
        "fi\n"
        'exec "$BEAMO_NEGATIVE_REAL_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = os.environ.copy()
    env.update(
        BEAMO_GATE_CHILD="1",
        BEAMO_NEGATIVE_PROBE_MARKER=str(marker),
        BEAMO_NEGATIVE_REAL_PYTHON=sys.executable,
        PATH=str(wrappers) + os.pathsep + env["PATH"],
    )
    proc = subprocess.Popen(
        ["bash", "scripts/ci-hosted.sh", "negative"],
        cwd=checkout,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 15
    while not marker.exists() and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    during = safety.read_bytes()
    during_mtime = safety.stat().st_mtime_ns
    during_mode = stat.S_IMODE(safety.stat().st_mode)
    output, _ = proc.communicate(timeout=30)
    assert marker.exists(), output
    assert proc.returncode == 0, output
    assert (
        during == before
        and during_mtime == original_mtime
        and during_mode == original_mode
    ), (
        "Negative gate changed its checkout's safety.py while another process could import it.\n"
        + output
    )
    assert safety.read_bytes() == before
    assert stat.S_IMODE(safety.stat().st_mode) == original_mode
