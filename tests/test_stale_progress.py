"""#92: stale progress must explain itself with safe next steps.

Fake engine output and controllable clocks only; no subprocess or disk I/O.
"""

import pytest

from beamo_wipe import copy as copy_strings
from beamo_wipe import lang
from beamo_wipe import progress as progress_strings
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.progress import (
    FIRST_UPDATE_GRACE_S,
    STALE_MEANING,
    STALE_NEXT,
    ProgressTiming,
    ProgressView,
    STALE_PROGRESS_S,
    plan_stages,
    silence_text,
    stale_block,
)
from test_progress_timing import Clock, bind_wizard_timing, sample, stable

UNSAFE_EN = [
    "restart",
    "reboot",
    "unplug",
    "replug",
    "start over",
    "try again",
    "retry",
    "shut down",
    "power off",
    "force",
    "kill",
]
UNSAFE_FR = [
    "redémarr",
    "reboot",
    "débranch",
    "rebranch",
    "recommenc",
    "réessay",
    "forcer",
]
UNSAFE_DE = [
    "neustart",
    "neu starten",
    "abziehen",
    "einstecken",
    "von vorn",
    "erneut",
    "erzwing",
]


def stale_view():
    clock, timing, _ = stable()
    clock.advance(STALE_PROGRESS_S + 1)
    return clock, timing, timing.view(timing.last, True)


def test_stale_view_shows_duration_meaning_and_next_steps_in_order():
    _, _, view = stale_view()
    assert view.stale_for is not None
    text = view.status_text
    first = silence_text(view.stale_for)
    assert first
    i, j, k = text.index(first), text.index(STALE_MEANING), text.index(STALE_NEXT)
    assert i < j < k
    assert text.count(first) == 1
    assert text.count(STALE_MEANING) == 1
    assert text.count(STALE_NEXT) == 1


def test_stale_block_is_empty_when_fresh():
    assert stale_block(None) == ""
    _, _, view = stable()
    assert view.stale_for is None
    assert STALE_MEANING not in view.status_text
    assert STALE_NEXT not in view.status_text
    assert "No new progress update" not in view.status_text


def test_first_update_grace_boundary():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    clock.advance(FIRST_UPDATE_GRACE_S - 0.1)
    fresh = timing.view(None, False)
    assert fresh.stale_for is None
    assert stale_block(fresh.stale_for) == ""
    clock.advance(0.1)
    late = timing.view(None, False)
    assert late.stale_for == pytest.approx(FIRST_UPDATE_GRACE_S)
    block = stale_block(late.stale_for)
    assert STALE_MEANING in block
    assert STALE_NEXT in block


def test_data_gap_boundary():
    clock, timing, _ = stable()
    clock.advance(STALE_PROGRESS_S)
    fresh = timing.view(timing.last, True)
    assert fresh.stale_for is None
    assert stale_block(fresh.stale_for) == ""
    clock.advance(0.1)
    view = timing.view(timing.last, True)
    assert view.stale_for == pytest.approx(STALE_PROGRESS_S + 0.1)
    assert view.percent_is_old
    assert STALE_MEANING in view.status_text
    assert STALE_NEXT in view.status_text


def test_resumed_output_clears_the_whole_stale_block():
    clock, timing, _ = stable()
    clock.advance(STALE_PROGRESS_S + 1)
    assert STALE_MEANING in timing.view(timing.last, True).status_text
    clock.advance(2)
    fresh = timing.view(sample(16, eta=420), True)
    assert fresh.stale_for is None
    assert STALE_MEANING not in fresh.status_text
    assert STALE_NEXT not in fresh.status_text


def test_backward_clock_shows_no_staleness_claim():
    clock, timing, _ = stable()
    clock.advance(STALE_PROGRESS_S + 1)
    assert timing.view(timing.last, True).stale_for is not None
    clock.mono -= 5  # operator changed the clock; time cannot be trusted
    broken = timing.view(timing.last, True)
    assert timing.invalid_clock
    assert broken.stale_for is None
    assert stale_block(broken.stale_for) == ""
    assert STALE_MEANING not in broken.status_text
    assert STALE_NEXT not in broken.status_text
    assert "No new progress update" not in broken.status_text


def test_stale_retry_keeps_both_the_block_and_the_retry_note():
    from beamo_wipe.progress import PHASE_NOTE_RETRYING

    stages = plan_stages(1, True)
    view = ProgressView(
        "Retrying",
        40.0,
        120.0,
        None,
        stale_for=30.0,
        percent_is_old=True,
        stages=stages,
        position=1,
        step_percent=40.0,
    )
    text = view.status_text
    assert PHASE_NOTE_RETRYING in text
    assert STALE_MEANING in text
    assert STALE_NEXT in text


def test_stale_block_never_recommends_an_unsafe_restart():
    _, _, view = stale_view()
    block = stale_block(view.stale_for)
    lowered = block.lower()
    for token in UNSAFE_EN:
        assert token not in lowered, token
    assert "USB" in block
    assert "wall power" in block
    assert "Do not turn off" in block
    assert copy_strings.STOP_ASK in block


@pytest.mark.parametrize(
    "code,unsafe,usb,power,off",
    [
        ("fr", UNSAFE_FR, "USB", "secteur", "N’éteignez pas"),
        ("de", UNSAFE_DE, "USB", "Netzteil", "nicht aus"),
    ],
)
def test_stale_block_is_translated_and_safe(code, unsafe, usb, power, off):
    try:
        lang.set_language(code)
        meaning = progress_strings.STALE_MEANING
        nxt = progress_strings.STALE_NEXT
        assert meaning and nxt
        _, _, view = stale_view()
        block = stale_block(view.stale_for)
        lowered = block.lower()
        for token in unsafe:
            assert token not in lowered, token
        assert usb in block
        assert power in block
        assert off in block
        assert copy_strings.STOP_ASK in block
        assert "No new progress update" not in block
        assert meaning in block
        assert nxt in block
        assert meaning in view.status_text
        assert nxt in view.status_text
    finally:
        lang.set_language("en")


def test_stale_messaging_is_bounded_across_repeated_renders():
    clock, timing, _ = stable()
    clock.advance(STALE_PROGRESS_S + 1)
    for _ in range(50):
        view = timing.view(timing.last, True)
        assert view.stale_for is not None
        text = view.status_text
        assert text.count(STALE_MEANING) == 1
        assert text.count(STALE_NEXT) == 1
        assert text.count("No new progress update for ") == 1
        clock.advance(1)


def test_stopping_finalizing_and_done_show_no_stale_block(monkeypatch, tmp_path):
    from beamo_wipe.demo import make_demo_wizard
    from test_wizard_flow import _drive_to_working

    clock = Clock()
    clock.add = clock.advance
    w = make_demo_wizard()
    w.preview = False
    w._clock = clock
    w.runner._clock = clock
    w.runner.duration_s = 1000
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    _drive_to_working(w, clock)
    bind_wizard_timing(w, clock)
    w.runner.progress = 40
    w.runner.progress_observation = sample(40)
    assert w.progress_view.stale_for is None
    clock.advance(30)
    assert STALE_MEANING in w.progress_view.status_text
    assert w._claim_stop()
    stopping = w.progress_view
    assert stopping.phase == "Stopping"
    assert STALE_MEANING not in stopping.status_text
    assert STALE_NEXT not in stopping.status_text
    w.screen = Screen.WORKING
    w.runner.finalizing = True
    finishing = w.progress_view
    assert finishing.phase == "Finalizing"
    assert STALE_MEANING not in finishing.status_text
    assert STALE_NEXT not in finishing.status_text
    result = WipeResult(False, 1, "nwipe exited 1", w._wipe_request.logfile)
    w._finish(result)
    done = w.progress_view
    assert STALE_MEANING not in done.status_text
    assert STALE_NEXT not in done.status_text
    assert "No new progress update" not in done.status_text
