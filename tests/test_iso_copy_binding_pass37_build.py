"""Live-build must reject copied inputs that differ from the staged host tree."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from beamo_wipe import release_manifest


ROOT = Path(__file__).resolve().parents[1]


def _digest(root: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    with monkeypatch.context() as patch:
        patch.setattr(release_manifest, "ROOT", root)
        values = release_manifest.live_build_inputs()
    raw = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source, copied = tmp_path / "source", tmp_path / "copied"
    helper = source / "packaging/live/config/includes.binary/START-HERE.html"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"reviewed helper\n")
    wrapper = source / "src/beamo_wipe/__init__.py"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_bytes(b"# wrapper fixture\n")
    desktop = source / "desktop/main.go"
    desktop.parent.mkdir(parents=True)
    desktop.write_bytes(b"package main\n")
    copied.mkdir()
    return source, copied, helper


def _container_check() -> str:
    script = (ROOT / "packaging/live/inside-docker.sh").read_text()
    pattern = re.compile(
        r"# BEGIN LIVE INPUT COPY CHECK\n.*?python3 - \"\$BEAMO_WIPE_LIVE_INPUTS_SHA\" /build <<'PYCHECK'\n"
        r"(.*?)\nPYCHECK\n# END LIVE INPUT COPY CHECK",
        re.DOTALL,
    )
    match = pattern.search(script)
    assert match, "container must check the copied live inputs before lb build"
    assert match.end() < script.index("lb build")
    return match.group(1)


def _run_check(code: str, expected: str, copied: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code, expected, str(copied)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_docker_copy_rejects_transient_staged_asset_change(tmp_path, monkeypatch):
    source, copied, helper = _fixture(tmp_path)
    expected = _digest(source, monkeypatch)
    helper.write_bytes(b"transient changed helper\n")
    if shutil.which("rsync"):
        subprocess.run(["rsync", "-a", f"{source}/", f"{copied}/"], check=True)
    else:
        shutil.copytree(source, copied, dirs_exist_ok=True)
    helper.write_bytes(b"reviewed helper\n")
    assert _digest(source, monkeypatch) == expected
    assert _digest(copied, monkeypatch) != expected

    code = _container_check()
    bad = _run_check(code, expected, copied)
    assert bad.returncode != 0
    assert "copied live inputs differ" in bad.stderr

    (copied / "packaging/live/config/includes.binary/START-HERE.html").write_bytes(
        b"reviewed helper\n"
    )
    good = _run_check(code, expected, copied)
    assert good.returncode == 0, good.stderr


def test_build_iso_passes_staged_digest_to_container():
    script = (ROOT / "scripts/build-iso.sh").read_text()
    assert "BEAMO_WIPE_LIVE_INPUTS_SHA=" in script
    assert "-e BEAMO_WIPE_LIVE_INPUTS_SHA=\"$LIVE_INPUTS_SHA\"" in script
    assert script.index("stage_live_assets.py") < script.index("LIVE_INPUTS_SHA=")
    assert script.index("LIVE_INPUTS_SHA=") < script.index("docker run")
