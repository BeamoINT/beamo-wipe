# SPDX-License-Identifier: GPL-3.0-or-later
"""Startup stage tracker: truthful pre-discovery progress for every surface.

The three stages describe work in progress and never claim a safety check
has passed. A stage is marked done only when the next stage begins or
discovery returns; a failed startup marks nothing further done. Discovery
itself (not these lines) verifies the boot USB exclusion. Presenters — the
Tk splash, the console lines, the GTK stage window — render snapshots.
Stage transitions are also appended to the serial log for post-run evidence.
"""

from __future__ import annotations

import queue
import threading
import time

from beamo_wipe import copy as C

STAGE_STARTING = "starting"
STAGE_BOOT_USB = "checking-boot-usb"
STAGE_FINDING = "finding-disks"
STAGES = (STAGE_STARTING, STAGE_BOOT_USB, STAGE_FINDING)

STALL_AFTER_S = 10.0

_STAGE_MARKERS = {
    STAGE_STARTING: "BEAMO_WIPE_STAGE_STARTING",
    STAGE_BOOT_USB: "BEAMO_WIPE_STAGE_BOOT_USB",
    STAGE_FINDING: "BEAMO_WIPE_STAGE_FINDING",
}
STAGE_DONE_MARKER = "BEAMO_WIPE_STAGE_DONE"
STAGE_FAILED_MARKER = "BEAMO_WIPE_STAGE_FAILED"
STAGE_STALLED_MARKER = "BEAMO_WIPE_STAGE_STALLED"

STAGE_COPY = {
    STAGE_STARTING: (C.STARTUP_TITLE, C.STARTUP_TITLE_HINT),
    STAGE_BOOT_USB: (C.STARTUP_STAGE_BOOT_USB, C.STARTUP_STAGE_BOOT_USB_HINT),
    STAGE_FINDING: (C.STARTUP_STAGE_FINDING, C.STARTUP_STAGE_FINDING_HINT),
}


def _emit(marker: str) -> None:
    try:
        from beamo_wipe.diagnostics import emit_serial_marker

        emit_serial_marker(marker)
    except Exception:
        pass


class StartupStages:
    """Ordered, clock-injectable startup progress with stall detection."""

    def __init__(self, *, clock=time.monotonic, stall_after_s: float = STALL_AFTER_S):
        self._clock = clock
        self._stall_after = max(0.0, float(stall_after_s))
        self.states = {stage: "pending" for stage in STAGES}
        self.failed = False
        self.done = False
        self._active: str | None = None
        self._active_since = 0.0
        self._stalled_reported = False
        self.begin(STAGE_STARTING)

    @property
    def active(self) -> str | None:
        return self._active

    def begin(self, stage: str) -> bool:
        """Activate a stage; the previously active one demonstrably ended."""
        if stage not in self.states:
            raise ValueError(f"unknown startup stage: {stage!r}")
        if self.done or self.failed:
            return False
        if self._active is not None:
            self.states[self._active] = "done"
        self._active = stage
        self.states[stage] = "active"
        self._active_since = self._clock()
        self._stalled_reported = False
        _emit(_STAGE_MARKERS[stage])
        return True

    def succeed(self) -> None:
        if self._active is not None:
            self.states[self._active] = "done"
        self.done = True
        _emit(STAGE_DONE_MARKER)

    def fail(self) -> None:
        # The active stage stays exactly as it was: nothing further is
        # marked done, so a failure can never look like a passed check.
        self.failed = True
        _emit(STAGE_FAILED_MARKER)

    def stalled(self) -> bool:
        """True once while the active stage overruns, for a 'still working' note."""
        if (
            self.done
            or self.failed
            or self._active is None
            or self._stalled_reported
        ):
            return False
        if self._clock() - self._active_since < self._stall_after:
            return False
        self._stalled_reported = True
        _emit(STAGE_STALLED_MARKER)
        return True

    def snapshot(self) -> list:
        return [
            {
                "key": stage,
                "title": STAGE_COPY[stage][0],
                "hint": STAGE_COPY[stage][1],
                "state": self.states[stage],
            }
            for stage in STAGES
        ]


_MISSING = object()


class StartupRun:
    """One staged build: worker thread plus UI-thread sequencing.

    ``build`` receives a worker-safe ``report(stage_key)`` callback and
    returns the built wizard; anything it raises becomes the failure
    outcome. The worker touches only the report queue and the outcome
    slot — stage transitions, stall notes, and completion all happen on
    the UI thread via :meth:`drain` and :meth:`poll`, so every surface
    (Tk ``after``, GTK timeout, console sleep loop) shares one discipline.
    """

    def __init__(self, build, *, clock=time.monotonic, stall_after_s: float = STALL_AFTER_S):
        self.stages = StartupStages(clock=clock, stall_after_s=stall_after_s)
        self._build = build
        self._clock = clock
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._outcome = _MISSING
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="beamo-startup"
        )

    def start(self) -> None:
        self.thread.start()

    def report(self, stage: str) -> None:
        self._queue.put(stage)

    def _run(self) -> None:
        try:
            outcome = self._build(self.report)
        except BaseException as exc:
            outcome = exc
        with self._lock:
            self._outcome = outcome

    def drain(self) -> list:
        """Apply queued stage starts on the UI thread; return the snapshot."""
        while True:
            try:
                stage = self._queue.get_nowait()
            except queue.Empty:
                break
            # An unknown key is a programming error: fail loudly in tests
            # rather than silently showing a stuck stage in production.
            self.stages.begin(stage)
        return self.stages.snapshot()

    def stalled_note(self) -> str | None:
        if self.stages.stalled():
            return C.STARTUP_STILL_WORKING
        return None

    def poll(self):
        """UI thread: None while running, else ("wizard", w) / ("failed", exc).

        The worker always queues its last stage report before publishing
        the outcome, so once an outcome is visible a final drain is
        guaranteed to observe every report: the splash can never close
        showing "Waiting" for work that already ended.
        """
        self.drain()
        with self._lock:
            if self._outcome is _MISSING:
                return None
            outcome = self._outcome
        # An outcome became visible after the first drain; a report queued
        # just before it lands here, never after the splash closes.
        self.drain()
        if isinstance(outcome, BaseException):
            self.stages.fail()
            return ("failed", outcome)
        self.stages.succeed()
        return ("wizard", outcome)


def complete_synchronously(build, **_kwargs) -> tuple:
    """Run ``build`` on this thread and return its startup outcome.

    Same ("wizard", wizard) / ("failed", exc) protocol as the graphical
    presenters, without opening any display. Headless tests double the
    display presenters with this so app.py keeps its exact staged
    sequencing while the factory runs inline. Presenter options such as
    ``fullscreen`` are accepted and ignored.
    """
    run = StartupRun(build)
    run.start()
    run.thread.join(timeout=60)
    result = run.poll()
    assert result is not None, "startup worker did not finish"
    return result
