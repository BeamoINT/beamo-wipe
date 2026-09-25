"""Cloud submission must fail if it cannot establish checkout cleanliness."""

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_cloud_submit_rejects_git_status_failure(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = status ] && [ "$2" = --porcelain ]; then exit 42; fi\n'
        "exit 0\n"
    )
    git.chmod(0o755)
    calls = tmp_path / "gcloud-called"
    gcloud = fake_bin / "gcloud"
    gcloud.write_text(f"#!/bin/sh\nprintf called > '{calls}'\n")
    gcloud.chmod(0o755)
    env = os.environ.copy()
    env.pop("SUBSTITUTIONS", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/ci-cloud.sh")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not calls.exists()


def test_cloud_submit_preserves_hook_when_tracking_check_fails(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "ci-cloud.sh").write_bytes((ROOT / "scripts/ci-cloud.sh").read_bytes())
    hook = checkout / "packaging/live/config/hooks/normal/fixture.hook.chroot"
    hook.parent.mkdir(parents=True)
    hook.symlink_to("/usr/share/live/build/hooks/fixture.hook.chroot")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = ls-files ]; then exit 42; fi\n'
        'if [ "$1" = status ]; then exit 0; fi\n'
        "exit 0\n"
    )
    git.chmod(0o755)
    calls = tmp_path / "gcloud-called"
    gcloud = fake_bin / "gcloud"
    gcloud.write_text(f"#!/bin/sh\nprintf called > '{calls}'\n")
    gcloud.chmod(0o755)
    env = os.environ.copy()
    env.pop("SUBSTITUTIONS", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["bash", str(scripts / "ci-cloud.sh")],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert hook.is_symlink()
    assert not calls.exists()


def test_cloud_submit_does_not_clean_hook_through_linked_parent(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "ci-cloud.sh").write_bytes((ROOT / "scripts/ci-cloud.sh").read_bytes())
    outside = tmp_path / "outside-hooks"
    outside.mkdir()
    hook = outside / "fixture.hook.chroot"
    hook.symlink_to("/usr/share/live/build/hooks/fixture.hook.chroot")
    hooks = checkout / "packaging/live/config/hooks"
    hooks.mkdir(parents=True)
    (hooks / "normal").symlink_to(outside, target_is_directory=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    git.write_text("#!/bin/sh\nexit 0\n")
    git.chmod(0o755)
    calls = tmp_path / "gcloud-called"
    gcloud = fake_bin / "gcloud"
    gcloud.write_text(f"#!/bin/sh\nprintf called > '{calls}'\n")
    gcloud.chmod(0o755)
    env = os.environ.copy()
    env.pop("SUBSTITUTIONS", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["bash", str(scripts / "ci-cloud.sh")],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert hook.is_symlink()
    assert not calls.exists()
