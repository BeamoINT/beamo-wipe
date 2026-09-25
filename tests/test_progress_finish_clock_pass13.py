"""A contradictory terminal clock cannot become a claimed elapsed time."""

import pytest

from beamo_wipe.progress import ProgressTiming


@pytest.mark.parametrize("ended", [90.0, float("nan"), float("inf")])
def test_invalid_terminal_clock_leaves_elapsed_unavailable(ended):
    timing = ProgressTiming(lambda: 100.0, lambda: 100.0)
    timing.start(100.0)

    timing.finish(ended)

    assert timing.view(None, False).elapsed is None


def test_terminal_clock_earlier_than_last_observation_is_unavailable():
    current = [100.0]
    timing = ProgressTiming(lambda: current[0], lambda: current[0])
    timing.start(100.0)
    current[0] = 120.0
    timing.view(None, False)

    timing.finish(110.0)

    assert timing.view(None, False).elapsed is None
