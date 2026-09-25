"""Release signing CLI must reject special and oversized inputs promptly."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from beamo_wipe import release_signing


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO only")
@pytest.mark.parametrize("kind", ["manifest", "registry", "key"])
def test_cli_input_fifo_fails_without_blocking(tmp_path: Path, kind: str) -> None:
    fifo = tmp_path / "input.fifo"
    os.mkfifo(fifo)
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"beamo_wipe_version":"0.2.9"}')
    registry = tmp_path / "keys.json"
    registry.write_text("{}")
    if kind == "manifest":
        command = [
            "verify",
            "--manifest",
            str(fifo),
            "--signature",
            str(registry),
            "--registry",
            str(registry),
        ]
    elif kind == "registry":
        command = [
            "verify",
            "--manifest",
            str(manifest),
            "--signature",
            str(registry),
            "--registry",
            str(fifo),
        ]
    else:
        command = [
            "sign",
            "--manifest",
            str(manifest),
            "--key-file",
            str(fifo),
            "--out",
            str(tmp_path / "signed.json"),
        ]
    env = dict(os.environ, PYTHONPATH=str(Path(release_signing.__file__).parents[1]))
    result = subprocess.run(
        [sys.executable, "-m", "beamo_wipe.release_signing", *command],
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode != 0
    assert "regular" in result.stderr.lower() or "safely" in result.stderr.lower()


def test_signing_cli_rejects_linked_and_oversized_input(tmp_path: Path) -> None:
    regular = tmp_path / "manifest.json"
    regular.write_bytes(b"{}")
    linked = tmp_path / "linked.json"
    linked.symlink_to(regular)
    with pytest.raises(RuntimeError, match="safely"):
        release_signing._read_bytes_file(linked, what="manifest")
    with regular.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(RuntimeError, match="bounded|limit"):
        release_signing._read_bytes_file(regular, what="manifest")
