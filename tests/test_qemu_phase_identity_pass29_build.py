"""QEMU's engine proof must bind each phase to the disposable target."""

from __future__ import annotations

import subprocess
from pathlib import Path
import sys

import pytest

from test_qemu_complete_log_pass28_build import _bundle, _replace_exported_log, _status_row
from test_result_presentations import STATUS


ROOT = Path(__file__).resolve().parents[1]


def test_guest_gate_rejects_phase_lines_for_target_name_prefix(tmp_path):
    session, command, files, _ = _bundle(tmp_path)
    # /dev/vda2 shares the requested target's prefix, so substring searches
    # previously counted every phase as proof of a wipe of /dev/vda.
    log = files["nwipe.log"].replace(b"on /dev/vda\n", b"on /dev/vda2\n")
    _replace_exported_log(session, log)

    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "missing or out-of-order" in checked.stderr


def test_host_gate_rejects_phase_lines_for_another_loop(tmp_path):
    shell = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = shell.split('python3 - "$logf" "$nwipe_method" "$verify"', 1)[1]
    block = block.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    log = tmp_path / "nwipe.log"
    log.write_text(
        "method = PRNG Stream\nverify = 1 (last pass)\nrounds = 1\n"
        "Starting pass 1/1, round 1/1, on /dev/loop0p1\n"
        "Verifying pass 1 of 1, round 1 of 1, on /dev/loop0p1\n"
        "Verified pass 1 of 1, round 1 of 1, on '/dev/loop0p1'.\n"
        "Finished pass 1/1, round 1/1, on /dev/loop0p1\n"
        + STATUS + _status_row("loop0")
    )
    checked = subprocess.run(
        [sys.executable, "-", str(log), "prng", "last", "/dev/loop0"],
        input=block, capture_output=True, text=True,
    )
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "missing or out of order" in checked.stderr


def test_host_gate_accepts_retained_nwipe_042_log():
    shell = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = shell.split('python3 - "$logf" "$nwipe_method" "$verify" "$LOOP"', 1)[1]
    block = block.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    retained = ROOT / "docs/evidence/usb-lab-20260907/linux/boot-gate/nwipe-boundary.txt"
    checked = subprocess.run(
        [sys.executable, "-", str(retained), "zero", "off", "/dev/loop0"],
        input=block, capture_output=True, text=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_host_gate_accepts_pinned_nwipe_verified_phase(tmp_path):
    shell = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = shell.split('python3 - "$logf" "$nwipe_method" "$verify" "$LOOP"', 1)[1]
    block = block.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    log = tmp_path / "nwipe.log"
    log.write_text(
        "method = PRNG Stream\nverify = 1 (last pass)\nrounds = 1\n"
        "Starting pass 1/1, round 1/1, on /dev/loop0\n"
        "Verifying pass 1 of 1, round 1 of 1, on /dev/loop0\n"
        "Verified pass 1 of 1, round 1 of 1, on '/dev/loop0'.\n"
        "Finished pass 1/1, round 1/1, on /dev/loop0\n"
        + STATUS + _status_row("loop0")
    )
    checked = subprocess.run(
        [sys.executable, "-", str(log), "prng", "last", "/dev/loop0"],
        input=block, capture_output=True, text=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_guest_gate_accepts_pinned_nwipe_verified_phase(tmp_path):
    _, command, files, _ = _bundle(tmp_path)
    assert b"Verified pass 1 of 1, round 1 of 1, on '/dev/vda'.\n" in files["nwipe.log"]
    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_guest_gate_accepts_nwipe_042_timestamped_phase_lines(tmp_path):
    session, command, files, _ = _bundle(tmp_path)
    phase_prefixes = (b"Starting pass", b"Verifying pass", b"Verified pass", b"Finished pass")
    log = b"\n".join(
        b"[2026/09/07 04:58:44]  notice: " + line
        if line.startswith(phase_prefixes) else line
        for line in files["nwipe.log"].split(b"\n")
    )
    _replace_exported_log(session, log)
    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("contradiction", [
    "method = Fill With Zeros", "verify = 0 (off)", "rounds = 2",
])
def test_host_gate_rejects_conflicting_engine_option(tmp_path, contradiction):
    shell = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = shell.split('python3 - "$logf" "$nwipe_method" "$verify" "$LOOP"', 1)[1]
    block = block.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    log = tmp_path / "nwipe.log"
    log.write_text(
        "method = PRNG Stream\nverify = 1 (last pass)\nrounds = 1\n"
        f"{contradiction}\n"
        "Starting pass 1/1, round 1/1, on /dev/loop0\n"
        "Verifying pass 1 of 1, round 1 of 1, on /dev/loop0\n"
        "Verified pass 1 of 1, round 1 of 1, on '/dev/loop0'.\n"
        "Finished pass 1/1, round 1/1, on /dev/loop0\n"
        + STATUS + _status_row("loop0")
    )
    checked = subprocess.run(
        [sys.executable, "-", str(log), "prng", "last", "/dev/loop0"],
        input=block, capture_output=True, text=True,
    )
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "conflicting" in checked.stderr
