"""Pinned method copy must agree with a successful saved result."""

from copy import deepcopy

import pytest

from beamo_wipe import lang
from beamo_wipe.outcomes import present_evidence
from beamo_wipe.privacy import make_sharing_copy
from beamo_wipe.result_summary import build_result_summary
from test_result_presentations import CASES, case_evidence


@pytest.mark.parametrize("field", ["title", "operation_summary", "description", "docs_name"])
def test_forged_method_copy_cannot_keep_green_result_or_report(field):
    _, evidence, _ = case_evidence(CASES[0])
    assert present_evidence(evidence).code == "verified"
    changed = deepcopy(evidence)
    changed["method"][field] = "Certified 100-pass purge"

    assert present_evidence(changed).code == "indeterminate"
    assert "Certified 100-pass purge" not in build_result_summary(changed)


@pytest.mark.parametrize("language", ["fr", "de"])
def test_saved_method_copy_is_checked_in_its_own_language(language):
    original = lang.current()
    try:
        lang.set_language(language)
        _, evidence, _ = case_evidence(CASES[0])
        evidence["locale"]["language"] = language
        assert present_evidence(evidence).code == "verified"
        lang.set_language("en")
        assert present_evidence(evidence).code == "verified"
    finally:
        lang.set_language(original)


def test_sharing_method_redaction_is_retained_in_readable_report():
    _, evidence, _ = case_evidence(CASES[0])
    evidence["device"]["serial"] = "overwrite"
    sharing = make_sharing_copy(evidence)
    assert present_evidence(sharing).code == "verified"

    summary = build_result_summary(sharing)
    assert "One withheld" in summary
    assert "One overwrite" not in summary

    forged = deepcopy(sharing)
    forged["method"]["operation_summary"] = "Certified 100-pass purge"
    assert present_evidence(forged).code == "indeterminate"
    assert "Certified 100-pass purge" not in build_result_summary(forged)
