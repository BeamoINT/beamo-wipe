"""The hosted preview phase must reject malformed generated JavaScript."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_hosted_preview_rejects_a_javascript_syntax_failure(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_node = fake_bin / "node"
    fake_node.write_text(
        "#!/bin/sh\necho 'intentional JavaScript parse failure' >&2\nexit 7\n",
        encoding="utf-8",
    )
    fake_node.chmod(0o755)
    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}{os.pathsep}{env['PATH']}",
        BEAMO_GATE_CHILD="1",
        BEAMO_WIPE_NO_OPEN="1",
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "ci-hosted.sh"), "preview"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, result.stdout
    assert "intentional JavaScript parse failure" in result.stdout + result.stderr
