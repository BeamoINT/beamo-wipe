"""QEMU command recording must not accept an enabled guest network."""

from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "extra",
    [
        "-nic user",
        "-nic none",
        "-nic=user",
        "-netdev user,id=net0",
        "-netdev=user,id=net0",
        "-net user",
        "-readconfig /tmp/network.cfg",
        "-readconfig=/tmp/network.cfg",
        "-device e1000",
        "-device virtio-net-pci",
        "-device=rtl8139",
    ],
)
def test_qemu_cmdline_rejects_network_after_disabled_nic(tmp_path, extra):
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    function = (
        "record_qemu_cmdline() {"
        + source.split("record_qemu_cmdline() {", 1)[1].split("\n}\n", 1)[0]
        + "\n}\n"
    )
    script = tmp_path / "check.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        + function
        + f'record_qemu_cmdline "$1" qemu-system-x86_64 -nic none {extra}\n'
    )
    result = subprocess.run(
        ["bash", str(script), str(tmp_path / "argv.txt")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr


def test_qemu_cmdline_accepts_shipped_device_set(tmp_path):
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    function = (
        "record_qemu_cmdline() {"
        + source.split("record_qemu_cmdline() {", 1)[1].split("\n}\n", 1)[0]
        + "\n}\n"
    )
    script = tmp_path / "check.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        + function
        + 'record_qemu_cmdline "$1" qemu-system-x86_64 -nic none '
        "-device qemu-xhci,id=beamo-xhci "
        "-device usb-storage,drive=beamo-boot-media,serial=BEAMOBOOT,bootindex=1 "
        "-device virtio-blk-pci,drive=beamo-target,serial=0001\n"
    )
    result = subprocess.run(
        ["bash", str(script), str(tmp_path / "argv.txt")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
