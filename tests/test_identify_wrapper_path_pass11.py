"""The manual boot-ID wrapper must import its own checked-out package."""

import os
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_identify_wrapper_ignores_untrusted_calling_directory(tmp_path):
    untrusted = tmp_path / "untrusted"
    package = untrusted / "beamo_wipe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# unrelated package\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = fake_bin / "python3"
    python.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} -c "
        "'import importlib.util; print(importlib.util.find_spec(\"beamo_wipe\").origin)'\n"
    )
    python.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [str(ROOT / "scripts/identify-boot-usb.sh")],
        cwd=untrusted,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(ROOT / "src/beamo_wipe/__init__.py")
