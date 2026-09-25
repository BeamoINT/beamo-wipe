"""Live-stage preparation preserves user work at ignored generated paths."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from test_iso_live_assets_pass20 import _fixture

STAGER = Path(__file__).resolve().parents[1] / "scripts/stage_wrapper_sources.py"


@pytest.mark.parametrize(
    "relative",
    [
        "config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe/user-note.txt",
        "config/includes.chroot/usr/share/beamo-wipe/user-note.txt",
        "config/includes.chroot/usr/share/doc/beamo-wipe/user-note.txt",
        "config/binary",
        "config/package-lists/live.list.chroot",
    ],
)
def test_prepare_preserves_unknown_untracked_content(tmp_path, relative):
    project, live, _ = _fixture(tmp_path)
    custom = live / relative
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text("user authored source\n")

    result = subprocess.run(
        [sys.executable, str(STAGER), "--prepare", str(live)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert custom.read_text() == "user authored source\n"


def test_prepare_refreshes_only_reviewed_generated_assets(tmp_path):
    project, live, _ = _fixture(tmp_path)
    wrapper = live / "config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe"
    assert (wrapper / "payload.py").is_file()
    share = live / "config/includes.chroot/usr/share/beamo-wipe"
    (share / "helper").mkdir(parents=True, exist_ok=True)
    (share / "helper/index.html").write_text("old generated helper\n")
    docs = live / "config/includes.chroot/usr/share/doc/beamo-wipe"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "NOTICE").write_text("old generated notice\n")

    result = subprocess.run(
        [sys.executable, str(STAGER), "--prepare", str(live)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert list(wrapper.iterdir()) == []
    assert not (share / "helper/index.html").exists()
    assert not (docs / "NOTICE").exists()
