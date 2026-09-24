"""Malformed metadata must not derail a conservative evidence record."""

from __future__ import annotations

import pytest

from beamo_wipe.evidence import wall_timestamps


@pytest.mark.parametrize("provenance", [[], {}, set()])
def test_unhashable_clock_provenance_is_unavailable(provenance):
    stamps = wall_timestamps("2026-09-24T12:00:00Z", "2026-09-24T12:01:00Z", provenance)
    assert stamps == {
        "started_at_wall": "",
        "ended_at_wall": "",
        "wall_confidence": "unavailable",
        "wall_provenance": "unavailable",
    }
