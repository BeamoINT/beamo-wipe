"""The skipped hosted QEMU gate must not follow a planted evidence link."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_skipped_qemu_does_not_overwrite_existing_evidence_link(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "ci-hosted.sh").write_bytes((ROOT / "scripts/ci-hosted.sh").read_bytes())
    evidence = tmp_path / "qemu-evidence"
    evidence.mkdir()
    sentinel = tmp_path / "owner-data.txt"
    sentinel.write_text("owner data\n")
    (evidence / "SKIPPED.txt").symlink_to(sentinel)

    result = subprocess.run(
        ["bash", str(scripts / "ci-hosted.sh"), "qemu"],
        cwd=tmp_path,
        env={**os.environ, "BEAMO_GATE_CHILD": "1", "SKIP_QEMU": "true"},
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode != 0
    assert sentinel.read_text() == "owner data\n"


def test_qemu_evidence_copy_does_not_follow_existing_link(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "ci-hosted.sh").write_bytes((ROOT / "scripts/ci-hosted.sh").read_bytes())
    (scripts / "build-usb-image.sh").write_text("#!/bin/sh\nexit 0\n")
    (scripts / "build-usb-image.sh").chmod(0o755)
    source = tmp_path / "generated-evidence"
    source.mkdir()
    (source / "run.txt").write_text("new evidence\n")
    (scripts / "qemu-verify.sh").write_text(
        "#!/bin/sh\nprintf '%s\\n' '" + str(source) + "' > qemu-evidence/PATH\n"
    )
    (scripts / "qemu-verify.sh").chmod(0o755)
    evidence = tmp_path / "qemu-evidence"
    evidence.mkdir()
    sentinel = tmp_path / "owner-data.txt"
    sentinel.write_text("owner data\n")
    (evidence / "run.txt").symlink_to(sentinel)

    env = {**os.environ, "BEAMO_GATE_CHILD": "1"}
    if platform.system() == "Darwin":
        gcp = shutil.which("gcp")
        if not gcp:
            pytest.skip("GNU cp is required to reproduce the hosted Linux behavior")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "cp").symlink_to(gcp)
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["bash", str(scripts / "ci-hosted.sh"), "qemu"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode != 0
    assert sentinel.read_text() == "owner data\n"


def test_direct_qemu_gate_does_not_redirect_path_receipt(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    gate = (ROOT / "scripts/qemu-verify.sh").read_text()
    # The disposable fixture is not a Linux worker. Bypass only the Mac guard;
    # a fake QEMU command fails before any device operation can be reached.
    assert "if [[ -d /Users/HP ]]; then" in gate
    (scripts / "qemu-verify.sh").write_text(
        gate.replace("if [[ -d /Users/HP ]]; then", "if false; then", 1)
    )
    (scripts / "qemu-verify.sh").chmod(0o755)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "beamo-wipe-0.2.9-amd64.iso").write_bytes(b"fake ISO")
    (dist / "beamo-wipe-0.2.9-amd64.manifest.json").write_text("{}")
    evidence = tmp_path / "qemu-evidence"
    evidence.mkdir()
    sentinel = tmp_path / "owner-data.txt"
    sentinel.write_text("owner data\n")
    (evidence / "PATH").symlink_to(sentinel)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uname").write_text(
        '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n'
    )
    (bin_dir / "uname").chmod(0o755)
    (bin_dir / "mktemp").write_text(
        '#!/bin/sh\nmkdir -p "$BEAMO_TEST_RUN_ROOT"\nprintf \'%s\\n\' "$BEAMO_TEST_RUN_ROOT"\n'
    )
    (bin_dir / "mktemp").chmod(0o755)
    (bin_dir / "qemu-system-x86_64").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "qemu-system-x86_64").chmod(0o755)
    result = subprocess.run(
        ["bash", str(scripts / "qemu-verify.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "BEAMO_TEST_RUN_ROOT": str(tmp_path / "run-root"),
        },
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode != 0
    assert sentinel.read_text() == "owner data\n"


def test_hosted_qemu_receipt_cannot_be_swapped_by_external_reader(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "ci-hosted.sh").write_bytes((ROOT / "scripts/ci-hosted.sh").read_bytes())
    (scripts / "build-usb-image.sh").write_text("#!/bin/sh\nexit 0\n")
    (scripts / "build-usb-image.sh").chmod(0o755)
    trusted = tmp_path / "trusted-evidence"
    trusted.mkdir()
    (trusted / "run.txt").write_text("trusted\n")
    attacker = tmp_path / "attacker-evidence"
    attacker.mkdir()
    (attacker / "run.txt").write_text("attacker\n")
    (scripts / "qemu-verify.sh").write_text(
        "#!/bin/sh\nprintf '%s\\n' '" + str(trusted) + "' > qemu-evidence/PATH\n"
    )
    (scripts / "qemu-verify.sh").chmod(0o755)
    attacker_receipt = tmp_path / "attacker-path.txt"
    attacker_receipt.write_text(str(attacker) + "\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "cat").write_text(
        "#!/bin/sh\nmv qemu-evidence/PATH qemu-evidence/PATH.original\n"
        'ln -s "$BEAMO_TEST_ATTACKER_RECEIPT" qemu-evidence/PATH\n'
        'exec /bin/cat "$@"\n'
    )
    (bin_dir / "cat").chmod(0o755)
    result = subprocess.run(
        ["bash", str(scripts / "ci-hosted.sh"), "qemu"],
        cwd=tmp_path,
        env={
            **os.environ,
            "BEAMO_GATE_CHILD": "1",
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "BEAMO_TEST_ATTACKER_RECEIPT": str(attacker_receipt),
        },
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "qemu-evidence" / "run.txt").read_text() == "trusted\n"
    assert not (tmp_path / "qemu-evidence" / "PATH").is_symlink()
