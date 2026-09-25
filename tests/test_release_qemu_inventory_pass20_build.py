"""Every QEMU gate artifact must be present in the published release."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_wipe_publisher_pass20_build", ROOT / "scripts/publish_release_gcs.py"
)
assert SPEC and SPEC.loader
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


def _qemu_gate_output_names() -> set[str]:
    """Files written under EVIDENCE_DIR by scripts/qemu-verify.sh."""
    names = {
        "run.txt",
        "untested-physical.txt",
        "qemu-version.txt",
        "source-commit.txt",
        "checksums.txt",
        "isoinfo.txt",
        "nwipe-version.txt",
        "fixed-vulnerabilities.txt",
        "accessible-runtime.txt",
        "report-image.txt",
        "report-helper-crash.txt",
        "fake-disk-e2e.txt",
        "qemu-img.txt",
        "nwipe-invalid-target.txt",
        "summary.txt",
    }
    for label in (
        "uefi",
        "bios-usb",
        "uefi-usb",
        "secureboot-usb",
        "bios-speech-usb",
        "uefi-speech-usb",
    ):
        names.update(
            f"{label}-{suffix}.txt" for suffix in ("serial", "qemu", "cmdline")
        )
    for case in ("everyday", "extra", "quick_zero"):
        for run in (case, f"{case}-repeat"):
            names.update(
                {
                    f"host-{run}.log",
                    f"host-{run}-nwipe.txt",
                    f"bios-{run}-serial.txt",
                    f"bios-{run}-qemu.txt",
                    f"bios-{run}-cmdline.txt",
                    f"guest-{run}-readback.txt",
                    f"guest-{run}-bundle.txt",
                    f"guest-{run}-fsck.txt",
                    f"guest-{run}-mount.txt",
                }
            )
    return names


def test_release_lists_every_qemu_gate_output():
    qemu_dir = PUBLISHER.ROOT / "qemu-evidence"
    listed = {
        path.name
        for path in PUBLISHER._release_inputs("0.2.9")
        if path.parent == qemu_dir
    }
    assert listed == _qemu_gate_output_names()


def test_publisher_rejects_unlisted_or_missing_qemu_gate_output():
    qemu_dir = PUBLISHER.ROOT / "qemu-evidence"
    listed = [qemu_dir / name for name in sorted(_qemu_gate_output_names())]
    PUBLISHER._require_complete_qemu_inputs(
        {path.name: "a" * 64 for path in listed}, listed
    )
    with pytest.raises(PUBLISHER.PublishError, match="QEMU evidence inventory"):
        PUBLISHER._require_complete_qemu_inputs(
            {**{path.name: "a" * 64 for path in listed}, "extra.log": "b" * 64}, listed
        )
    with pytest.raises(PUBLISHER.PublishError, match="QEMU evidence inventory"):
        PUBLISHER._require_complete_qemu_inputs(
            {path.name: "a" * 64 for path in listed[:-1]}, listed
        )
