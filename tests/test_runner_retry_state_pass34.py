"""A rejected retry cannot expose a previous run's terminal result."""

import time

import pytest

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.safety import SafetyError


def test_rejected_retry_does_not_return_previous_result(tmp_path, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    request = WipeRequest(
        "/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(tmp_path / "nwipe.log")
    )
    runner = NwipeRunner(binary="/usr/bin/true")
    runner.start(request)
    for _ in range(100):
        previous = runner.poll(request)
        if previous is not None:
            break
        time.sleep(0.01)
    assert previous is not None
    assert runner._proc is None

    runner.binary = "missing-engine"
    with pytest.raises(SafetyError):
        runner.start(request)

    assert runner.start_not_spawned()
    assert runner.poll(request) is None
