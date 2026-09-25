"""A saved failure label must agree with the recorded process exit."""

from copy import deepcopy

import pytest

from beamo_wipe.outcomes import present_evidence
from test_result_presentations import CASES, case_evidence


@pytest.mark.parametrize(
    "case_name,exit_code",
    [
        ("process_failed", 0),
        ("completion_missing", 2),
    ],
)
def test_failure_reason_cannot_contradict_process_exit(case_name, exit_code):
    case = next(case for case in CASES if case[0] == case_name)
    _, valid, _ = case_evidence(case)
    changed = deepcopy(valid)
    changed["exit_evidence"]["exit_code"] = exit_code

    assert present_evidence(changed).code == "indeterminate"


def test_signal_metadata_must_agree_with_recorded_exit():
    case = next(case for case in CASES if case[0] == "process_failed")
    _, valid, _ = case_evidence(case)
    changed = deepcopy(valid)
    changed["exit_evidence"]["signal"] = 15

    assert present_evidence(changed).code == "indeterminate"
