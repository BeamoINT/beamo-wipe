# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #91: explain unavailable erase-time estimates. Fake lines only."""

from beamo_wipe import lang
from beamo_wipe.models import MethodId
from beamo_wipe.progress import ProgressTiming, ProgressView, observe
from test_operation_sequence import _working
from test_progress_timing import Clock, sample, stable


def test_early_progress_estimates_after_more():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = timing.view(sample(10, eta=400), False)
    clock.advance(5)
    view = timing.view(sample(11, eta=390), False)
    assert view.remaining is None
    assert view.estimate_state == "Estimating after more progress."
    assert "Estimating after more progress." in view.timing_text


def test_short_span_stays_estimating():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = None
    for n in range(6):
        view = timing.view(sample(10 + n, eta=400 - n * 10), True)
        clock.advance(3)
    assert view.remaining is None
    assert view.estimate_state == "Estimating after more progress."


def test_non_final_operation_waits_last_step():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = None
    for n in range(6):
        view = timing.view(sample(10 + n, eta=400 - n * 10), False)
        clock.advance(5)
    assert view.remaining is None
    assert view.estimate_state == "Estimate unavailable until the last step."


def test_retrying_explains_missing_estimate():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = None
    for n in range(8):
        view = timing.view(
            sample(30 + n, eta=300 - n * 10, phase="retrying"), True
        )
        clock.advance(5)
    assert view.remaining is None
    assert view.estimate_state == (
        "Estimate unavailable while the drive is retrying."
    )


def test_stall_pauses_estimate():
    clock, timing, _view = stable()
    clock.advance(30)
    view = timing.view(sample(15, eta=425), True)
    assert view.stale_for is not None
    assert view.remaining is None
    assert view.estimate_state == "No estimate until progress resumes."


def test_missing_engine_eta_state():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = None
    for n in range(6):
        record = f"/dev/fake: {10 + n:.2f}%, round 1 of 1, pass 1 of 1\n"
        obs = observe(record, "/dev/fake")
        assert obs is not None and obs.engine_eta is None
        view = timing.view(obs, True)
        clock.advance(5)
    assert view.remaining is None
    assert view.estimate_state == (
        "Estimate unavailable: no time information from the drive."
    )


def test_unsteady_rate_disagrees():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = None
    for pct in (10, 11, 30, 31, 32, 33):
        view = timing.view(sample(pct, eta=400 - pct * 5), True)
        clock.advance(5)
    assert view.remaining is None
    assert view.estimate_state == (
        "Estimate unavailable: progress reports disagree."
    )


def test_engine_eta_disagreement_state():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = None
    for n in range(6):
        view = timing.view(sample(10 + n, eta=5), True)
        clock.advance(5)
    assert view.remaining is None
    assert view.estimate_state == (
        "Estimate unavailable: progress reports disagree."
    )


def test_final_hundred_waits_for_result():
    clock, timing, _view = stable()
    clock.advance(5)
    view = timing.view(sample(100, eta=5), True)
    assert view.remaining is None
    assert view.estimate_state == "Last step finished. Waiting for the result."


def test_midplan_hundred_waits_for_last_step():
    clock, timing, _view = stable()
    clock.advance(5)
    view = timing.view(sample(100, eta=5), False)
    assert view.remaining is None
    assert view.estimate_state == "Estimate unavailable until the last step."


def test_syncing_explains_missing_estimate():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = None
    for n in range(8):
        view = timing.view(
            sample(30 + n, eta=300 - n * 10, phase="syncing"), True
        )
        clock.advance(5)
    assert view.remaining is None
    assert view.estimate_state == (
        "Estimate unavailable while the drive is syncing."
    )


def test_regression_returns_to_estimating():
    clock, timing, _view = stable()
    clock.advance(5)
    view = timing.view(sample(5, eta=400), True)
    assert view.remaining is None
    assert view.estimate_state == "Estimating after more progress."


def test_resumed_progress_rebuilds_then_restores_estimate():
    clock, timing, _view = stable()
    clock.advance(30)
    view = timing.view(sample(15, eta=425), True)
    assert view.estimate_state == "No estimate until progress resumes."
    clock.advance(5)
    view = timing.view(sample(20, eta=400), True)
    clock.advance(5)
    view = timing.view(sample(21, eta=390), True)
    assert view.remaining is None
    assert view.estimate_state == "Estimating after more progress."
    for n in range(2, 9):
        clock.advance(5)
        view = timing.view(sample(20 + n, eta=400 - n * 10), True)
    assert view.remaining is not None
    assert view.estimate_state == ""
    assert "about" in view.timing_text


def test_valid_estimate_shows_no_state():
    _clock, _timing, view = stable()
    assert view.remaining is not None
    assert view.estimate_state == ""
    assert "about" in view.timing_text
    assert "Estimating after" not in view.timing_text


def test_repeated_views_do_not_flap_state():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    obs = sample(10, eta=400)
    first = timing.view(obs, False).timing_text
    second = timing.view(obs, False).timing_text
    assert first == second
    assert "Estimating after more progress." in first


def test_hand_built_views_carry_no_state():
    assert ProgressView("Writing", 25, 120).estimate_state == ""


def test_working_fresh_shows_estimating():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = None
    text = wiz.progress_view.status_text
    assert "Estimating after more progress." in text


def test_working_retry_shows_retry_state():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, phase="retrying", counters="round 1 of 1, pass 2 of 3"
    )
    assert (
        "Estimate unavailable while the drive is retrying."
        in wiz.progress_view.status_text
    )


def test_finalizing_shows_no_estimator_state():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        100, phase="verifying", counters="round 1 of 1, pass 3 of 3"
    )
    wiz.runner.finalizing = True
    text = wiz.progress_view.status_text
    assert "Determining the result" in text
    for state in (
        "Estimating after more progress.",
        "Estimate unavailable",
        "No estimate until progress resumes.",
    ):
        assert state not in text


def test_stopping_shows_no_estimator_state():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    assert wiz._claim_stop()
    text = wiz.progress_view.status_text
    assert "Stopping" in text
    assert "Estimating after more progress." not in text
    assert "Estimate unavailable" not in text


def test_french_and_german_states():
    lang.set_language("fr")
    try:
        wiz, _clock = _working(MethodId.EXTRA)
        wiz.runner.progress_observation = None
        assert "plus de progression" in wiz.progress_view.status_text
        wiz.runner.progress_observation = sample(
            40, phase="retrying", counters="round 1 of 1, pass 2 of 3"
        )
        assert "le disque réessaie" in wiz.progress_view.status_text
    finally:
        lang.set_language("en")
    lang.set_language("de")
    try:
        wiz, _clock = _working(MethodId.EXTRA)
        wiz.runner.progress_observation = None
        assert "weiterem Fortschritt" in wiz.progress_view.status_text
        wiz.runner.progress_observation = sample(
            40, phase="retrying", counters="round 1 of 1, pass 2 of 3"
        )
        assert (
            "während das Laufwerk gerade wiederholt"
            in wiz.progress_view.status_text
        )
    finally:
        lang.set_language("en")


def test_preview_mid_segment_waits_and_late_segment_estimates():
    wiz, clock = _working(MethodId.EXTRA)
    wiz.runner.synthesize_stages = True
    wiz.runner.duration_s = 100.0
    wiz.runner._started = 0.0
    text = ""
    for tick in range(26, 47, 4):
        clock.mono = float(tick)
        clock.wall = 1000.0 + float(tick)
        wiz.tick()
        text = wiz.progress_view.status_text
    assert "Step 2 of 4" in text
    assert "Estimate unavailable until the last step." in text
    for tick in range(76, 97, 4):
        clock.mono = float(tick)
        clock.wall = 1000.0 + float(tick)
        wiz.tick()
        text = wiz.progress_view.status_text
    assert "Step 4 of 4" in text
    assert "Estimated time remaining: less than 1 minute" in text
    assert "Estimate unavailable" not in text
    assert "Estimating after more progress." not in text
