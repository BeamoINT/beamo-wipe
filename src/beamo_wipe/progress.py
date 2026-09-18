# SPDX-License-Identifier: GPL-3.0-or-later
"""Display-only engine observations. Never evidence of successful completion."""

from __future__ import annotations

import datetime
import math
from typing import Callable
import re
from collections import deque
from dataclasses import dataclass

_SUFFIX = re.compile(
    r",\s*eta (\d{2,6}):([0-5]\d):([0-5]\d),\s*<?\[(writing|verifying|blanking|syncing|retrying)\]>?\s*$"
)
_MARKER = re.compile(
    r"(?:,\s*)<?\[(writing|verifying|blanking|syncing|retrying)\]>?\s*$"
)
_PHASES = {
    "writing": "Writing",
    "blanking": "Writing",
    "verifying": "Verifying",
    "syncing": "Syncing",
    "retrying": "Retrying",
}

# Engine phase codes above stay English: wizard and ProgressTiming compare
# them. Only this display map is translated.
PHASE_WRITING = "Writing"
PHASE_VERIFYING = "Verifying"
PHASE_SYNCING = "Syncing"
PHASE_RETRYING = "Retrying"
PHASE_PREPARING = "Preparing"
PHASE_STOPPING = "Stopping"
PHASE_FINALIZING = "Finalizing"
PHASE_UNKNOWN = "Phase not reported"


def _build_phase_display() -> dict[str, str]:
    return {
        "Writing": PHASE_WRITING,
        "Verifying": PHASE_VERIFYING,
        "Syncing": PHASE_SYNCING,
        "Retrying": PHASE_RETRYING,
        "Preparing": PHASE_PREPARING,
        "Stopping": PHASE_STOPPING,
        "Finalizing": PHASE_FINALIZING,
        "Phase not reported": PHASE_UNKNOWN,
    }


_PHASE_DISPLAY = _build_phase_display()


def phase_display(phase: str) -> str:
    return _PHASE_DISPLAY.get(phase, phase)


def _apply_language() -> None:
    global _PHASE_DISPLAY
    _PHASE_DISPLAY = _build_phase_display()


STAGE_OVERWRITE = "Overwrite {i} of {n}"
STAGE_VERIFY = "Read-back verification"
STAGE_STEP = "Step {k} of {total}: {stage}"
STAGE_DONE_MARK = " (done)"
STAGE_NOW_MARK = " (now)"
STAGE_NOT_REPORTED = "Current step not reported yet"
STAGE_MISMATCH = "Engine step does not match the planned method"
STEP_PCT = "{step} ({pct} of this step)"
STEP_PCT_OLD = "{step} (last reported {pct} of this step)"
PHASE_NOTE_VERIFYING = (
    "Checking the last overwrite. The erase is not done "
    "until the result screen."
)
PHASE_NOTE_SYNCING = "Finishing disk writes. This step can be quiet for a while."
PHASE_NOTE_RETRYING = "Retrying a step that did not finish. The erase continues."
PHASE_NOTE_FINALIZING = "The erase run ended. Determining the result."
ESTIMATE_EARLY = "Estimating after more progress."
ESTIMATE_LAST_STEP = "Estimate unavailable until the last step."
ESTIMATE_RETRYING = "Estimate unavailable while the drive is retrying."
ESTIMATE_SYNCING = "Estimate unavailable while the drive is syncing."
ESTIMATE_PAUSED = "No estimate until progress resumes."
ESTIMATE_NO_ETA = "Estimate unavailable: no time information from the drive."
ESTIMATE_DISAGREE = "Estimate unavailable: progress reports disagree."
ESTIMATE_STEP_DONE = "Last step finished. Waiting for the result."

DURATION_UNAVAILABLE = "unavailable"
LESS_THAN_MINUTE = "less than 1 minute"
DAY_ONE = "{value} day"
DAY_MANY = "{value} days"
HOUR_ONE = "{value} hour"
HOUR_MANY = "{value} hours"
MINUTE_ONE = "{value} minute"
MINUTE_MANY = "{value} minutes"
ABOUT_DURATION = "about {text}"
NO_UPDATE = "No new progress update for {text}."
STALE_MEANING = "A quiet screen does not mean the erase stopped."
STALE_NEXT = (
    "Keep the USB in and wall power connected. "
    'Do not turn off the computer. You can choose "Stop erase" at any time.'
)
ELAPSED_LINE = " · Elapsed: {text}"
REMAINING_LINE = "\nEstimated time remaining: {text}"
PROGRESS_UNKNOWN = "Progress not reported"
LAST_REPORTED = "Last reported: {text} (old)"
# Measured nwipe 0.42: the runner requests SIGUSR1 every 2.0s after the
# handler exists. Five missed pulses mark telemetry stale, matching the
# existing estimate-history expiry. The PRNG auto-bench is 8×1.0s before
# that handler is armed, so the first percentage can legitimately wait
# ~10s plus one pulse; twenty seconds is ten missed pulses after bench.
ENGINE_PROGRESS_INTERVAL_S = 2.0
STALE_PROGRESS_S = 10.0
FIRST_UPDATE_GRACE_S = 20.0
QUIET_PHASES = frozenset({"Preparing", "Syncing", "Retrying"})


@dataclass(frozen=True)
class Observation:
    record: str
    percent: float
    phase: str
    counters: tuple[int, int, int, int]
    engine_eta: int | None
    quantum: float
    engine_time: float | None = None


@dataclass(frozen=True)
class Stage:
    """One planned operation. kind is "overwrite" or "verify"."""

    kind: str
    index: int  # 1-based within kind
    total: int  # overwrite passes, for "i of n"; 0 for verify


def plan_stages(overwrite_passes: int, has_verify: bool) -> tuple[Stage, ...]:
    """Derive the full operation sequence from the method plan."""
    if overwrite_passes < 1:
        return ()
    stages = [
        Stage("overwrite", i, overwrite_passes)
        for i in range(1, overwrite_passes + 1)
    ]
    if has_verify:
        stages.append(Stage("verify", 1, 0))
    return tuple(stages)


def stage_label(stage: Stage) -> str:
    if stage.kind == "verify":
        return STAGE_VERIFY
    return STAGE_OVERWRITE.format(i=stage.index, n=stage.total)


def locate_stage(
    stages: tuple[Stage, ...], observation: Observation | None
) -> tuple[int | None, bool]:
    """Locate the live observation on the plan.

    Returns (position, mismatch). None without mismatch means the
    engine has not reported a locatable step yet; mismatch means the
    report disagrees with the plan. Never guess.
    """
    if not stages or observation is None:
        return None, False
    round_i, round_n, pass_i, pass_n = observation.counters
    if (round_i, round_n) != (1, 1):
        return None, True
    overwrites = [s for s in stages if s.kind == "overwrite"]
    verify_at = next(
        (n for n, s in enumerate(stages) if s.kind == "verify"), None
    )
    if observation.phase == "Verifying":
        if verify_at is None:
            return None, True
        return verify_at, False
    if not (pass_n and 1 <= pass_i <= pass_n):
        return None, False
    if pass_n != len(overwrites):
        return None, True
    return pass_i - 1, False


def sequence_text(
    stages: tuple[Stage, ...], position: int | None
) -> str:
    """Full stage list, one per line, with done/now markers."""
    lines = []
    for n, stage in enumerate(stages):
        label = stage_label(stage)
        if position is not None:
            if n < position:
                label += STAGE_DONE_MARK
            elif n == position:
                label += STAGE_NOW_MARK
        lines.append(label)
    return "\n".join(lines)


def step_text(
    stages: tuple[Stage, ...],
    position: int | None,
    mismatch: bool,
    pct: float | None = None,
    pct_old: bool = False,
) -> str:
    """Current-step line, or explicit uncertainty. Never a guess.

    A live step percent scopes the number to its step so 100% of one
    write cannot read as overall completion. Unknown and mismatched
    steps carry no percent.
    """
    if mismatch:
        return STAGE_MISMATCH
    if position is None or not stages:
        return STAGE_NOT_REPORTED
    step = STAGE_STEP.format(
        k=position + 1, total=len(stages), stage=stage_label(stages[position])
    )
    if pct is None:
        return step
    from beamo_wipe.wizard import format_progress_percent

    template = STEP_PCT_OLD if pct_old else STEP_PCT
    return template.format(step=step, pct=format_progress_percent(pct))


def phase_note(phase: str, mismatch: bool) -> str:
    """One-line transition explainer for the display phase, if any.

    Engine phase codes stay English; the finalizing display phase is
    compared against its translated constant. Mismatch and stopping
    carry their own text and take no note.
    """
    if mismatch:
        return ""
    if phase == "Verifying":
        return PHASE_NOTE_VERIFYING
    if phase == "Syncing":
        return PHASE_NOTE_SYNCING
    if phase == "Retrying":
        return PHASE_NOTE_RETRYING
    if phase == PHASE_FINALIZING:
        return PHASE_NOTE_FINALIZING
    return ""


def observe(text: str, device: str) -> Observation | None:
    # Reuse the target and counter validation used by completion parsing.
    from beamo_wipe.nwipe_runner import _iter_target_progress

    if not text.endswith("\n"):
        return None  # do not reuse an older sample across an incomplete append
    last = None
    for line in text.splitlines(keepends=True):
        if not line.endswith("\n"):
            continue  # a writer may still be appending this record
        for match, value in _iter_target_progress(line, device):
            suffix = _SUFFIX.fullmatch(line[match.end() :].strip())
            marker = _MARKER.search(line[match.end() :])
            digits = match.group(2).partition(".")[2]
            engine_time = None
            if line.lstrip().startswith("["):
                stamp = line.lstrip().partition("]")[0][1:]
                try:
                    engine_time = (
                        datetime.datetime.strptime(stamp, "%Y/%m/%d %H:%M:%S")
                        .replace(tzinfo=datetime.timezone.utc)
                        .timestamp()
                    )
                except ValueError:
                    suffix = None
            last = Observation(
                line,
                value,
                _PHASES[marker[1]] if marker else PHASE_UNKNOWN,
                (int(match[3]), int(match[4]), int(match[5] or 0), int(match[6] or 0)),
                int(suffix[1]) * 3600 + int(suffix[2]) * 60 + int(suffix[3])
                if suffix
                else None,
                10.0 ** -len(digits),
                engine_time,
            )
    return last


def duration(seconds: float | None) -> str:
    if (
        seconds is None
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        return DURATION_UNAVAILABLE
    minutes = int(seconds) // 60
    if minutes == 0:
        return LESS_THAN_MINUTE
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = []
    units = (
        (days, DAY_ONE, DAY_MANY),
        (hours, HOUR_ONE, HOUR_MANY),
        (minutes, MINUTE_ONE, MINUTE_MANY),
    )
    for value, one, many in units:
        if value:
            parts.append((one if value == 1 else many).format(value=value))
    return " ".join(parts)


def estimate(seconds: float) -> str:
    # Round UP, using minutes, five-minute buckets, or whole hours. No seconds.
    if seconds < 60:
        return LESS_THAN_MINUTE
    unit = 60 if seconds < 600 else 300 if seconds < 3600 else 3600
    return ABOUT_DURATION.format(text=duration(math.ceil(seconds / unit) * unit))


def silence_text(stale_for: float | None) -> str:
    if stale_for is None:
        return ""
    return NO_UPDATE.format(text=duration(stale_for))


def stale_block(stale_for: float | None) -> str:
    """Full stale-progress explainer: how long, what it means, what to do.

    Reads module constants at call time so set_language() applies. Never
    recommends restarting, unplugging, or retrying the wipe.
    """
    if stale_for is None:
        return ""
    return "\n".join((silence_text(stale_for), STALE_MEANING, STALE_NEXT))


@dataclass(frozen=True)
class ProgressView:
    phase: str
    percent: float | None
    elapsed: float | None
    remaining: float | None = None
    stale_for: float | None = None
    percent_is_old: bool = False
    stages: tuple[Stage, ...] = ()
    position: int | None = None
    mismatch: bool = False
    step_percent: float | None = None
    estimate_state: str = ""

    @property
    def known_quiet(self) -> bool:
        return self.stale_for is None and self.phase in QUIET_PHASES

    @property
    def animate(self) -> bool:
        """True only while waiting for the first number during a known quiet start."""
        return (
            self.percent is None
            and self.stale_for is None
            and not self.percent_is_old
            and self.phase == "Preparing"
        )

    @property
    def timing_text(self) -> str:
        text = phase_display(self.phase) + ELAPSED_LINE.format(text=duration(self.elapsed))
        if self.remaining is not None:
            text += REMAINING_LINE.format(text=estimate(self.remaining))
        elif self.estimate_state:
            text += REMAINING_LINE.format(text=self.estimate_state)
        wait = stale_block(self.stale_for)
        if wait:
            text += f"\n{wait}"
        if self.stages:
            text += f"\n{step_text(self.stages, self.position, self.mismatch, self.step_percent, self.percent_is_old)}"
            note = phase_note(self.phase, self.mismatch)
            if note:
                text += f"\n{note}"
            marked = None if self.mismatch else self.position
            text += f"\n{sequence_text(self.stages, marked)}"
        return text

    @property
    def status_text(self) -> str:
        from beamo_wipe.wizard import format_progress_percent

        if self.percent is None:
            pct = PROGRESS_UNKNOWN
        elif self.percent_is_old:
            pct = LAST_REPORTED.format(text=format_progress_percent(self.percent))
        else:
            pct = format_progress_percent(self.percent)
        return f"{pct}. {self.timing_text}"


class ProgressTiming:
    """Bounded history of newly observed progress, using an injected clock.

    The engine ETA must agree with at least five fresh, stable measured intervals.
    Only estimate within the method's final operation: future write/read rates
    are not interchangeable. Reading the same record never renews freshness.
    """

    def __init__(
        self, clock: Callable[[], float], wall_clock: Callable[[], float]
    ) -> None:
        self.clock, self.wall_clock = clock, wall_clock
        self.started: float | None = None
        self.ended: float | None = None
        self.invalid_clock = False
        self.last_clock: tuple[float, float] | None = None
        self.last: Observation | None = None
        self.samples: deque[tuple[float, float]] = deque(maxlen=61)
        self.phase = "Preparing"
        self.last_seen: float | None = None
        self.high_water = 0.0

    def start(self, now: float) -> None:
        self.started = now
        self.invalid_clock = not math.isfinite(now)
        self.last_clock = (now, self.wall_clock())

    def clear_estimate(self) -> None:
        self.samples.clear()

    def finish(self, now: float) -> None:
        self.view(None, False)  # check the clock before freezing
        self.ended = now
        self.clear_estimate()

    def view(
        self, observation: Observation | None, final_operation: bool
    ) -> ProgressView:
        if self.ended is not None:
            elapsed = (
                None
                if self.invalid_clock or self.started is None
                else max(0.0, self.ended - self.started)
            )
            return ProgressView(self.phase, None, elapsed)
        now, wall = self.clock(), self.wall_clock()
        changed_clock = False
        if self.last_clock:
            mono_delta = now - self.last_clock[0]
            wall_delta = wall - self.last_clock[1]
            if not math.isfinite(now) or mono_delta < 0:
                self.invalid_clock = True
            changed_clock = (
                self.invalid_clock
                or not math.isfinite(wall_delta)
                or abs(wall_delta - mono_delta) > 0.1
            )
        self.last_clock = now, wall
        if changed_clock:
            self.clear_estimate()
        elapsed = None
        if self.started is not None and not self.invalid_clock:
            elapsed = max(
                0.0, (self.ended if self.ended is not None else now) - self.started
            )
        if observation is None:
            # Incomplete/malformed polls are not accepted updates. Keep the
            # last accepted monotonic time; only age can mark telemetry stale.
            self.clear_estimate()
        if observation is not None and observation != self.last:
            previous = self.last
            if previous and self.last_seen is not None:
                if (observation.engine_time is None) != (previous.engine_time is None):
                    changed_clock = True
                elif (
                    observation.engine_time is not None
                    and previous.engine_time is not None
                ):
                    engine_delta = observation.engine_time - previous.engine_time
                    if (
                        engine_delta <= 0
                        or abs(engine_delta - (now - self.last_seen)) > 2
                    ):
                        changed_clock = True
            self.last = observation
            self.last_seen = now
            self.phase = observation.phase
            if previous and (
                previous.phase != observation.phase
                or previous.counters != observation.counters
                or previous.quantum != observation.quantum
            ):
                self.clear_estimate()
            regressed = observation.percent < self.high_water
            self.high_water = max(self.high_water, observation.percent)
            if regressed or observation.engine_eta is None or changed_clock:
                self.clear_estimate()
            elif not self.samples or observation.percent > self.samples[-1][1]:
                if self.samples and not 1 <= now - self.samples[-1][0] <= 10:
                    self.clear_estimate()
                self.samples.append((now, observation.percent))
        if self.samples and now - self.samples[-1][0] > STALE_PROGRESS_S:
            self.clear_estimate()
        remaining = None
        obs = self.last
        if (
            not self.invalid_clock
            and self.ended is None
            and final_operation
            and obs
            and obs.phase in {"Writing", "Verifying"}
            and len(self.samples) >= 6
            and self.samples[-1][0] - self.samples[0][0] >= 20
            and obs.engine_eta
            and obs.percent < 100
        ):
            intervals = list(zip(self.samples, list(self.samples)[1:]))
            rates = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in intervals]
            span = self.samples[-1][1] - self.samples[0][1]
            if (
                span + obs.quantum * 1e-6 >= obs.quantum * 10
                and all(
                    b[1] - a[1] + obs.quantum * 1e-6 >= obs.quantum
                    for a, b in intervals
                )
                and min(rates) > 0
                and max(rates) / min(rates) <= 1.5
            ):
                projected = (100 - obs.percent) / (
                    span / (self.samples[-1][0] - self.samples[0][0])
                )
                if 2 / 3 <= obs.engine_eta / projected <= 1.5:
                    remaining = max(projected, obs.engine_eta)
        stale_for = None
        percent_is_old = False
        if self.invalid_clock:
            stale_for = None
        elif self.last_seen is None:
            if (
                self.started is not None
                and elapsed is not None
                and elapsed >= FIRST_UPDATE_GRACE_S
            ):
                stale_for = elapsed
        elif now - self.last_seen > STALE_PROGRESS_S:
            stale_for = now - self.last_seen
            percent_is_old = True
        state = ""
        if remaining is None:
            state = self._estimate_state(observation, final_operation, stale_for)
        return ProgressView(
            self.phase, None, elapsed, remaining,
            stale_for=stale_for, percent_is_old=percent_is_old,
            estimate_state=state,
        )

    def _estimate_state(
        self,
        observation: Observation | None,
        final_operation: bool,
        stale_for: float | None,
    ) -> str:
        """Name the first unmet estimate gate. Never manufactures certainty."""
        current = observation if observation is not None else self.last
        phase = current.phase if current is not None else self.phase
        if phase == "Retrying":
            return ESTIMATE_RETRYING
        if phase == "Syncing":
            return ESTIMATE_SYNCING
        if stale_for is not None:
            return ESTIMATE_PAUSED
        if current is not None and not current.engine_eta:
            return ESTIMATE_NO_ETA
        samples = self.samples
        if len(samples) < 6 or samples[-1][0] - samples[0][0] < 20:
            return ESTIMATE_EARLY
        if not final_operation:
            return ESTIMATE_LAST_STEP
        if current is not None and current.percent >= 100:
            return ESTIMATE_STEP_DONE
        return ESTIMATE_DISAGREE
