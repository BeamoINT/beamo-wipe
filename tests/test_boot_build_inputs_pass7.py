"""The live image may consume only reviewed config and fresh lb outputs."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_iso_live_assets_pass20 import _fixture


ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "scripts/stage_wrapper_sources.py"
ASSETS = ROOT / "scripts/stage_live_assets.py"


@pytest.mark.parametrize(
    "relative",
    [
        "config/package-lists/extra.list.chroot",
        "config/archives/extra.list.chroot",
        "config/bootloaders/isolinux/extra.cfg",
    ],
)
def test_unreviewed_live_build_config_cannot_enter_image(tmp_path, relative):
    project, live, _ = _fixture(tmp_path)
    injected = live / relative
    injected.parent.mkdir(parents=True, exist_ok=True)
    injected.write_text("unreviewed build input\n")

    result = subprocess.run(
        [sys.executable, str(ASSETS), str(project), str(live)],
        cwd=project,
        env={**os.environ, "BUILD_ID": "local"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, result.stderr
    assert "unreviewed live config" in result.stderr


@pytest.mark.parametrize(
    "relative", ["config/binary", "config/package-lists/live.list.chroot"]
)
def test_prepare_preserves_unidentified_live_build_config(tmp_path, relative):
    project, live, _ = _fixture(tmp_path)
    stale = live / relative
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale live-build setting\n")

    result = subprocess.run(
        [sys.executable, str(STAGER), "--prepare", str(live)],
        cwd=project,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires deliberate cleanup" in result.stderr
    assert stale.read_text() == "stale live-build setting\n"


def test_prepare_preserves_unidentified_generated_link_without_following_it(tmp_path):
    project, live, _ = _fixture(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.write_text("retain me\n")
    generated = live / "config/binary"
    generated.symlink_to(foreign)

    result = subprocess.run(
        [sys.executable, str(STAGER), "--prepare", str(live)],
        cwd=project,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert generated.is_symlink()
    assert foreign.read_text() == "retain me\n"
