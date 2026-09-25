"""Cloud trigger reconciliation must distinguish missing from unreadable state."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install-cloud-triggers.sh"


def _run_with_describe_error(tmp_path, message: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    fake = bin_dir / "gcloud"
    fake.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$BEAMO_FAKE_GCLOUD_CALLS"\n'
        'case "$*" in *"builds triggers describe "*) '
        'printf "%s\\n" "$BEAMO_FAKE_DESCRIBE_ERROR" >&2; exit 1;; esac\n'
        "exit 0\n"
    )
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "BEAMO_FAKE_GCLOUD_CALLS": str(calls),
        "BEAMO_FAKE_DESCRIBE_ERROR": message,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, calls.read_text() if calls.exists() else ""


def test_trigger_setup_stops_when_inventory_is_unavailable(tmp_path):
    result, calls = _run_with_describe_error(
        tmp_path, "PERMISSION_DENIED: cannot list triggers"
    )
    assert result.returncode != 0
    assert "builds triggers create" not in calls


def test_trigger_setup_can_create_when_trigger_is_confirmed_missing(tmp_path):
    result, calls = _run_with_describe_error(
        tmp_path, "NOT_FOUND: trigger does not exist"
    )
    assert result.returncode == 0, result.stderr
    assert calls.count("builds triggers create") == 2
