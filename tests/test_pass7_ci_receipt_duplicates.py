"""Measured CI receipts must have one unambiguous gate status."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from beamo_wipe.ci_evidence import load_receipts, run_gate


ROOT = Path(__file__).resolve().parents[1]


def test_duplicate_gate_status_cannot_pass_receipt_load(tmp_path):
    receipt = run_gate(
        "preview",
        [sys.executable, "-c", "raise SystemExit(0)"],
        root=ROOT,
        evidence_dir=tmp_path,
        build_id="local",
    )
    assert load_receipts(tmp_path) == [receipt]
    path = tmp_path / "preview.receipt.json"
    raw = path.read_text().replace(
        '"status": "pass"', '"status": "fail", "status": "pass"', 1
    )
    assert raw != path.read_text()
    path.write_text(raw)
    with pytest.raises(RuntimeError, match="duplicate"):
        load_receipts(tmp_path)
