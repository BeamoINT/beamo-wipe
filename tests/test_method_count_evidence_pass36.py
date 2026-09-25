"""A successful result cannot contradict its pinned method's pass counts."""

from copy import deepcopy

import pytest

from beamo_wipe.outcomes import present_evidence
from test_result_presentations import CASES, case_evidence


@pytest.mark.parametrize(
    "field,value",
    [
        ("overwrite_passes", 2),
        ("verification_passes", 2),
        ("overwrite_passes", True),
        ("verification_passes", True),
    ],
)
def test_changed_method_pass_count_cannot_keep_verified_result(field, value):
    _, evidence, _ = case_evidence(CASES[0])
    assert present_evidence(evidence).code == "verified"
    changed = deepcopy(evidence)
    changed["method"][field] = value

    assert present_evidence(changed).code == "indeterminate"
