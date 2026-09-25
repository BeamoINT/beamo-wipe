"""QEMU readback must reject sectors that are almost entirely prefill."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHELL = (ROOT / "scripts/qemu-verify.sh").read_text()


def _heredoc(after: str) -> str:
    return SHELL.split(after, 1)[1].split("<<'PY'", 1)[1].split("\n", 1)[1].split("\nPY", 1)[0]


HOST_CHECK = _heredoc('python3 - "$raw" "$HOST_METHOD_BYTES"')
GUEST_CHECK = _heredoc('python3 - "$raw" "$nwipe_method" "$HOST_METHOD_BYTES"')


def test_readback_accepts_changed_sectors_with_sparse_prefill_bytes(tmp_path: Path) -> None:
    target = tmp_path / "changed.raw"
    target.write_bytes(bytes(range(256)) * 8192)
    host = subprocess.run(
        [sys.executable, "-", str(target), str(target.stat().st_size)],
        input=HOST_CHECK,
        capture_output=True,
        text=True,
    )
    guest = subprocess.run(
        [sys.executable, "-", str(target), "prng", str(target.stat().st_size)],
        input=GUEST_CHECK,
        capture_output=True,
        text=True,
    )
    assert host.returncode == 0, host.stdout + host.stderr
    assert guest.returncode == 0, guest.stdout + guest.stderr


@pytest.mark.parametrize("method", ["prng", "dodshort"])
def test_host_rejects_one_changed_byte_per_sector(tmp_path: Path, method: str) -> None:
    target = tmp_path / f"host-{method}.raw"
    target.write_bytes((b"\x00" + b"\xa5" * 511) * 4096)
    checked = subprocess.run(
        [sys.executable, "-", str(target), str(target.stat().st_size)],
        input=HOST_CHECK,
        capture_output=True,
        text=True,
    )
    assert checked.returncode != 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("method", ["prng", "dodshort"])
def test_guest_rejects_one_changed_byte_per_sector(tmp_path: Path, method: str) -> None:
    target = tmp_path / f"guest-{method}.raw"
    target.write_bytes((b"\x00" + b"\xa5" * 511) * 4096)
    checked = subprocess.run(
        [sys.executable, "-", str(target), method, str(target.stat().st_size)],
        input=GUEST_CHECK,
        capture_output=True,
        text=True,
    )
    assert checked.returncode != 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("pattern", [
    b"\x00" * 496 + b"\xa5" * 16,
    bytes(0xA5 if position % 15 == 0 else 0 for position in range(512)),
], ids=["contiguous-16", "scattered-35"])
def test_host_rejects_limited_remaining_prefill(tmp_path: Path, pattern: bytes) -> None:
    target = tmp_path / "partial-host.raw"
    target.write_bytes(pattern * 4096)
    checked = subprocess.run(
        [sys.executable, "-", str(target), str(target.stat().st_size)],
        input=HOST_CHECK,
        capture_output=True,
        text=True,
    )
    assert checked.returncode != 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("pattern", [
    b"\x00" * 496 + b"\xa5" * 16,
    bytes(0xA5 if position % 15 == 0 else 0 for position in range(512)),
], ids=["contiguous-16", "scattered-35"])
def test_guest_rejects_limited_remaining_prefill(tmp_path: Path, pattern: bytes) -> None:
    target = tmp_path / "partial-guest.raw"
    target.write_bytes(pattern * 4096)
    checked = subprocess.run(
        [sys.executable, "-", str(target), "prng", str(target.stat().st_size)],
        input=GUEST_CHECK,
        capture_output=True,
        text=True,
    )
    assert checked.returncode != 0, checked.stdout + checked.stderr
