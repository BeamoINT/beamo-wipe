"""Stage only ordinary tracked wrapper files into disposable ISO fixtures."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "scripts" / "stage_wrapper_sources.py"


def test_iso_staging_rejects_tracked_symlink_into_untracked_bytes(tmp_path):
    repo = tmp_path / "checkout"
    wrapper = repo / "src" / "beamo_wipe"
    wrapper.mkdir(parents=True)
    (repo / "external.py").write_text("UNTRACKED_BYTES = True\n")
    (wrapper / "injected.py").symlink_to("../../external.py")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "src/beamo_wipe/injected.py"], cwd=repo, check=True)
    stage = repo / "staged"
    stage.mkdir()
    result = subprocess.run(
        ["python3", str(STAGER), str(repo), str(stage)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (stage / "injected.py").exists()


def test_iso_staging_rejects_linked_parent_of_tracked_file(tmp_path):
    repo = tmp_path / "checkout"
    wrapper = repo / "src" / "beamo_wipe"
    package = wrapper / "pkg"
    package.mkdir(parents=True)
    (package / "module.py").write_text("TRACKED_BYTES = True\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "src/beamo_wipe/pkg/module.py"], cwd=repo, check=True)
    package.rename(repo / "prior-package")
    foreign = repo / "foreign"
    foreign.mkdir()
    (foreign / "module.py").write_text("UNTRACKED_BYTES = True\n")
    package.symlink_to("../../foreign")
    stage = repo / "staged"
    stage.mkdir()
    result = subprocess.run(
        ["python3", str(STAGER), str(repo), str(stage)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (stage / "pkg" / "module.py").exists()


def test_iso_staging_rejects_tracked_fifo_without_waiting_for_writer(tmp_path):
    repo = tmp_path / "checkout"
    wrapper = repo / "src" / "beamo_wipe"
    wrapper.mkdir(parents=True)
    source = wrapper / "module.py"
    source.write_text("TRACKED_BYTES = True\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "src/beamo_wipe/module.py"], cwd=repo, check=True)
    source.unlink()
    os.mkfifo(source)
    stage = repo / "staged"
    stage.mkdir()
    result = subprocess.run(
        ["python3", str(STAGER), str(repo), str(stage)],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (stage / "module.py").exists()


def test_iso_staging_rejects_linked_output_parent(tmp_path):
    repo = tmp_path / "checkout"
    source = repo / "src" / "beamo_wipe" / "pkg" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("TRACKED_BYTES = True\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "src/beamo_wipe/pkg/module.py"], cwd=repo, check=True)
    stage = repo / "staged"
    stage.mkdir()
    foreign = repo / "foreign"
    foreign.mkdir()
    (stage / "pkg").symlink_to(foreign, target_is_directory=True)
    result = subprocess.run(
        ["python3", str(STAGER), str(repo), str(stage)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (foreign / "module.py").exists()


@pytest.mark.parametrize("checkout_state", ["dirty", "clean"])
def test_iso_staging_copies_regular_tracked_file(tmp_path, checkout_state):
    repo = tmp_path / "checkout"
    wrapper = repo / "src" / "beamo_wipe"
    wrapper.mkdir(parents=True)
    (wrapper / "module.py").write_text("TRACKED_BYTES = True\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "src/beamo_wipe/module.py"], cwd=repo, check=True)
    if checkout_state == "clean":
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=repo,
            check=True,
        )
        assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=repo)
    else:
        (repo / "untracked.txt").write_text("local only\n")
    stage = repo / "staged"
    stage.mkdir()
    result = subprocess.run(
        ["python3", str(STAGER), str(repo), str(stage)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (stage / "module.py").read_text() == "TRACKED_BYTES = True\n"
