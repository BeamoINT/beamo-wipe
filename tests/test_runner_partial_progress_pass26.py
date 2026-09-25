"""Incomplete live log appends cannot advance the owner-facing percentage."""

from beamo_wipe.nwipe_runner import NwipeRunner


def test_partial_live_progress_line_does_not_advance_percentage(monkeypatch):
    runner = NwipeRunner()
    text = "/dev/vda: 20.00%, round 1 of 1, pass 1 of 1\n"
    monkeypatch.setattr(runner, "_read_log_tail", lambda *_args: text)

    runner._refresh_progress("fake-log", "/dev/vda")
    assert runner.progress == 20
    assert runner.progress_observation is not None

    text = "/dev/vda: 80.00%, round 1 of 1, pass 1 of 1"
    runner._refresh_progress("fake-log", "/dev/vda")

    assert runner.progress_observation is None
    assert runner.progress == 20
