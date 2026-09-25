"""Release publication must not buffer an unbounded QEMU log line."""

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_release_gcs as publisher  # noqa: E402


def test_qemu_log_reader_refuses_oversized_line_even_with_later_digest(tmp_path):
    evidence = tmp_path / "dist" / "evidence"
    evidence.mkdir(parents=True)
    digest = "a" * 64
    (evidence / "qemu.log").write_bytes(
        b"x" * (2 * 1024 * 1024)
        + b"\n[qemu-verify] usb_image_sha256=" + digest.encode() + b"\n"
    )

    with pytest.raises(publisher.PublishError, match="log line exceeded"):
        publisher._qemu_tested_usb_sha(tmp_path)


def test_qemu_log_reader_keeps_exact_digest_and_rejects_duplicates(tmp_path):
    evidence = tmp_path / "dist" / "evidence"
    evidence.mkdir(parents=True)
    digest = "b" * 64
    marker = f"[qemu-verify] usb_image_sha256={digest}\n"
    log = evidence / "qemu.log"
    log.write_text("ordinary output\n" + marker)
    assert publisher._qemu_tested_usb_sha(tmp_path) == digest

    log.write_text(marker + marker)
    with pytest.raises(publisher.PublishError, match="ambiguous"):
        publisher._qemu_tested_usb_sha(tmp_path)
