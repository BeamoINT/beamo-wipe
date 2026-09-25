# SPDX-License-Identifier: GPL-3.0-or-later
"""Redacted text must not reveal identifier variants from report fields."""

from __future__ import annotations

import copy

from beamo_wipe.result_summary import build_result_summary
from test_result_presentations import CASES, case_evidence


def test_redacted_summary_scrubs_case_variants_and_boot_path():
    _, original, _ = case_evidence(CASES[0])
    evidence = copy.deepcopy(original)
    evidence["device"]["serial"] = "CASE-SENSITIVE-SERIAL-ZX9Q"
    evidence["boot_device"] = "/dev/PrivateBootPass8"
    evidence["warnings"] = [
        "Another read of case-sensitive-serial-zx9q failed",
        "Boot path /DEV/PRIVATEBOOTPASS8 was present",
    ]
    summary = build_result_summary(evidence, redacted=True).casefold()
    assert "case-sensitive-serial-zx9q" not in summary
    assert "/dev/privatebootpass8" not in summary
    assert "withheld" in summary
