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


@dataclass(frozen=True)
class Observation:
    record: str
    percent: float
    phase: str
    counters: tuple[int, int, int, int]
    engine_eta: int | None
    quantum: float
    engine_time: float | None = None


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
                _PHASES[marker[1]] if marker else "Phase not reported",
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
        return "unavailable"
    minutes = int(seconds) // 60
    if minutes == 0:
        return "less than 1 minute"
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = []
    for value, unit in ((days, "day"), (hours, "hour"), (minutes, "minute")):
        if value:
            parts.append(f"{value} {unit}{'s' if value != 1 else ''}")
    return " ".join(parts)


def estimate(seconds: float) -> str:
    # Round UP, using minutes, five-minute buckets, or whole hours. No seconds.
    if seconds < 60:
        return "less than 1 minute"
    unit = 60 if seconds < 600 else 300 if seconds < 3600 else 3600
    return "about " + duration(math.ceil(seconds / unit) * unit)


@dataclass(frozen=True)
class ProgressView:
    phase: str
    percent: float | None
    elapsed: float | None
    remaining: float | None = None

    @property
    def timing_text(self) -> str:
        text = f"{self.phase} · Elapsed: {duration(self.elapsed)}"
        if self.remaining is not None:
            text += f"\nEstimated time remaining: {estimate(self.remaining)}"
        return text

    @property
    def status_text(self) -> str:
        from beamo_wipe.wizard import format_progress_percent

        pct = (
            "Progress not reported"
            if self.percent is None
            else format_progress_percent(self.percent)
        )
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
        if self.samples and now - self.samples[-1][0] > 10:
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
        phase = self.phase
        if self.last_seen is not None and (
            observation is None or now - self.last_seen > 10
        ):
            phase += " (last reported)"
        return ProgressView(phase, None, elapsed, remaining)
