"""Random final passes must not leave constant-filled sectors."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _readback_program(guest: bool) -> str:
    script = (ROOT / "scripts/qemu-verify.sh").read_text(encoding="utf-8")
    marker = (
        'python3 - "$raw" "$nwipe_method" "$HOST_METHOD_BYTES"'
        if guest else 'python3 - "$raw" "$HOST_METHOD_BYTES"'
    )
    source = script.split(marker, 1)[1]
    return re.split(r"<<'PY'[^\n]*\n", source, maxsplit=1)[1].split("\nPY", 1)[0]


@pytest.mark.parametrize("guest", [False, True], ids=["host", "guest"])
@pytest.mark.parametrize("method", ["prng", "dodshort"])
@pytest.mark.parametrize("fill", [0x00, 0x5A, 0xFF])
def test_random_final_pass_rejects_constant_target(
    tmp_path: Path, guest: bool, method: str, fill: int,
) -> None:
    target = tmp_path / "constant.raw"
    target.write_bytes(bytes([fill]) * (512 * 64))
    args = [sys.executable, "-", str(target)]
    if guest:
        args.append(method)
    args.append(str(target.stat().st_size))
    result = subprocess.run(
        args, input=_readback_program(guest), capture_output=True, text=True,
        check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("guest", [False, True], ids=["host", "guest"])
def test_random_final_pass_accepts_varied_target(tmp_path: Path, guest: bool) -> None:
    target = tmp_path / "random.raw"
    target.write_bytes(bytes(range(256)) * 128)
    args = [sys.executable, "-", str(target)]
    if guest:
        args.append("prng")
    args.append(str(target.stat().st_size))
    result = subprocess.run(
        args, input=_readback_program(guest), capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
