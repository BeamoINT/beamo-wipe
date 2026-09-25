"""Read-back stage labels must agree with the selected method's pass plan."""

import pytest

from beamo_wipe.progress import Observation, locate_stage, plan_stages


@pytest.mark.parametrize(
    "counters,expected",
    [
        ((1, 1, 1, 1), (None, True)),
        ((1, 1, 1, 3), (None, True)),
        ((1, 1, 0, 0), (None, False)),
        ((1, 1, 3, 3), (3, False)),
    ],
)
def test_verifying_stage_requires_matching_final_pass(counters, expected):
    observation = Observation(
        record="fake-progress", percent=40.0, phase="Verifying",
        counters=counters, engine_eta=200, quantum=0.01,
    )
    assert locate_stage(plan_stages(3, True), observation) == expected
