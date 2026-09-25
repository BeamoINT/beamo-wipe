"""The ISO staging gate must reject local live-build auto commands."""

from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from stage_live_assets import require_reviewed_live_config  # noqa: E402


def test_unreviewed_live_build_auto_command_cannot_reach_container(tmp_path):
    project = tmp_path / "project"
    live = project / "packaging/live"
    (live / "config").mkdir(parents=True)
    auto = live / "auto/config"
    auto.parent.mkdir()
    auto.write_text("#!/bin/sh\nexit 0\n")
    auto.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)

    # inside-docker.sh copies the whole checkout to /build and runs lb config
    # there. A local auto/config would become an executable live-build input.
    with pytest.raises(RuntimeError, match="unreviewed live-build auto"):
        require_reviewed_live_config(project, live, set())


def test_empty_live_build_auto_directory_is_accepted(tmp_path):
    project = tmp_path / "project"
    live = project / "packaging/live"
    (live / "config").mkdir(parents=True)
    (live / "auto").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)

    require_reviewed_live_config(project, live, set())


def test_container_copy_omits_late_live_build_auto_command(tmp_path):
    rsync = shutil.which("rsync")
    if rsync is None:
        pytest.skip("rsync is unavailable")
    source = tmp_path / "src"
    destination = tmp_path / "build"
    auto = source / "packaging/live/auto/config"
    auto.parent.mkdir(parents=True)
    auto.write_text("#!/bin/sh\nexit 0\n")
    normal = source / "packaging/live/config/package-lists/beamo.list.chroot"
    normal.parent.mkdir(parents=True)
    normal.write_text("python3\n")
    script = (ROOT / "packaging/live/inside-docker.sh").read_text()
    patterns = re.findall(r"--exclude '([^']+)'", script)
    subprocess.run(
        [
            rsync,
            "-a",
            *(arg for pattern in patterns for arg in ("--exclude", pattern)),
            str(source) + "/",
            str(destination) + "/",
        ],
        check=True,
    )

    assert not (destination / "packaging/live/auto").exists()
    assert (
        destination / "packaging/live/config/package-lists/beamo.list.chroot"
    ).read_text() == "python3\n"
