"""Preview progress stays in range after an anomalous clock reading."""

import math

import pytest

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import DryRunRunner


@pytest.mark.parametrize("later", [9.0, math.nan, math.inf])
def test_preview_clock_regression_never_displays_negative_progress(tmp_path, monkeypatch, later):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    now = [10.0]
    runner = DryRunRunner(clock=lambda: now[0], synthesize_stages=True)
    request = WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(tmp_path / "nwipe.log"))
    runner.start(request)

    now[0] = later
    assert runner.poll(request) is None
    assert runner.progress == 0.0
    assert runner.progress_observation is not None
    assert runner.progress_observation.percent == 0.0
