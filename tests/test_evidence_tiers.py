# SPDX-License-Identifier: GPL-3.0-or-later
"""docs/evidence-tiers.md stays honest and its receipt links resolve."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "evidence-tiers.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_tier_definitions_and_limits_are_stated():
    text = _text()
    for heading in (
        "Tier 1",
        "Tier 2",
        "Tier 3",
        "Receipt schema",
        "Revalidation triggers",
    ):
        assert heading in text
    assert "never proves" in text
    assert "never be presented as" in text
    assert "not a certificate" in text


def test_unverified_gaps_are_explicit():
    text = _text()
    assert "UNVERIFIED" in text
    assert "Claims that remain unverified" in text


def test_accessibility_matrix_reconfirmation_is_versioned_and_scoped():
    text = (ROOT / "docs" / "accessibility-lowres-matrix.md").read_text(encoding="utf-8")
    assert "0.2.7" in text
    assert "evidence-tiers" in text
    assert "Tier 1" in text


def test_tier_index_covers_the_full_boot_media_range():
    text = _text()
    assert "BM-01" in text and "BM-17" in text


def test_tier_index_states_only_what_the_receipt_shows():
    text = _text()
    assert "zeroed the guest target prefill" in text


def test_compatibility_matrix_evidence_snapshot_is_qualified():
    text = (ROOT / "docs" / "compatibility-matrix.md").read_text(encoding="utf-8")
    assert "historical snapshot" in text
    assert "docs/ci.md" in text


def test_receipt_links_exist():
    text = _text()
    targets = sorted(
        {m.group(0)[1:-1] for m in re.finditer(r"\(evidence/[^)]+\)", text)}
    )
    assert targets, "evidence-tiers.md links no evidence receipts"
    for target in targets:
        assert (ROOT / "docs" / target).exists(), f"receipt link is dead: {target}"
