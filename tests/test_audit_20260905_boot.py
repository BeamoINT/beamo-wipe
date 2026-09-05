# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute boot/build helpers against inert subprocesses and fake resources."""

from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot"


@pytest.mark.parametrize("exit_code", [0, 1, 37, 126, 127, 130, 143])
def test_build_hook_logged_command_preserves_failure_status(tmp_path, exit_code):
    source = HOOK.read_text(encoding="utf-8")
    function = source[
        source.index("run_logged() {"):
        source.index('\nrun_logged "$WORKDIR/apt-update.log"')
    ]
    result = subprocess.run(  # noqa: S603
        [
            "/bin/sh", "-c",
            function + '\nrun_logged "$1/log" /bin/sh -c \'exit "$1"\' fake "$2"\n',
            "proof", str(tmp_path), str(exit_code),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == exit_code, result.stderr
    if exit_code:
        assert f"command failed (exit {exit_code})" in result.stderr
    else:
        assert not result.stderr
