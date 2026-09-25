"""Exercise the QEMU UEFI probe block without booting or touching real disks."""

from pathlib import Path
import shlex
import subprocess
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("has_vars", [False, True])
def test_uefi_probes_use_available_ovmf_firmware(tmp_path, has_vars):
    code = tmp_path / "OVMF_CODE_4M.fd"
    code.write_bytes(b"fixture firmware")
    if has_vars:
        (tmp_path / "OVMF_VARS_4M.fd").write_bytes(b"fixture variables")
    text = (ROOT / "scripts/qemu-verify.sh").read_text(encoding="utf-8")
    block = 'OVMF_CODE=""' + text.split('OVMF_CODE=""', 1)[1].split(
        "# Enrolled Microsoft keys", 1
    )[0]
    block = block.replace(
        "/usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd",
        f"{shlex.quote(str(code))} {shlex.quote(str(tmp_path / 'missing-code.fd'))}",
    )
    harness = (
        "set -euo pipefail\n"
        f"RUN_ROOT={shlex.quote(str(tmp_path))}\n"
        "boot_probe() { printf '%s %s\\n' \"$1\" \"$*\"; }\n"
        + block
    )
    proc = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    for case in ("uefi", "uefi-usb", "uefi-speech-usb"):
        flag = "-drive " if has_vars else "-bios "
        assert any(line.startswith(case + " ") and flag in line for line in lines)
