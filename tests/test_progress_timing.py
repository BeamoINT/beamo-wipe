"""Fake engine output and controllable clocks only; no subprocess or disk I/O."""

import pytest

from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.progress import (
    ENGINE_PROGRESS_INTERVAL_S,
    FIRST_UPDATE_GRACE_S,
    ProgressTiming,
    ProgressView,
    STALE_PROGRESS_S,
    duration,
    observe,
)


class Clock:
    def __init__(self):
        self.mono = 0.0
        self.wall = 1000.0

    def __call__(self):
        return self.mono

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds


def line(pct, eta=400, phase="writing", counters="round 1 of 1, pass 1 of 1", stamp=""):
    hours, seconds = divmod(eta, 3600)
    minutes, seconds = divmod(seconds, 60)
    return (
        f"{stamp}/dev/fake: {pct:.2f}%, {counters}, "
        f"eta {hours:02}:{minutes:02}:{seconds:02}, [{phase}]\n"
    )


def sample(pct, **kwargs):
    result = observe(line(pct, **kwargs), "/dev/fake")
    assert result is not None
    return result


def stable(step=5, delta=1):
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(clock())
    view = None
    for n in range(6):
        pct = 10 + n * delta
        view = timing.view(sample(pct, eta=int((100 - pct) * step / delta)), True)
        if n < 5:
            clock.advance(step)
    return clock, timing, view


def bind_wizard_timing(wizard, clock):
    """Keep ProgressTiming on the injected clock after confirm_erase."""
    wizard._clock = clock
    wizard._progress_timing.clock = clock
    wizard._progress_timing.wall_clock = lambda: clock.wall
    wizard._progress_timing.last_clock = (clock(), clock.wall)


@pytest.mark.parametrize(
    "phase,expected",
    [
        ("writing", "Writing"),
        ("verifying", "Verifying"),
        ("blanking", "Writing"),
        ("syncing", "Syncing"),
        ("retrying", "Retrying"),
        ("unknown", "Phase not reported"),
    ],
)
def test_phase_is_explicit_engine_metadata(phase, expected):
    assert sample(25, phase=phase).phase == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        line(5)[:-1],
        line(5).replace("/dev/fake", "/dev/foreign"),
        line(101),
        line(5, counters="round 2 of 1, pass 1 of 1"),
        "summary: 100%\n",
    ],
)
def test_missing_partial_foreign_invalid_never_becomes_observation(text):
    assert observe(text, "/dev/fake") is None


def test_direction_markers_and_log_prefix_are_supported():
    for suffix in ("[writing]>", "<[writing]"):
        record = line(5, stamp="[2026/09/05 12:00:00] info: ").replace(
            "[writing]", suffix
        )
        assert observe(record, "/dev/fake").phase == "Writing"


def test_sparse_counters_or_eta_cannot_support_estimate():
    clock, timing, _ = stable()
    for record in (
        "/dev/fake: 16%, round 1 of 1\n",
        line(16).replace("00:06:40", "unknown"),
    ):
        obs = observe(record, "/dev/fake")
        assert obs.phase == (
            "Writing" if "[writing]" in record else "Phase not reported"
        )
        assert timing.view(obs, True).remaining is None


def test_estimate_requires_six_advances_twenty_seconds_and_engine_agreement():
    clock, timing, view = stable()
    assert view.elapsed == 25
    assert view.remaining == pytest.approx(425)
    assert "Estimated time remaining: about 8 minutes" in view.timing_text
    clock.advance(5)
    assert timing.view(sample(16, eta=1), True).remaining is None


def test_duplicate_polls_and_duplicate_percent_do_not_renew_rate_or_freshness():
    clock, timing, view = stable()
    last = timing.last
    for _ in range(10):
        assert timing.view(last, True).remaining == view.remaining
    clock.advance(11)
    stalled = timing.view(last, True)
    assert stalled.remaining is None
    assert stalled.stale_for == pytest.approx(11)
    assert stalled.percent_is_old
    assert "No new progress update for less than 1 minute." in stalled.timing_text
    assert "last reported" not in stalled.phase
    # A fresh log timestamp with unchanged percent still cannot establish speed.
    for n in range(8):
        clock.advance(5)
        assert timing.view(sample(15, stamp=f"[{n}] info: "), True).remaining is None


@pytest.mark.parametrize(
    "kind",
    [
        "phase",
        "pass",
        "round",
        "regression",
        "missing",
        "stall",
        "wall_forward",
        "wall_backward",
        "mono_backward",
        "mono_nan",
        "rate",
    ],
)
def test_estimate_suppression_at_discontinuities(kind):
    clock, timing, before = stable()
    assert before.remaining
    clock.advance(5)
    obs = sample(16, eta=420)
    if kind == "phase":
        obs = sample(16, phase="verifying")
    elif kind == "pass":
        obs = sample(16, counters="round 1 of 1, pass 2 of 2")
    elif kind == "round":
        obs = sample(16, counters="round 2 of 2, pass 1 of 1")
    elif kind == "regression":
        obs = sample(3)
    elif kind == "missing":
        obs = None
    elif kind == "stall":
        clock.advance(30)
    elif kind == "wall_forward":
        clock.wall += 3600
    elif kind == "wall_backward":
        clock.wall -= 3600
    elif kind == "mono_backward":
        clock.mono = 1
    elif kind == "mono_nan":
        clock.mono = float("nan")
    elif kind == "rate":
        obs = sample(40)
    assert timing.view(obs, True).remaining is None


def test_regression_must_catch_up_and_rebuild_history():
    clock, timing, _ = stable()
    for pct in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14):
        clock.advance(5)
        assert timing.view(sample(pct), True).remaining is None
    assert len(timing.samples) == 0


@pytest.mark.parametrize(
    "step,delta,expected",
    [(1, 1, False), (5, 0.01, False), (11, 1, False), (5, 1, True), (5, 8, True)],
)
def test_fast_slow_sparse_and_stable_streams(step, delta, expected):
    _, _, view = stable(step, delta)
    assert (view.remaining is not None) == expected


def test_irregular_but_stable_rates():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    timing.view(sample(10, eta=450), True)
    for gap in (3, 7, 4, 6, 5):
        clock.advance(gap)
        pct = 10 + clock() / 5
        view = timing.view(sample(pct, eta=int((100 - pct) * 5)), True)
    assert view.remaining == pytest.approx(425)


def test_unknown_future_phase_and_completion_never_get_an_eta():
    clock, timing, _ = stable()
    assert timing.view(timing.last, False).remaining is None
    clock.advance(5)
    assert timing.view(sample(100, eta=0), True).remaining is None
    timing.finish(clock())
    clock.advance(100)
    assert timing.view(timing.last, True).elapsed == 30
    assert timing.view(timing.last, True).remaining is None


@pytest.mark.parametrize(
    "seconds,text",
    [
        (0, "less than 1 minute"),
        (60, "1 minute"),
        (3600, "1 hour"),
        (90061, "1 day 1 hour 1 minute"),
        (8640000, "100 days"),
        (None, "unavailable"),
        (-1, "unavailable"),
        (float("inf"), "unavailable"),
    ],
)
def test_elapsed_has_no_clock_wrap_or_false_precision(seconds, text):
    assert duration(seconds) == text


def test_log_reader_observation_does_not_change_completion_or_signaling(monkeypatch):
    runner = NwipeRunner()
    raw = line(42)
    monkeypatch.setattr(runner, "_read_log_tail", lambda *_: raw)
    runner._refresh_progress("fake-log", "/dev/fake")
    assert runner.progress == 42
    assert runner.progress_observation.percent == 42
    assert runner.result is None and runner._proc is None
    raw = line(4)
    runner._refresh_progress("fake-log", "/dev/fake")
    assert runner.progress == 42  # preserve existing monotonic percent contract
    assert runner.progress_observation.percent == 4  # estimator sees the regression
    raw = ""
    runner._refresh_progress("fake-log", "/dev/fake")
    assert runner.progress_observation is None


def test_wizard_views_stop_finalize_and_freeze_evidence_time(monkeypatch, tmp_path):
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
    w.runner.progress_observation = sample(42, phase="verifying")
    assert w.progress_view.phase == "Verifying"
    assert w.progress_view.remaining is None
    clock.advance(90)
    assert w.progress_view.elapsed == 90
    assert w._claim_stop()
    assert w.progress_view.phase == "Stopping"
    assert w.progress_view.remaining is None
    w.screen = Screen.WORKING
    w.runner.finalizing = True
    assert w.progress_view.phase == "Finalizing"
    result = WipeResult(False, 143, "interrupted", w._wipe_request.logfile)
    w._finish(result, interrupted=True)
    assert w.evidence["timestamps"]["duration_s"] == 90
    clock.advance(1000)
    assert w.progress_view.elapsed == 90
    assert w.evidence["timestamps"]["duration_s"] == 90
    assert "remaining" not in str(w.evidence)


def test_progress_does_not_imply_verified_outcome():
    view = ProgressView("Verifying", 99.99, 121, 60)
    assert view.status_text.startswith("99%.")
    assert "success" not in view.status_text.lower()


def test_engine_timestamp_jump_resets_estimate():
    import datetime

    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    epoch = datetime.datetime(2026, 9, 5)
    for n in range(6):
        stamp = (epoch + datetime.timedelta(seconds=clock())).strftime(
            "[%Y/%m/%d %H:%M:%S] info: "
        )
        view = timing.view(sample(10 + n, eta=450 - n * 5, stamp=stamp), True)
        if n < 5:
            clock.advance(5)
    assert view.remaining is not None
    clock.advance(5)
    assert (
        timing.view(sample(16, stamp="[2026/09/04 00:00:00] info: "), True).remaining
        is None
    )


def test_plain_console_deduplicates_and_remains_cancellable(monkeypatch, capsys):
    import io
    from types import SimpleNamespace
    from beamo_wipe.ui import console_wizard

    w = SimpleNamespace(
        wants_shutdown=False,
        screen=Screen.WORKING,
        preview=False,
        progress_view=ProgressView("Writing", 25, 120),
        error=None,
        evidence_warning="",
        selected=None,
        tick=lambda: None,
    )
    calls = []

    def ready(*_):
        calls.append(True)
        return ([object()] if len(calls) == 20 else [], [], [])

    w.cancel_wipe = lambda: setattr(w, "wants_shutdown", True)
    monkeypatch.setattr(console_wizard.select, "select", ready)
    monkeypatch.setattr(console_wizard.sys, "stdin", io.StringIO("CANCEL\n"))
    assert console_wizard._plain_loop_body(w) == 0
    output = capsys.readouterr().out
    assert output.count("Elapsed:") == 1
    assert "Writing" in output and "25%" in output
    assert len(calls) == 20


def test_shared_display_limits_percent_updates_but_phase_changes_are_immediate():
    from beamo_wipe.demo import make_demo_wizard

    w = make_demo_wizard()
    clock = Clock()
    w._clock = clock
    w._progress_timing = ProgressTiming(clock, lambda: clock.wall)
    w._progress_timing.start(0)
    w.screen = Screen.WORKING
    w.runner.progress = 10
    w.runner.progress_observation = sample(10)
    assert w.progress_view.percent == 10
    for pct in (11, 12, 13, 14):
        clock.advance(1)
        w.runner.progress = pct
        w.runner.progress_observation = sample(pct)
        assert w.progress_view.percent == 10
    clock.advance(1)
    assert w.progress_view.percent == 14
    w.runner.progress_observation = sample(14, phase="verifying")
    assert w.progress_view.phase == "Verifying"


def test_wall_change_does_not_change_monotonic_elapsed():
    clock, timing, _ = stable()
    clock.wall -= 100000
    assert timing.view(timing.last, True).elapsed == 25
    assert timing.view(timing.last, True).remaining is None


def test_recovered_elapsed_comes_from_evidence_and_never_has_eta():
    from beamo_wipe.demo import make_demo_wizard

    w = make_demo_wizard()
    w._recovered = True
    w.evidence = {"timestamps": {"duration_s": 3660}}
    assert w.elapsed_text == "Elapsed: 1 hour 1 minute"
    assert w.progress_view.remaining is None
    w.evidence = {}
    assert w.elapsed_text == "Elapsed: unavailable"


def test_frozen_elapsed_survives_later_clock_discontinuity():
    clock, timing, _ = stable()
    timing.finish(clock())
    clock.mono = -1000
    clock.wall = -1000
    assert timing.view(None, False).elapsed == 25


def test_partial_append_cannot_reuse_an_older_eta_sample():
    assert observe(line(25) + line(26)[:-1], "/dev/fake") is None


@pytest.mark.parametrize(
    "method,phase,allowed",
    [
        ("everyday", "writing", False),
        ("everyday", "verifying", True),
        ("extra", "writing", False),
        ("extra", "verifying", True),
        ("quick_zero", "writing", True),
        ("quick_zero", "verifying", False),
    ],
)
def test_method_gates_estimate_on_final_operation(method, phase, allowed):
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import MethodId

    w = make_demo_wizard()
    clock = Clock()
    w._clock = clock
    w._progress_timing = ProgressTiming(clock, lambda: clock.wall)
    w._progress_timing.start(0)
    w.screen = Screen.WORKING
    w.method = MethodId(method)
    for n in range(6):
        w.runner.progress = 10 + n
        w.runner.progress_observation = sample(10 + n, eta=450 - n * 5, phase=phase)
        view = w.progress_view
        if n < 5:
            clock.advance(5)
    assert (view.remaining is not None) == allowed


def test_invalid_initial_monotonic_time_is_unavailable():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(float("nan"))
    assert timing.view(None, False).elapsed is None


@pytest.mark.parametrize("step", [-1, -0.25, 0.25, 1])
def test_wall_clock_step_suppresses_estimate(step):
    clock, timing, before = stable()
    assert before.remaining is not None
    clock.wall += step
    assert timing.view(timing.last, True).remaining is None


@pytest.mark.parametrize("code,swap_at", [(0, 1), (0, 2), (None, 1), (None, 2)])
def test_late_poll_cannot_publish_phase_into_a_new_runner_generation(
    monkeypatch, code, swap_at
):
    from types import SimpleNamespace
    from beamo_wipe.models import MethodId, WipeRequest

    runner = NwipeRunner()
    signals = []
    old_process = SimpleNamespace(
        poll=lambda: code, send_signal=lambda value: signals.append(value)
    )
    new_process = SimpleNamespace()
    new_observation = sample(5)
    runner._proc = old_process
    reads = []

    def read(*_):
        reads.append(True)
        # Replace at progress, completion, or signal-readiness read boundaries.
        if len(reads) == swap_at:
            runner._proc = new_process
            runner.finalizing = False
            runner.progress_observation = new_observation
            runner.progress = 5
            runner._sigusr1_armed = False
            runner._last_sigusr1 = 0
        return line(99, phase="verifying") + "Program options are set as follows\n"

    monkeypatch.setattr(runner, "_read_log_tail", read)
    request = WipeRequest("/dev/fake", MethodId.EVERYDAY, "/dev/boot", "fake-log")
    runner.poll(request)
    assert runner.finalizing is False
    assert runner.progress_observation is new_observation
    assert runner.progress == 5
    assert runner._sigusr1_armed is False and runner._last_sigusr1 == 0
    assert runner._proc is new_process and runner.result is None
    assert signals == []


def test_pinned_engine_two_second_cadence_can_estimate_after_warmup():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    for n in range(31):
        pct = 10 + n
        view = timing.view(sample(pct, eta=int((100 - pct) * 2)), True)
        clock.advance(2)
    assert view.remaining is not None


def test_normal_cadence_with_poll_jitter_can_estimate():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    for gap in (1.9, 2.1, 2.2, 1.8, 2.05, 1.95) * 5:
        pct = 10 + clock() * 0.5
        view = timing.view(sample(pct, eta=int((100 - pct) * 2)), True)
        clock.advance(gap)
    assert view.remaining is not None


def test_slow_quantized_progress_can_estimate_with_bounded_history():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    for n in range(200):
        pct = 50 + n * 0.01
        view = timing.view(
            sample(pct, eta=int((100 - pct) * 500), phase="verifying"), True
        )
        clock.advance(5)
    assert view.remaining is not None and view.remaining > 3600
    assert len(timing.samples) <= 61
    assert "hours" in view.timing_text and "seconds" not in view.timing_text


def test_real_runner_fake_output_reaches_eta_at_its_signal_cadence(monkeypatch):
    from types import SimpleNamespace
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import MethodId, WipeRequest

    clock = Clock()
    w = make_demo_wizard()
    w._clock = clock
    w._progress_timing = ProgressTiming(clock, lambda: clock.wall)
    w._progress_timing.start(0)
    w.screen = Screen.WORKING
    w.method = MethodId.QUICK_ZERO
    w._wipe_request = WipeRequest("/dev/fake", w.method, "/dev/boot", "fake-log")
    runner = NwipeRunner()
    signals = []
    runner._proc = SimpleNamespace(
        poll=lambda: None, send_signal=lambda value: signals.append((clock(), value))
    )
    w.runner = runner
    monkeypatch.setattr("beamo_wipe.nwipe_runner.time.monotonic", clock)
    monkeypatch.setattr(
        runner,
        "_read_log_tail",
        lambda *_: line(10 + clock() / 2, eta=int((90 - clock() / 2) * 2))
        + "Program options are set as follows\n",
    )
    for _ in range(31):
        w.tick()
        view = w.progress_view
        clock.advance(2)
    assert view.remaining is not None
    assert view.phase == "Writing" and w.screen == Screen.WORKING
    assert runner.result is None and w.wipe_result is None
    assert len(signals) == 30
    assert all(b[0] - a[0] == 2 for a, b in zip(signals, signals[1:]))


def test_more_precise_record_cannot_reinterpret_old_coarse_samples():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    for n in range(6):
        pct = 10 + n
        coarse = line(pct, eta=(100 - pct) * 5).replace(f"{pct:.2f}%", f"{pct}%")
        view = timing.view(observe(coarse, "/dev/fake"), True)
        assert view.remaining is None
        clock.advance(5)
    assert timing.view(sample(16, eta=420), True).remaining is None


def test_thresholds_follow_measured_sigusr1_cadence():
    assert ENGINE_PROGRESS_INTERVAL_S == 2.0
    assert STALE_PROGRESS_S == 5 * ENGINE_PROGRESS_INTERVAL_S
    assert FIRST_UPDATE_GRACE_S == 10 * ENGINE_PROGRESS_INTERVAL_S


def test_quiet_progress_module_does_not_stop_the_engine():
    import inspect
    from beamo_wipe import progress

    src = inspect.getsource(progress)
    assert "SIGTERM" not in src
    assert "SIGKILL" not in src
    assert "os.kill" not in src
    assert ".cancel(" not in src


def test_no_first_update_stays_quiet_then_marks_unavailable():
    clock = Clock()
    timing = ProgressTiming(clock, lambda: clock.wall)
    timing.start(0)
    early = timing.view(None, False)
    assert early.phase == "Preparing"
    assert early.stale_for is None
    assert early.animate
    assert early.known_quiet
    assert "No new progress update" not in early.status_text
    clock.advance(FIRST_UPDATE_GRACE_S - 1)
    still_quiet = timing.view(None, False)
    assert still_quiet.stale_for is None
    assert still_quiet.animate
    assert still_quiet.known_quiet
    clock.advance(2)
    late = timing.view(None, False)
    assert late.phase == "Preparing"
    assert late.stale_for == pytest.approx(FIRST_UPDATE_GRACE_S + 1)
    assert not late.animate
    assert not late.known_quiet
    assert late.percent_is_old is False
    assert "No new progress update for less than 1 minute." in late.status_text
    assert late.stale_for > STALE_PROGRESS_S


def test_long_silence_marks_last_value_old_without_failing():
    clock, timing, _ = stable()
    clock.advance(11)
    view = timing.view(timing.last, True)
    assert view.percent_is_old
    assert view.stale_for == pytest.approx(11)
    assert view.phase == "Writing"
    assert "No new progress update" in view.status_text


def test_resumed_output_clears_stale_mark():
    clock, timing, _ = stable()
    clock.advance(11)
    assert timing.view(timing.last, True).percent_is_old
    clock.advance(2)
    fresh = timing.view(sample(16, eta=420), True)
    assert fresh.stale_for is None
    assert fresh.percent_is_old is False
    assert "No new progress update" not in fresh.status_text
    assert fresh.phase == "Writing"


def test_parser_errors_do_not_immediately_mark_stale_or_fail():
    clock, timing, before = stable()
    assert before.stale_for is None
    truncated = observe(line(16)[:-1], "/dev/fake")
    assert truncated is None
    view = timing.view(None, True)
    assert view.phase == "Writing"
    assert view.stale_for is None
    assert view.percent_is_old is False
    assert view.remaining is None
    clock.advance(11)
    late = timing.view(None, True)
    assert late.percent_is_old
    assert late.stale_for == pytest.approx(11)
    assert late.phase == "Writing"


def test_phase_transition_is_not_stale_and_keeps_process_running(tmp_path, monkeypatch):
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
    w.runner.progress = 20
    w.runner.progress_observation = sample(20, phase="writing")
    assert w.progress_view.phase == "Writing"
    w.runner.progress_observation = sample(20, phase="verifying")
    view = w.progress_view
    assert view.phase == "Verifying"
    assert view.stale_for is None
    assert w.screen == Screen.WORKING
    assert w.wipe_result is None
    assert not getattr(w.runner, "cancelled", False)


def test_wizard_no_first_update_silence_and_resume_keep_the_process(monkeypatch, tmp_path):
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
    clock.advance(FIRST_UPDATE_GRACE_S - 1)
    early = w.progress_view
    assert early.phase == "Preparing"
    assert early.stale_for is None
    assert early.animate
    assert w.screen == Screen.WORKING
    assert w.wipe_result is None
    clock.advance(2)
    missing = w.progress_view
    assert missing.stale_for == pytest.approx(FIRST_UPDATE_GRACE_S + 1)
    assert missing.percent_is_old is False
    assert not missing.animate
    assert "No new progress update" in missing.status_text
    assert w.screen == Screen.WORKING
    assert not getattr(w.runner, "cancelled", False)
    w.runner.progress = 12
    w.runner.progress_observation = sample(12)
    fresh = w.progress_view
    assert fresh.stale_for is None
    assert fresh.percent_is_old is False
    assert fresh.percent == 12
    clock.advance(30)
    stale = w.progress_view
    assert stale.percent_is_old
    assert stale.stale_for == pytest.approx(30)
    assert stale.status_text.startswith("Last reported: 12% (old).")
    assert w.screen == Screen.WORKING
    assert w.wipe_result is None
    assert not getattr(w.runner, "cancelled", False)
    clock.advance(5)
    w.runner.progress = 18
    w.runner.progress_observation = sample(18)
    resumed = w.progress_view
    assert resumed.stale_for is None
    assert resumed.percent_is_old is False
    assert resumed.percent == 18
    assert w.screen == Screen.WORKING
    assert not getattr(w.runner, "cancelled", False)


def test_process_exit_and_cancel_are_not_stale_telemetry(monkeypatch, tmp_path):
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
    accepted = w.progress_view
    assert accepted.percent == 40
    assert accepted.stale_for is None
    clock.advance(30)
    stale = w.progress_view
    assert stale.percent_is_old
    assert stale.stale_for == pytest.approx(30)
    assert w.screen == Screen.WORKING
    assert w.wipe_result is None
    assert not getattr(w.runner, "cancelled", False)
    assert w._claim_stop()
    stopping = w.progress_view
    assert stopping.phase == "Stopping"
    assert stopping.stale_for is None
    assert stopping.percent_is_old is False
    assert "No new progress update" not in stopping.status_text
    w.screen = Screen.WORKING
    w.runner.finalizing = True
    finishing = w.progress_view
    assert finishing.phase == "Finalizing"
    assert finishing.stale_for is None
    assert finishing.percent_is_old is False
    assert w.wipe_result is None
    result = WipeResult(False, 1, "nwipe exited 1", w._wipe_request.logfile)
    w._finish(result)
    done = w.progress_view
    assert done.stale_for is None
    assert done.percent_is_old is False
    assert "No new progress update" not in done.status_text


def test_recovery_does_not_show_live_stale_progress():
    from beamo_wipe.demo import make_demo_wizard

    w = make_demo_wizard()
    clock = Clock()
    w._clock = clock
    w._recovered = True
    w.evidence = {"timestamps": {"duration_s": 120}}
    w.runner.progress = 55
    w.runner.progress_observation = sample(55)
    view = w.progress_view
    assert view.stale_for is None
    assert view.remaining is None
    clock.advance(60)
    assert w.progress_view.stale_for is None
    assert w.elapsed_text == "Elapsed: 2 minutes"


def test_status_text_marks_old_percent_without_claiming_failure():
    view = ProgressView(
        "Writing", 42, 120, stale_for=11, percent_is_old=True
    )
    assert view.status_text.startswith("Last reported: 42% (old).")
    assert "No new progress update for less than 1 minute." in view.status_text
    assert "fail" not in view.status_text.lower()
    assert "cancel" not in view.status_text.lower()
    assert not view.animate
