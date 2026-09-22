# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #88: complete erase operation sequence. Fake engine lines only."""

import pytest

from beamo_wipe import lang
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.methods import METHODS
from beamo_wipe.models import MethodId, Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.progress import (
    locate_stage,
    plan_stages,
    sequence_text,
    stage_label,
    step_text,
)
from test_progress_timing import Clock, bind_wizard_timing, sample


def _working(method=MethodId.EXTRA):
    clock = Clock()
    clock.add = clock.advance
    wiz = make_demo_wizard()
    wiz.preview = False
    wiz._clock = clock
    wiz.runner._clock = clock
    wiz.runner.duration_s = 1000
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.set_method(method)
    wiz.continue_method()
    clock.add(5.0)
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    bind_wizard_timing(wiz, clock)
    return wiz, clock


def test_plan_derives_from_method_spec():
    everyday = plan_stages(1, True)
    assert [stage_label(s) for s in everyday] == [
        "Overwrite 1 of 1",
        "Read-back verification",
    ]
    extra = plan_stages(3, True)
    assert [stage_label(s) for s in extra] == [
        "Overwrite 1 of 3",
        "Overwrite 2 of 3",
        "Overwrite 3 of 3",
        "Read-back verification",
    ]
    quick = plan_stages(1, False)
    assert [stage_label(s) for s in quick] == ["Overwrite 1 of 1"]


def test_plan_matches_shipped_methods():
    assert (
        len(plan_stages(METHODS[MethodId.EVERYDAY].overwrite_passes, True)) == 2
    )
    spec = METHODS[MethodId.EXTRA]
    assert (
        len(
            plan_stages(
                spec.overwrite_passes, bool(spec.verification_passes)
            )
        )
        == 4
    )
    spec = METHODS[MethodId.QUICK_ZERO]
    assert spec.verification_passes == 0
    assert (
        len(
            plan_stages(
                spec.overwrite_passes, bool(spec.verification_passes)
            )
        )
        == 1
    )


def test_locate_overwrite_from_pass_counters():
    stages = plan_stages(3, True)
    obs = sample(40, counters="round 1 of 1, pass 2 of 3")
    assert obs.phase == "Writing"
    position, mismatch = locate_stage(stages, obs)
    assert (position, mismatch) == (1, False)
    assert step_text(stages, position, mismatch) == (
        "Step 2 of 4: Overwrite 2 of 3"
    )


def test_locate_verify_from_phase():
    stages = plan_stages(3, True)
    obs = sample(
        90,
        phase="verifying",
        counters="round 1 of 1, pass 3 of 3",
    )
    position, mismatch = locate_stage(stages, obs)
    assert (position, mismatch) == (3, False)
    assert step_text(stages, position, mismatch) == (
        "Step 4 of 4: Read-back verification"
    )


def test_verify_under_no_verify_plan_is_mismatch():
    stages = plan_stages(1, False)
    obs = sample(
        90, phase="verifying", counters="round 1 of 1, pass 1 of 1"
    )
    position, mismatch = locate_stage(stages, obs)
    assert (position, mismatch) == (None, True)
    assert step_text(stages, position, mismatch) == (
        "Engine step does not match the planned method"
    )


def test_counter_plan_disagreement_is_mismatch():
    stages = plan_stages(1, True)
    obs = sample(40, counters="round 1 of 1, pass 2 of 3")
    position, mismatch = locate_stage(stages, obs)
    assert (position, mismatch) == (None, True)


def test_unexpected_round_is_mismatch():
    stages = plan_stages(1, True)
    obs = sample(40, counters="round 2 of 2, pass 1 of 1")
    position, mismatch = locate_stage(stages, obs)
    assert (position, mismatch) == (None, True)


def test_missing_counters_is_unknown_not_mismatch():
    stages = plan_stages(3, True)
    obs = sample(10, counters="round 1 of 1")
    assert obs.counters[2:] == (0, 0)
    position, mismatch = locate_stage(stages, obs)
    assert (position, mismatch) == (None, False)
    assert step_text(stages, position, mismatch) == (
        "Current step not reported yet"
    )


def test_no_observation_is_unknown():
    stages = plan_stages(3, True)
    position, mismatch = locate_stage(stages, None)
    assert (position, mismatch) == (None, False)


def test_retrying_keeps_located_stage():
    stages = plan_stages(3, True)
    obs = sample(
        40, phase="retrying", counters="round 1 of 1, pass 2 of 3"
    )
    assert obs.phase == "Retrying"
    position, mismatch = locate_stage(stages, obs)
    assert (position, mismatch) == (1, False)


def test_last_pass_retry_is_not_labeled_as_the_last_overwrite():
    """nwipe keeps pass N of N for both the last write and its read-back."""
    stages = plan_stages(3, True)
    obs = sample(40, phase="retrying", counters="round 1 of 1, pass 3 of 3")
    position, mismatch = locate_stage(stages, obs)
    assert (position, mismatch) == (None, False)
    assert step_text(stages, position, mismatch) == "Current step not reported yet"


def test_verify_retry_stays_on_read_back_after_that_phase_was_seen():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        90, phase="verifying", counters="round 1 of 1, pass 3 of 3"
    )
    assert "Step 4 of 4: Read-back verification" in wiz.progress_view.status_text
    wiz.runner.progress_observation = sample(
        90, phase="retrying", counters="round 1 of 1, pass 3 of 3"
    )
    text = wiz.progress_view.status_text
    assert "Retrying" in text
    assert "Step 4 of 4: Read-back verification" in text
    assert "Overwrite 3 of 3 (now)" not in text


def test_sequence_marks_done_current_and_todo():
    stages = plan_stages(3, True)
    assert sequence_text(stages, 1).splitlines() == [
        "Overwrite 1 of 3 (done)",
        "Overwrite 2 of 3 (now)",
        "Overwrite 3 of 3",
        "Read-back verification",
    ]
    assert sequence_text(stages, None).splitlines() == [
        "Overwrite 1 of 3",
        "Overwrite 2 of 3",
        "Overwrite 3 of 3",
        "Read-back verification",
    ]


def test_working_status_shows_step_and_full_sequence():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    text = wiz.progress_view.status_text
    assert "Step 2 of 4: Overwrite 2 of 3" in text
    assert "Overwrite 1 of 3 (done)" in text
    assert "Overwrite 2 of 3 (now)" in text
    assert "Overwrite 3 of 3\n" in text
    assert "Read-back verification" in text


def test_working_status_unknown_before_first_sample():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = None
    text = wiz.progress_view.status_text
    assert "Current step not reported yet" in text
    assert "Overwrite 1 of 3" in text
    assert "(now)" not in text


def test_single_pass_no_verify_sequence():
    wiz, _clock = _working(MethodId.QUICK_ZERO)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 1 of 1"
    )
    text = wiz.progress_view.status_text
    assert "Step 1 of 1: Overwrite 1 of 1" in text
    assert "verification" not in text.lower()


def test_stopping_keeps_last_located_stage():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    assert wiz._claim_stop()
    text = wiz.progress_view.status_text
    assert "Stopping" in text
    assert "Step 2 of 4: Overwrite 2 of 3" in text


def test_failed_run_claims_no_live_stage():
    from beamo_wipe.models import WipeResult

    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    result = WipeResult(False, 1, "nwipe exited 1", wiz._wipe_request.logfile)
    wiz._finish(result)
    assert wiz.screen == Screen.DONE
    for surface in (
        wiz.elapsed_text,
        wiz.report_view.message,
        wiz.report_view.status,
    ):
        assert "(now)" not in surface
        assert "Step " not in surface


def test_stage_transition_changes_announced_text():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 1 of 3"
    )
    before = wiz.progress_view.status_text
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    after = wiz.progress_view.status_text
    assert "Step 1 of 4" in before
    assert "Step 2 of 4" in after
    assert before != after


def test_french_and_german_render_sequence():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    lang.set_language("fr")
    try:
        text = wiz.progress_view.status_text
        assert "Overwrite" not in text
        assert "Étape 2 sur 4" in text
    finally:
        lang.set_language("en")
    lang.set_language("de")
    try:
        text = wiz.progress_view.status_text
        assert "Overwrite" not in text
        assert "Schritt 2 von 4" in text
    finally:
        lang.set_language("en")


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _dry_request(method=MethodId.EXTRA):
    from test_nwipe_runner import _request

    return _request(method)


def test_dry_run_synthesis_moves_through_plan():
    clock = _FakeClock()
    runner = DryRunRunner(
        duration_s=100.0, clock=clock, synthesize_stages=True
    )
    runner.start(_dry_request())
    seen = []
    for tick in range(0, 100, 5):
        clock.now = float(tick)
        assert runner.poll(_dry_request()) is None
        obs = runner.progress_observation
        assert obs is not None
        stages = plan_stages(3, True)
        position, mismatch = locate_stage(stages, obs)
        assert mismatch is False
        seen.append(position)
    assert seen[0] == 0
    assert seen[-1] == 3
    assert sorted(set(seen)) == [0, 1, 2, 3]


def test_interrupt_after_engine_start_stays_on_the_running_wipe():
    from beamo_wipe.ui import console_wizard

    clock = {"t": 0.0}

    def now():
        return clock["t"]

    wiz = make_demo_wizard()
    wiz.dry_run = False
    wiz.preview = False
    wiz._clock = now
    runner = DryRunRunner(duration_s=30.0, clock=now)
    original = runner.start

    def start(request):
        original(request)
        raise KeyboardInterrupt

    runner.start = start
    wiz.runner = runner
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    clock["t"] = 100.0
    state = {"n": 0}
    original_body = console_wizard._plain_loop_body

    def body(wizard):
        state["n"] += 1
        if state["n"] == 1:
            wizard.confirm_erase()
        return 7

    console_wizard._plain_loop_body = body
    try:
        code = console_wizard._plain_loop(wiz)
    finally:
        console_wizard._plain_loop_body = original_body
    assert code == 7
    assert wiz.screen == Screen.WORKING
    assert wiz._wipe_request is not None
    assert runner._started is not None
    assert wiz.stop_confirmation is not None
    assert wiz.wants_shutdown is False
    running = wiz._wipe_request
    wiz.shutdown()
    assert wiz.wants_shutdown is False
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert wiz._wipe_request is running
    assert runner._request is running


def test_dry_run_default_stays_silent():
    runner = DryRunRunner(duration_s=100.0, clock=_FakeClock())
    runner.start(_dry_request())
    assert runner.progress_observation is None


def test_preview_ticks_move_through_stages():
    wiz, clock = _working(MethodId.EXTRA)
    wiz.runner.synthesize_stages = True
    wiz.runner.duration_s = 100.0
    wiz.runner._started = 0.0
    seen = []
    for tick in (10, 30, 60, 90):
        clock.mono = float(tick)
        wiz.tick()
        assert wiz.screen == Screen.WORKING
        line = next(
            line
            for line in wiz.progress_view.status_text.splitlines()
            if line.startswith("Step")
        )
        seen.append(line)
    assert seen == [
        "Step 1 of 4: Overwrite 1 of 3 (10% of this step)",
        "Step 2 of 4: Overwrite 2 of 3 (30% of this step)",
        "Step 3 of 4: Overwrite 3 of 3 (60% of this step)",
        "Step 4 of 4: Read-back verification (90% of this step)",
    ]


def test_gallery_payload_carries_stage_plan():
    import json

    from beamo_wipe.gallery import gallery_html

    html = gallery_html("en")
    assert json.dumps(
        [
            "Overwrite 1 of 3",
            "Overwrite 2 of 3",
            "Overwrite 3 of 3",
            "Read-back verification",
        ]
    ) in html
    assert json.dumps(["Overwrite 1 of 1"]) in html
