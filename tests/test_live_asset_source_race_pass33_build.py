"""Live-image staging must bind copied assets to their source bytes."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from test_iso_live_assets_pass20 import _fixture


ROOT = Path(__file__).resolve().parents[1]


def test_stage_rejects_helper_changed_after_copy(tmp_path: Path) -> None:
    project, live, _source = _fixture(tmp_path)
    code = (
        "from pathlib import Path; import sys\n"
        "sys.path.insert(0, sys.argv[1]); import stage_live_assets as assets\n"
        "original = assets.read_regular_bytes\n"
        "def read_then_alter(path, **kwargs):\n"
        "    data = original(path, **kwargs)\n"
        "    if path == Path(sys.argv[2]) / 'helper/index.html':\n"
        "        path.write_text('<html>changed while staging</html>\\n')\n"
        "    return data\n"
        "assets.read_regular_bytes = read_then_alter\n"
        "assets.stage_assets(Path(sys.argv[2]), Path(sys.argv[3]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "scripts"), str(project), str(live)],
        cwd=project, env={**os.environ, "BUILD_ID": "local"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "source asset changed" in result.stderr


def test_stage_rejects_sound_changed_after_copy(tmp_path: Path) -> None:
    project, live, _source = _fixture(tmp_path)
    code = (
        "from pathlib import Path; import sys\n"
        "sys.path.insert(0, sys.argv[1]); import stage_live_assets as assets\n"
        "original = assets.read_regular_file\n"
        "def read_then_alter(path, **kwargs):\n"
        "    result = original(path, **kwargs)\n"
        "    if path == Path(sys.argv[2]) / 'packaging/sounds/finished.wav':\n"
        "        path.write_bytes(b'changed while staging')\n"
        "    return result\n"
        "assets.read_regular_file = read_then_alter\n"
        "assets.stage_assets(Path(sys.argv[2]), Path(sys.argv[3]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "scripts"), str(project), str(live)],
        cwd=project, env={**os.environ, "BUILD_ID": "local"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "source asset changed" in result.stderr


def test_stage_rejects_source_changed_between_two_copies(tmp_path: Path) -> None:
    project, live, _source = _fixture(tmp_path)
    code = (
        "from pathlib import Path; import sys\n"
        "sys.path.insert(0, sys.argv[1]); import stage_live_assets as assets\n"
        "original = assets.read_regular_file\n"
        "changed = False\n"
        "def read_then_alter(path, **kwargs):\n"
        "    global changed\n"
        "    result = original(path, **kwargs)\n"
        "    if path == Path(sys.argv[2]) / 'LICENSE' and not changed:\n"
        "        changed = True\n"
        "        path.write_bytes(b'changed between copies')\n"
        "    return result\n"
        "assets.read_regular_file = read_then_alter\n"
        "assets.stage_assets(Path(sys.argv[2]), Path(sys.argv[3]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "scripts"), str(project), str(live)],
        cwd=project, env={**os.environ, "BUILD_ID": "local"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "source asset changed" in result.stderr
