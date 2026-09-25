"""Final release checksums cannot write through a planted link."""

import json
from pathlib import Path
import sys

import pytest

from beamo_wipe import ci_evidence, release_manifest as rm
from test_ci_evidence_pipeline import build_provenance  # noqa: F401 - fixture


def test_finalize_does_not_follow_checksum_symlink(build_provenance, monkeypatch, tmp_path):  # noqa: F811
    root, manifest_path, _iso = build_provenance
    dist = root / "dist"
    outside = tmp_path / "outside-sentinel"
    outside.write_text("keep me")
    sums = dist / "SHA256SUMS"
    sums.symlink_to(outside)
    (dist / "evidence").mkdir()
    (dist / "evidence/packages.json").write_text("{}")
    manifest = json.loads(manifest_path.read_text())
    monkeypatch.setattr(ci_evidence, "load_receipts", lambda _directory: [])
    monkeypatch.setattr(rm, "generate_manifest", lambda **_kwargs: manifest)
    monkeypatch.setattr(rm, "verify_manifest", lambda *_args, **_kwargs: None)

    ci_evidence.finalize(root)

    assert outside.read_text() == "keep me"
    assert sums.is_file() and not sums.is_symlink()
    assert len(sums.read_text().splitlines()) == 2


def test_gate_refuses_dangling_junit_symlink_before_running(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    outside = tmp_path / "outside.xml"
    (evidence / "tests.xml").symlink_to(outside)
    fixture = tmp_path / "write_junit.py"
    fixture.write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['BEAMO_GATE_JUNIT']).write_text("
        "'<testsuite tests=\"1\" failures=\"0\" errors=\"0\" skipped=\"0\">'"
        "+'<testcase name=\"ok\"/></testsuite>')\n"
    )
    with pytest.raises(RuntimeError, match="stale evidence"):
        ci_evidence.run_gate(
            "tests", [sys.executable, str(fixture)],
            root=Path(__file__).resolve().parents[1],
            evidence_dir=evidence, build_id="local",
        )
    assert not outside.exists()


def test_finalizer_rejects_receipt_symlink_outside_evidence(tmp_path):
    evidence = tmp_path / "evidence"
    ci_evidence.run_gate(
        "preview", [sys.executable, "-c", "print('ok')"],
        root=Path(__file__).resolve().parents[1],
        evidence_dir=evidence, build_id="local",
    )
    receipt = evidence / "preview.receipt.json"
    outside = tmp_path / "outside-receipt.json"
    receipt.rename(outside)
    receipt.symlink_to(outside)

    with pytest.raises(RuntimeError, match="safely"):
        ci_evidence.load_receipts(evidence)
