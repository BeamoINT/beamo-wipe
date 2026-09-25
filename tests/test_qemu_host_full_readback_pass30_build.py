"""The hosted nwipe boundary must inspect the entire disposable target."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _host_readback_verifier() -> str:
    shell = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = shell.split('if [[ "$nwipe_method" == zero ]]; then', 1)[1]
    return block.split('python3 - "$raw"', 1)[1].split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]


def _check(path: Path, size: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-", str(path), str(size)],
        input=_host_readback_verifier(), capture_output=True, text=True,
    )


def _host_log_verifier() -> str:
    shell = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = shell.split('python3 - "$logf" "$nwipe_method" "$verify" "$LOOP"', 1)[1]
    return block.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]


def test_host_gate_accepts_fully_changed_disposable_target(tmp_path):
    target = tmp_path / "changed.raw"
    target.write_bytes(bytes(range(256)) * 8192)
    checked = _check(target, target.stat().st_size)
    assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("untouched_offset", [1024 * 1024, 2 * 1024 * 1024 - 512])
def test_host_gate_rejects_untouched_sector_beyond_first_megabyte(tmp_path, untouched_offset):
    target = tmp_path / "partial.raw"
    target.write_bytes(b"\x00" * (2 * 1024 * 1024))
    with target.open("r+b") as stream:
        stream.seek(untouched_offset)
        stream.write(b"\xa5" * 512)

    checked = _check(target, target.stat().st_size)
    assert checked.returncode != 0, checked.stdout + checked.stderr


def test_host_gate_rejects_short_readback(tmp_path):
    target = tmp_path / "short.raw"
    target.write_bytes(b"\x00" * (2 * 1024 * 1024 - 512))
    checked = _check(target, 2 * 1024 * 1024)
    assert checked.returncode != 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("ending", ["", "\r"])
def test_host_gate_rejects_unterminated_target_success_row(tmp_path, ending):
    log = tmp_path / "truncated.log"
    log.write_text(
        "method = PRNG Stream\nverify = 1 (last pass)\nrounds = 1\n"
        "Starting pass 1/1, round 1/1, on /dev/loop0\n"
        "Verifying pass 1 of 1, round 1 of 1, on /dev/loop0\n"
        "Verified pass 1 of 1, round 1 of 1, on '/dev/loop0'.\n"
        "Finished pass 1/1, round 1/1, on /dev/loop0\n"
        "********************************* Drive Status *********************************\n"
        "     loop0 | Erased |  120 MB/s | 00:00:02 | QEMU/DISK" + ending
    )
    checked = subprocess.run(
        [sys.executable, "-", str(log), "prng", "last", "/dev/loop0"],
        input=_host_log_verifier(), capture_output=True, text=True,
    )
    assert checked.returncode != 0, checked.stdout + checked.stderr
