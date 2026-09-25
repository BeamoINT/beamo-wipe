"""Malformed progress values must not become plausible wipe progress."""

import math

import pytest

from beamo_wipe.nwipe_runner import NwipeRunner


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="positive-infinity"),
        pytest.param(-math.inf, id="negative-infinity"),
        pytest.param(10**1000, id="huge-integer"),
    ],
)
def test_nonfinite_progress_is_ignored_while_engine_is_running(value):
    runner = NwipeRunner()
    runner._proc = object()
    runner.progress = 12.5

    runner._update_progress(value)

    assert runner.progress == 12.5
