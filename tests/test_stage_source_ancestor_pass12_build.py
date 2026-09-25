"""The ISO source root may not reach tracked bytes through a linked ancestor."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "scripts/stage_wrapper_sources.py"


def test_iso_staging_rejects_linked_ancestor_of_checkout(tmp_path):
    actual_parent = tmp_path / "actual"
    project = actual_parent / "project"
    wrapper = project / "src/beamo_wipe"
    wrapper.mkdir(parents=True)
    (wrapper / "module.py").write_text("TRACKED = True\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "src/beamo_wipe/module.py"], cwd=project, check=True)

    alias = tmp_path / "linked-parent"
    alias.symlink_to(actual_parent, target_is_directory=True)
    stage = tmp_path / "stage"
    stage.mkdir()
    result = subprocess.run(
        ["python3", str(STAGER), str(alias / "project"), str(stage)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert not (stage / "module.py").exists()
