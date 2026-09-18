# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #90: write progress must not look like final completion."""

import pytest

from beamo_wipe import lang
from beamo_wipe.models import MethodId
from beamo_wipe.nwipe_runner import DryRunRunner
from test_operation_sequence import _working
from test_progress_timing import sample


def test_step_line_carries_live_step_percent():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    assert (
        "Step 2 of 4: Overwrite 2 of 3 (40% of this step)"
        in wiz.progress_view.status_text
    )


def test_engine_100_midplan_is_step_scoped():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress = 99.9
    wiz.runner.progress_observation = sample(
        100, counters="round 1 of 1, pass 1 of 3"
    )
    text = wiz.progress_view.status_text
    assert text.startswith("99%.")
    assert "Step 1 of 4: Overwrite 1 of 3 (100% of this step)" in text
    assert "100%." not in text.splitlines()[0]


def test_stale_step_percent_marked_old():
    wiz, clock = _working(MethodId.EXTRA)
    wiz.runner.progress = 40.0
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    assert "(40% of this step)" in wiz.progress_view.status_text
    clock.advance(30)
    text = wiz.progress_view.status_text
    assert "last reported 40% of this step" in text
    assert "(40% of this step)" not in text


def test_unknown_step_shows_no_step_percent():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = None
    text = wiz.progress_view.status_text
    assert "Current step not reported yet" in text
    assert "of this step" not in text


def test_mismatch_shows_no_step_percent():
    wiz, _clock = _working(MethodId.QUICK_ZERO)
    wiz.runner.progress_observation = sample(
        90, phase="verifying", counters="round 1 of 1, pass 1 of 1"
    )
    text = wiz.progress_view.status_text
    assert "Engine step does not match the planned method" in text
    assert "of this step" not in text


def test_verify_phase_note_explains_transition():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        90, phase="verifying", counters="round 1 of 1, pass 3 of 3"
    )
    text = wiz.progress_view.status_text
    assert "Checking the last overwrite" in text
    assert "not done until the result screen" in text


def test_syncing_phase_note_warns_quiet():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        60, phase="syncing", counters="round 1 of 1, pass 2 of 3"
    )
    text = wiz.progress_view.status_text
    assert "Finishing disk writes" in text
    assert "quiet for a while" in text


def test_retrying_phase_note_keeps_going():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, phase="retrying", counters="round 1 of 1, pass 2 of 3"
    )
    text = wiz.progress_view.status_text
    assert "Retrying a step that did not finish" in text
    assert "erase continues" in text


def test_finalizing_phase_note_explains_result_wait():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        100, phase="verifying", counters="round 1 of 1, pass 3 of 3"
    )
    wiz.runner.finalizing = True
    text = wiz.progress_view.status_text
    assert "Finalizing" in text
    assert "run ended" in text
    assert "Determining the result" in text


def test_mismatch_suppresses_phase_note():
    wiz, _clock = _working(MethodId.QUICK_ZERO)
    wiz.runner.progress_observation = sample(
        90, phase="verifying", counters="round 1 of 1, pass 1 of 1"
    )
    assert "Checking the last overwrite" not in wiz.progress_view.status_text


def test_stopping_has_no_transition_note():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        40, counters="round 1 of 1, pass 2 of 3"
    )
    assert wiz._claim_stop()
    text = wiz.progress_view.status_text
    assert "Stopping" in text
    assert "Determining the result" not in text
    assert "Step 2 of 4" in text


@pytest.mark.parametrize(
    "method,counters,phase,expected",
    [
        (
            MethodId.EVERYDAY,
            "round 1 of 1, pass 1 of 1",
            "writing",
            "Step 1 of 2: Overwrite 1 of 1 (40% of this step)",
        ),
        (
            MethodId.EXTRA,
            "round 1 of 1, pass 2 of 3",
            "writing",
            "Step 2 of 4: Overwrite 2 of 3 (40% of this step)",
        ),
        (
            MethodId.QUICK_ZERO,
            "round 1 of 1, pass 1 of 1",
            "writing",
            "Step 1 of 1: Overwrite 1 of 1 (40% of this step)",
        ),
    ],
)
def test_all_methods_render_step_percent(method, counters, phase, expected):
    wiz, _clock = _working(method)
    wiz.runner.progress_observation = sample(
        40, counters=counters, phase=phase
    )
    assert expected in wiz.progress_view.status_text


def test_french_and_german_step_percent_and_notes():
    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        90, phase="verifying", counters="round 1 of 1, pass 3 of 3"
    )
    lang.set_language("fr")
    try:
        text = wiz.progress_view.status_text
        assert "de cette étape" in text
        assert "écran de résultat" in text
        assert "of this step" not in text
    finally:
        lang.set_language("en")
    lang.set_language("de")
    try:
        text = wiz.progress_view.status_text
        assert "dieses Schritts" in text
        assert "Ergebnisbildschirm" in text
        assert "of this step" not in text
    finally:
        lang.set_language("en")


def test_preview_ticks_show_step_percent():
    wiz, clock = _working(MethodId.EXTRA)
    wiz.runner.synthesize_stages = True
    wiz.runner.duration_s = 100.0
    wiz.runner._started = 0.0
    clock.mono = 30.0
    wiz.tick()
    assert "(30% of this step)" in wiz.progress_view.status_text


def test_german_transition_note_wraps_on_80x24(monkeypatch):
    from test_console_parity import _draw

    wiz, _clock = _working(MethodId.EXTRA)
    wiz.runner.progress_observation = sample(
        90, phase="verifying", counters="round 1 of 1, pass 3 of 3"
    )
    lang.set_language("de")
    try:
        _shown, packed, term = _draw(monkeypatch, wiz)
    finally:
        lang.set_language("en")
    assert "Ergebnisbildschirm" in packed
    assert "dieses Schritts" in packed
    assert all(len(line) < 80 for line in term.frames[-1].values())


def test_gallery_step_percent_template():
    import json

    from beamo_wipe.gallery import gallery_html

    html = gallery_html("en")
    assert '"stageStepPct"' in html
    assert "P.stageStepPct" in html
    assert json.dumps("({pct} of this step)")[1:-1] in html
