"""Cloud submission must preserve a hook replaced during generated-link cleanup."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_cloud_submit_preserves_hook_replaced_during_tracking_check(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "ci-cloud.sh"
    script.write_bytes((ROOT / "scripts/ci-cloud.sh").read_bytes())
    hook = checkout / "packaging/live/config/hooks/live/fixture.hook.chroot"
    hook.parent.mkdir(parents=True)
    hook.symlink_to("/usr/share/live/build/hooks/fixture.hook.chroot")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = ls-files ]; then\n'
        '  rm -- "$BEAMO_FIXTURE_HOOK"\n'
        '  printf "new user work" > "$BEAMO_FIXTURE_HOOK"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    git.chmod(0o755)
    called = tmp_path / "gcloud-called"
    gcloud = fake_bin / "gcloud"
    gcloud.write_text(f"#!/bin/sh\nprintf called > '{called}'\n")
    gcloud.chmod(0o755)

    env = os.environ.copy()
    env.pop("SUBSTITUTIONS", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["BEAMO_FIXTURE_HOOK"] = str(hook)
    result = subprocess.run(
        ["bash", str(script)],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert hook.read_text() == "new user work"
    assert not called.exists()
