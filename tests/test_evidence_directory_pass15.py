"""CI evidence must stay in the selected checkout directory."""

from pathlib import Path
import sys

import pytest

from beamo_wipe.ci_evidence import load_receipts, print_summary, run_gate


ROOT = Path(__file__).resolve().parents[1]


def test_gate_rejects_linked_evidence_directory_before_running(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    evidence = tmp_path / "evidence"
    evidence.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="evidence directory|symlink"):
        run_gate(
            "preview", [sys.executable, "-c", "print('ran')"],
            root=ROOT, evidence_dir=evidence, build_id="local",
        )
    assert list(outside.iterdir()) == []


def test_finalizer_rejects_linked_evidence_directory(tmp_path):
    evidence = tmp_path / "evidence"
    run_gate(
        "preview", [sys.executable, "-c", "print('ran')"],
        root=ROOT, evidence_dir=evidence, build_id="local",
    )
    outside = tmp_path / "outside"
    evidence.rename(outside)
    evidence.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="evidence directory|symlink"):
        load_receipts(evidence)


def test_timing_summary_rejects_linked_receipt(tmp_path, capsys):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(
        '{"gate":"tests","status":"pass",'
        '"started_at":"2026-09-25T00:00:00Z",'
        '"ended_at":"2026-09-25T00:00:01Z"}'
    )
    (evidence / "tests.receipt.json").symlink_to(outside)

    with pytest.raises(RuntimeError, match="safely read|symlink"):
        print_summary(evidence)
    assert "tests: pass" not in capsys.readouterr().out
