"""Release verification must not wait for a planted special file's writer."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_release_file_reader_rejects_fifo_without_blocking(tmp_path):
    path = tmp_path / "packages.json"
    os.mkfifo(path)
    script = (
        "from beamo_wipe.release_manifest import _open_regular_nofollow\n"
        "import sys\n"
        "_open_regular_nofollow(sys.argv[1])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
