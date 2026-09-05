# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen state machine. UI layers only render this. No auto-start wipe."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

from beamo_wipe.copy import REDISCOVER_ERROR, confirm_warning, erase_now_label
from beamo_wipe.methods import DEFAULT_METHOD, METHODS
from beamo_wipe.models import (
    ConfirmSpec,
    Disk,
    DiscoveryResult,
    MethodId,
    Screen,
    WipeRequest,
    WipeResult,
)
from beamo_wipe.discover import discover
from beamo_wipe.safety import (
    SafetyError,
    assert_boot_excluded,
    assert_disk_identity,
    assert_ready_to_wipe,
    confirm_spec,
    listed_disks as safety_listed_disks,
    selectable_disks,
    token_matches,
)
from beamo_wipe.nwipe_runner import NwipeRunner, build_nwipe_argv


class Runner(Protocol):
    progress: Optional[float]
    result: Optional[WipeResult]

    def start(self, request: WipeRequest) -> None: ...
    def poll(self, request: WipeRequest) -> Optional[WipeResult]: ...
    def cancel(self) -> None: ...


COUNTDOWN_S = 5.0
SPLASH_S = 3.0


@dataclass(frozen=True)
class ReportView:
    """One locked, immutable snapshot of the Done-screen report state."""

    revision: int
    status: str
    message: str
    session: str
    exporting: bool
    can_save: bool
    evidence_error: Optional[str]


@dataclass(frozen=True)
class _ReportExportClaim:
    """Evidence/result identity captured before an export worker starts."""

    evidence_path: Path
    evidence_sha256: str
    evidence_write_seq: int
    wipe_result: WipeResult
    discovery: DiscoveryResult
    target_path: str
    target_rdev: int
    boot_rdev: int


def format_progress_percent(pct: float) -> str:
    """Integer percent that never shows 100% before the engine reports 100.

    ``f"{99.5:.0f}"`` is ``100`` (round half away from zero). That would
    tell the owner the wipe is done while nwipe is still writing.
    """
    if pct >= 100.0:
        return "100%"
    if pct <= 0.0:
        return "0%"
    return f"{int(pct)}%"


class Wizard:
    def __init__(
        self,
        discovery: DiscoveryResult,
        runner: Runner,
        clock: Callable[[], float] | None = None,
        dry_run: bool = True,
        rediscover: Callable[[], DiscoveryResult] | None = None,
        wall_clock: Callable[[], str] | None = None,
        report_exporter: Optional[Callable[..., object]] = None,
    ) -> None:
        self.discovery = discovery
        self.runner = runner
        self._clock = clock or time.monotonic
        self.dry_run = dry_run
        self._rediscover = rediscover
        self._wall_clock = wall_clock  # for testing; default is evidence._iso_now_wall
        if dry_run:
            os.environ.setdefault("BEAMO_WIPE_DRY_RUN", "1")
        self.preview = False
        self.screen = Screen.SPLASH
        self.owner_ok = False
        self.selected: Optional[Disk] = None
        self.confirm_input = ""
        self.method = DEFAULT_METHOD
        self.wants_shutdown = False
        self.error: Optional[str] = None
        self.wipe_result: Optional[WipeResult] = None
        self._splash_until = self._clock() + SPLASH_S
        self._erase_until: Optional[float] = None
        self._wipe_request: Optional[WipeRequest] = None
        # Set when cancel_wipe starts (under _lock, before runner.cancel())
        # so a concurrent tick() drops the post-cancel poll result instead
        # of finishing with a misleading engine-'failed' outcome.
        self._cancel_requested = False
        self._advanced_from: Optional[Screen] = None
        self.log_text = ""
        self._done_keyboard_armed = False
        # Evidence bookkeeping (auditable, off-target)
        self._evidence_start_wall: Optional[str] = None
        self._evidence_start_mono: Optional[float] = None
        self._evidence_argv: Optional[list[str]] = None
        self.evidence: Optional[dict] = None  # type: ignore[type-arg]
        self.evidence_path: Optional[str] = None
        self.evidence_error: Optional[str] = None
        self._evidence_written_for: Optional[str] = None  # deduplicate poll
        # First-writer-wins interruption flags per dedup key: if the first
        # write for a result fails transiently, _finish's rewrite must keep
        # the original cancelled/interrupted flags, never downgrade a user
        # interrupt to an engine outcome.
        self._evidence_flag_hint: dict[str, tuple[bool, bool]] = {}
        self._evidence_write_seq = 0
        self._report_exporter = report_exporter
        self.report_status = "idle"  # idle | saving | saved | error
        self.report_message = ""
        self.report_session = ""
        self._report_exporting = False
        self._report_revision = 0
        self._active_report_claim: Optional[_ReportExportClaim] = None
        self._lock = threading.RLock()

    @property
    def now(self) -> float:
        return self._clock()

    @property
    def selectable(self):
        return selectable_disks(self.discovery)

    @property
    def listed_disks(self):
        """Boot (marked) plus selectable targets. Nothing else is shown."""
        return safety_listed_disks(self.discovery)

    @property
    def confirm(self) -> Optional[ConfirmSpec]:
        if self.selected is None:
            return None
        return confirm_spec(self.selected, self.listed_disks)

    @property
    def token_ok(self) -> bool:
        spec = self.confirm
        if spec is None:
            return False
        return token_matches(self.confirm_input, spec)

    @property
    def countdown_left(self) -> float:
        if self._erase_until is None:
            return COUNTDOWN_S
        return max(0.0, self._erase_until - self.now)

    @property
    def countdown_display(self) -> int:
        """Whole seconds shown to the owner. Never 0 while the gate blocks.

        The erase gate (erase_enabled) is authoritative; the display must
        never understate the remaining wait, so clamp to at least 1 until
        the gate opens.
        """
        if self.erase_enabled:
            return 0
        return max(1, math.ceil(self.countdown_left))

    @property
    def erase_enabled(self) -> bool:
        return self.screen == Screen.LAST_CHANCE and self.countdown_left <= 0.0

    @property
    def progress(self) -> Optional[float]:
        return getattr(self.runner, "progress", None)

    @staticmethod
    def _result_evidence_key(result: WipeResult) -> str:
        return f"{result.logfile}:{result.exit_code}:{result.summary}"

    def _set_report_state_locked(
        self,
        *,
        status: Optional[str] = None,
        message: Optional[str] = None,
        session: Optional[str] = None,
        exporting: Optional[bool] = None,
    ) -> None:
        """Publish report fields as one revision while ``_lock`` is held."""
        changed = False
        updates = (
            ("report_status", status),
            ("report_message", message),
            ("report_session", session),
            ("_report_exporting", exporting),
        )
        for name, value in updates:
            if value is not None and getattr(self, name) != value:
                setattr(self, name, value)
                changed = True
        if changed:
            self._report_revision += 1

    def _touch_report_locked(self) -> None:
        """Notify renderers that evidence-dependent report state changed."""
        self._report_revision += 1

    def tick(self) -> None:
        if (
            self.screen == Screen.SPLASH
            and not self.preview
            and self.now >= self._splash_until
        ):
            self.screen = Screen.WHAT
        # Poll under lock to avoid races with cancel_wipe / confirm_erase
        # that both touch _wipe_request / screen / evidence.
        should_finish = None
        with self._lock:
            if self.screen == Screen.WORKING and self._wipe_request is not None:
                result = self.runner.poll(self._wipe_request)
                if result is not None and not self._cancel_requested:
                    should_finish = result
                # When a cancel is in flight, drop the poll result: the
                # post-cancel runner state is not an engine verdict, and
                # finishing with it would lose the user's cancel (evidence
                # would say engine-'failed' instead of 'interrupted').
        if should_finish is not None:
            self._finish(should_finish)

    def skip_splash(self) -> None:
        if self.screen == Screen.SPLASH:
            self.screen = Screen.WHAT

    def reset_for_preview(self) -> None:
        """Start the wizard over. Preview only — never used on a live wipe."""
        from beamo_wipe.nwipe_runner import DryRunRunner

        fail = bool(getattr(self.runner, "fail", False))
        duration = float(getattr(self.runner, "duration_s", 8.0))
        self.runner = DryRunRunner(duration_s=duration, fail=fail)
        self.screen = Screen.SPLASH
        self.owner_ok = False
        self.selected = None
        self.confirm_input = ""
        self.method = DEFAULT_METHOD
        self.wants_shutdown = False
        self.error = None
        self.wipe_result = None
        self._splash_until = self.now + SPLASH_S
        self._erase_until = None
        self._wipe_request = None
        self._cancel_requested = False
        self._advanced_from = None
        self.log_text = ""
        self._done_keyboard_armed = False
        # Preserve evidence file on disk; clear in-memory start markers only
        self._evidence_start_wall = None
        self._evidence_start_mono = None
        self._evidence_argv = None
        self._evidence_written_for = None
        self._evidence_flag_hint = {}
        with self._lock:
            self._active_report_claim = None
            self._set_report_state_locked(
                status="idle", message="", session="", exporting=False
            )
        # evidence / evidence_path / evidence_error are kept for audit

    def shutdown(self) -> None:
        with self._lock:
            if self._report_exporting:
                self._set_report_state_locked(
                    message="Wait for the report USB to finish before shutting down."
                )
                return
            self.wants_shutdown = True

    def arm_done_keyboard(self) -> None:
        """Allow Enter on Done / empty / blocked after the confirming key is up."""
        if self.screen in (Screen.DONE, Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            self._done_keyboard_armed = True

    def accept_done_keyboard(self) -> None:
        """Enter on Done, empty, or blocked. Ignored while Return is still held."""
        if self.screen not in (Screen.DONE, Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            return
        if not self._done_keyboard_armed:
            return
        if self.screen == Screen.DONE and self.preview:
            self.reset_for_preview()
        else:
            self.shutdown()

    def accept_what(self) -> None:
        if self.screen != Screen.WHAT:
            return
        self.screen = Screen.OWNER

    def set_owner(self, checked: bool) -> None:
        self.owner_ok = bool(checked)

    def continue_owner(self) -> None:
        if self.screen != Screen.OWNER or not self.owner_ok:
            return
        self._enter_pick()

    def _enter_pick(self) -> None:
        self._done_keyboard_armed = False
        if not self.discovery.boot_identified or self.discovery.error:
            self.screen = Screen.PICK_BLOCKED
            # Surface diagnostic for maintainers while keeping UI generic and actionable
            diag = getattr(self.discovery, "diagnostic", None)
            if diag:
                # Discovery diagnostics can contain command/OS details. Keep
                # the owner-facing kiosk message generic and write only the
                # bounded sanitized diagnostic to the protected support log.
                self.error = self.discovery.error
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("wizard", "pick_blocked", diag)
                except Exception:
                    pass
            else:
                self.error = self.discovery.error
            return
        try:
            assert_boot_excluded(self.discovery)
        except SafetyError as exc:
            self.screen = Screen.PICK_BLOCKED
            self.error = str(exc)
            return
        if not self.selectable:
            self.screen = Screen.PICK_EMPTY
            return
        self.screen = Screen.PICK

    def select_disk(self, path: str) -> None:
        if self.screen != Screen.PICK:
            return
        want = os.path.realpath(path)
        boot = self.discovery.boot
        if boot is not None and os.path.realpath(boot.path) == want:
            return
        for disk in self.selectable:
            if os.path.realpath(disk.path) == want:
                self.selected = disk
                return

    def move_selection(self, delta: int) -> None:
        """Move the pick-list highlight. First Up/Down chooses an edge disk."""
        if self.screen != Screen.PICK:
            return
        selectable = sorted(self.selectable, key=lambda d: d.path)
        if not selectable:
            return
        paths = [d.path for d in selectable]
        if self.selected is None or self.selected.path not in paths:
            idx = 0 if delta >= 0 else len(paths) - 1
        else:
            idx = paths.index(self.selected.path) + delta
            idx = max(0, min(len(paths) - 1, idx))
        self.select_disk(paths[idx])

    def continue_pick(self) -> None:
        if self.screen != Screen.PICK or self.selected is None or self.selected.is_boot:
            return
        want = os.path.realpath(self.selected.path)
        if want not in {os.path.realpath(d.path) for d in self.selectable}:
            return
        if self.discovery.boot is not None:
            if want == os.path.realpath(self.discovery.boot.path):
                return
        self.confirm_input = ""
        self.screen = Screen.CONFIRM

    def set_confirm_input(self, text: str) -> None:
        if self.screen != Screen.CONFIRM:
            return
        self.confirm_input = text

    def continue_confirm(self) -> None:
        if self.screen != Screen.CONFIRM or not self.token_ok:
            return
        self.screen = Screen.METHOD

    def set_method(self, method: MethodId) -> None:
        if self.screen != Screen.METHOD:
            return
        if method not in METHODS:
            return
        self.method = method

    def continue_method(self) -> None:
        if self.screen != Screen.METHOD:
            return
        self.screen = Screen.LAST_CHANCE
        self._erase_until = self.now + COUNTDOWN_S

    def confirm_erase(self) -> None:
        with self._lock:
            # Double-start guard first: a second caller blocked on _lock
            # arrives after the first moved to WORKING. Refuse it with a
            # visible error (checking LAST_CHANCE first would silently
            # swallow it, since the screen is already WORKING).
            if self.screen == Screen.WORKING and self._wipe_request is not None:
                self.error = "A wipe is already running."
                return
            if self.screen != Screen.LAST_CHANCE:
                return
            if not self.erase_enabled or self.selected is None:
                return
            if (self.dry_run or self.preview) and isinstance(self.runner, NwipeRunner):
                self.error = "Preview and dry-run cannot exec nwipe."
                return
            # We already hold the lock; keep it for the whole start
            # sequence to prevent a second thread from also passing the
            # guard and double-starting the wipe. The rediscover I/O
            # could be slow, but it is bounded (lsblk timeout) and the
            # critical section is short; correctness wins.
            discovery = self.discovery
            disk = self.selected
            if not self.dry_run and not self.preview:
                try:
                    discovery = (self._rediscover or discover)()
                except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError, AttributeError) as exc:
                    self.error = f"Could not re-read disks: {exc}"
                    return
                except Exception as exc:  # noqa: BLE001 — fail closed on any rediscover error
                    self.error = f"Could not re-read disks: {exc}"
                    return
                if not discovery.boot_identified or discovery.boot is None:
                    self.error = REDISCOVER_ERROR
                    return
                try:
                    assert_boot_excluded(discovery)
                    assert_disk_identity(disk, discovery)
                except SafetyError as exc:
                    self.error = str(exc)
                    return
                self.discovery = discovery
                try:
                    disk = next(
                        d
                        for d in selectable_disks(discovery)
                        if os.path.realpath(d.path) == os.path.realpath(disk.path)
                    )
                except StopIteration:
                    self.error = "Selected disk is not in the safe list."
                    return
                self.selected = disk
            try:
                request = assert_ready_to_wipe(
                    owner_ok=self.owner_ok,
                    disk=disk,
                    discovery=discovery,
                    typed_token=self.confirm_input,
                    countdown_complete=self.countdown_left <= 0.0,
                    method=self.method,
                )
                build_nwipe_argv(request)
                self.runner.start(request)
            except SafetyError as exc:
                self.error = str(exc)
                return
            except OSError as exc:
                self.error = f"Could not start nwipe: {exc}"
                return
            self.error = None
            self._wipe_request = request
            self._cancel_requested = False
            self._evidence_written_for = None
            self._evidence_flag_hint = {}
            self.screen = Screen.WORKING
            # Record evidence start (wall + monotonic) + redacted argv for later completion
            try:
                from beamo_wipe.evidence import _iso_now_wall

                wall = self._wall_clock() if self._wall_clock else _iso_now_wall()  # type: ignore[misc]
            except Exception:
                wall = ""
            self._evidence_start_wall = wall
            self._evidence_start_mono = self.now
            try:
                # Build redacted argv now (never contains secrets; already sanitized)
                self._evidence_argv = list(build_nwipe_argv(request))
            except Exception:
                self._evidence_argv = []
            # Write initial started evidence (atomic, off-target)
            # Do not hold the lock during file I/O; copy needed state
            # and release lock before writing.
            pass
        # Outside the lock: write evidence without holding _lock during I/O
        # (prevents deadlock if evidence write calls back into wizard)
        self._write_evidence(result=None, cancelled=False, interrupted=False)

    def _finish(self, result: WipeResult) -> None:
        # Guard against double-finish from concurrent tick/cancel
        with self._lock:
            if self.screen == Screen.DONE and self.wipe_result is not None:
                return
            self.wipe_result = result
            self.screen = Screen.DONE
            self._done_keyboard_armed = False
            self.log_text = result.summary
            self._active_report_claim = None
            self._set_report_state_locked(
                status="idle", message="", session="", exporting=False
            )
        # Persist auditable evidence (atomic, off-target, truthful outcome)
        self._write_evidence(result=result, cancelled=False, interrupted=False)

    def cancel_wipe(self) -> None:
        """User or system interruption. Produce interrupted evidence."""
        with self._lock:
            if self._wipe_request is None or self.screen != Screen.WORKING:
                return
            # Claim the finish before touching the runner: a concurrent
            # tick() must drop the post-cancel poll result (see tick())
            # instead of recording an engine-'failed' outcome.
            self._cancel_requested = True
        try:
            self.runner.cancel()
        except Exception as exc:
            with self._lock:
                # Cancel failed: release the claim so tick() resumes
                # delivering real outcomes while the engine may still run.
                self._cancel_requested = False
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("wizard", "cancel_runner_failed", type(exc).__name__)
            except Exception:
                pass
            # Fail closed: the engine may still hold the disk. Stay on
            # WORKING so tick() can still deliver the real outcome (or the
            # user can retry), and surface the failure instead of writing a
            # clean 'interrupted' outcome for a wipe that may still run.
            self.error = f"Could not stop the wipe: {exc}"
            return
        # Hold lock while checking and transitioning to avoid race with
        # tick()->_finish.
        with self._lock:
            if self._wipe_request is None or self.screen != Screen.WORKING:
                return
            from beamo_wipe.models import WipeResult as _WR

            observed = getattr(self.runner, "result", None)
            if observed is not None and (
                observed.ok
                or (observed.summary or "").strip().casefold()
                not in {"cancelled", "interrupted"}
            ):
                # poll() completed while cancel() was waiting. Preserve the
                # engine's real outcome instead of relabelling it interrupted.
                res = observed
                cancelled = interrupted = False
            else:
                res = _WR(ok=False, exit_code=143, summary="interrupted", logfile=self._wipe_request.logfile)
                cancelled = interrupted = True
            # _write_evidence and _finish outside lock to avoid I/O under lock
            need_evidence = res
        self._write_evidence(
            result=need_evidence, cancelled=cancelled, interrupted=interrupted
        )
        self._finish(need_evidence)
        self.arm_done_keyboard()

    def _write_evidence(
        self, *, result: Optional[WipeResult], cancelled: bool, interrupted: bool
    ) -> None:
        """Build and atomically persist evidence. Never raises to caller."""
        # Deduplicate: poll may deliver same result twice
        key = None
        try:
            key = (
                self._result_evidence_key(result)
                if result is not None
                else f"{(self._wipe_request.logfile if self._wipe_request else '')}:start:"
            )
        except Exception:
            key = None
        with self._lock:
            if key is not None and self._evidence_written_for == key:
                return
            if key is not None:
                # First writer wins: a later rewrite of the same result (e.g.
                # _finish after a transient write failure in cancel_wipe) keeps
                # the original interruption flags instead of downgrading them.
                prev = self._evidence_flag_hint.setdefault(key, (cancelled, interrupted))
                cancelled, interrupted = prev
            self._evidence_write_seq += 1
            write_seq = self._evidence_write_seq
        try:
            from beamo_wipe.evidence import build_evidence, write_evidence_atomic

            # Gather log tail for checksum (best effort, off-target)
            log_text = ""
            try:
                # Prefer runner's _log_tail if available, else read file
                log_text = getattr(self.runner, "_log_tail", "") or ""
                if not log_text and self._wipe_request and self._wipe_request.logfile:
                    try:
                        fd = os.open(
                            self._wipe_request.logfile,
                            os.O_RDONLY | os.O_NOFOLLOW,
                        )
                        try:
                            opened = os.fstat(fd)
                            if not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid():
                                raise OSError("unsafe wipe log")
                            with os.fdopen(fd, "rb") as fh:
                                fd = -1
                                fh.seek(0, 2)
                                size = fh.tell()
                                fh.seek(max(0, size - 8192))
                                log_text = fh.read().decode("utf-8", errors="replace")
                        finally:
                            if fd >= 0:
                                os.close(fd)
                    except OSError as exc:
                        try:
                            from beamo_wipe.diagnostics import log_diag

                            log_diag("wizard", "evidence_log_tail_failed", type(exc).__name__)
                        except Exception:
                            pass
                        log_text = log_text or ""
                if not log_text:
                    log_text = self.log_text or (result.summary if result else "")
            except Exception as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("wizard", "evidence_log_gather_failed", type(exc).__name__)
                except Exception:
                    pass
                log_text = ""

            # Wall clocks
            try:
                from beamo_wipe.evidence import _iso_now_wall

                end_wall = self._wall_clock() if self._wall_clock else _iso_now_wall()  # type: ignore[misc]
            except Exception as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("wizard", "wall_clock_failed", type(exc).__name__)
                except Exception:
                    pass
                end_wall = ""
            start_wall = self._evidence_start_wall or ""
            start_mono = self._evidence_start_mono
            end_mono = self.now if result is not None else None
            # If STARTED evidence has no start yet, use current as both
            if start_wall == "" and result is None and self._wipe_request is not None:
                start_wall = end_wall
                start_mono = self.now

            argv = self._evidence_argv
            # Fallback: rebuild from request if argv missing (e.g., after restart)
            if argv is None and self._wipe_request is not None:
                try:
                    from beamo_wipe.nwipe_runner import build_nwipe_argv

                    argv = list(build_nwipe_argv(self._wipe_request))
                except Exception as exc:
                    try:
                        from beamo_wipe.diagnostics import log_diag

                        log_diag("wizard", "argv_rebuild_failed", type(exc).__name__)
                    except Exception:
                        pass
                    argv = []

            ev = build_evidence(
                disk=self.selected,
                discovery=self.discovery,
                method=self.method,
                request=self._wipe_request,
                result=result,
                started_at_wall=start_wall,
                ended_at_wall=end_wall if result is not None else "",
                started_mono=start_mono,
                ended_mono=end_mono,
                argv=argv,
                log_text=log_text or "",
                interrupted=interrupted,
                cancelled=cancelled,
            )
            target = self._wipe_request.device if self._wipe_request else ""
            # Use the same log dir that produced the request (monkeypatched in tests)
            try:
                import beamo_wipe.safety as _safety

                log_dir = _safety.default_log_dir()
            except Exception:
                log_dir = None
            path = write_evidence_atomic(ev, log_dir=log_dir, device_path=target or (self.selected.path if self.selected else ""), target_device=target)
            # Reload provenance from file to ensure evidence_file matches written file
            try:
                from beamo_wipe.evidence import load_evidence

                written = load_evidence(path)
                ev["provenance"] = written.get("provenance", ev["provenance"])
            except Exception as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("wizard", "provenance_reload_failed", type(exc).__name__)
                except Exception:
                    pass
                ev["provenance"]["evidence_file"] = str(path)
            # Also expose checksum for UI (already in evidence, but handy)
            try:
                from beamo_wipe.evidence import verify_evidence_checksum

                ev["provenance"]["verified"] = verify_evidence_checksum(path)
            except Exception as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("wizard", "checksum_verify_failed", type(exc).__name__)
                except Exception:
                    pass
            with self._lock:
                if write_seq != self._evidence_write_seq:
                    return
                self.evidence = ev
                self.evidence_path = str(path)
                self.evidence_error = None
                if key is not None:
                    self._evidence_written_for = key
                self._touch_report_locked()
        except SafetyError as exc:
            with self._lock:
                if write_seq == self._evidence_write_seq:
                    self.evidence_error = str(exc)
                    self._touch_report_locked()
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("wizard", "evidence_safety_error", str(exc)[:120])
            except Exception:
                pass
        except Exception as exc:
            with self._lock:
                if write_seq == self._evidence_write_seq:
                    self.evidence_error = f"Could not write evidence: {exc}"
                    self._touch_report_locked()
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("wizard", "evidence_write_failed", f"{type(exc).__name__}: {str(exc)[:120]}")
            except Exception:
                pass

    def export_evidence(self, dest_dir: str) -> str:
        """Copy evidence JSON + sidecar to a second USB directory. Returns dest path or raises."""
        if not self.evidence_path:
            raise SafetyError("No evidence to export")
        from pathlib import Path

        from beamo_wipe.evidence import export_evidence as _export

        src = Path(self.evidence_path)
        dest = Path(dest_dir)
        target = self._wipe_request.device if self._wipe_request else (self.selected.path if self.selected else "")
        boot = self.discovery.boot.path if self.discovery.boot else ""
        out = _export(src, dest, target_device=target, boot_device=boot)
        return str(out)

    @property
    def can_save_report(self) -> bool:
        """True only for the current, checksum-verified terminal evidence."""
        with self._lock:
            return self._can_save_report_locked()

    def _can_save_report_locked(self) -> bool:
        result = self.wipe_result
        evidence = self.evidence
        path = self.evidence_path
        if (
            self.preview
            or self.screen != Screen.DONE
            or result is None
            or self.evidence_error
            or not path
            or not isinstance(evidence, dict)
            or self._report_exporting
            or self.report_status == "saved"
            or self._evidence_written_for != self._result_evidence_key(result)
        ):
            return False
        outcome = evidence.get("outcome")
        if result.ok:
            if outcome not in {"completed", "verified"}:
                return False
        elif outcome not in {"failed", "interrupted"}:
            return False
        exit_evidence = evidence.get("exit_evidence")
        if (
            not isinstance(exit_evidence, dict)
            or type(exit_evidence.get("exit_code")) is not int
            or exit_evidence["exit_code"] != result.exit_code
        ):
            return False
        provenance = evidence.get("provenance")
        return bool(
            isinstance(provenance, dict)
            and provenance.get("verified") is True
            and provenance.get("evidence_file") == path
        )

    @property
    def report_view(self) -> ReportView:
        """Return one coherent report snapshot for a complete UI render."""
        with self._lock:
            return ReportView(
                revision=self._report_revision,
                status=self.report_status,
                message=self.report_message,
                session=self.report_session,
                exporting=self._report_exporting,
                can_save=self._can_save_report_locked(),
                evidence_error=self.evidence_error,
            )

    def _claim_report_export(self) -> Optional[_ReportExportClaim]:
        """Verify and bind one attempt to the exact current evidence bytes."""
        with self._lock:
            if self._report_exporting:
                return None
            if not self._can_save_report_locked():
                if self.report_status != "saved":
                    self._set_report_state_locked(
                        status="error",
                        message="A current finished wipe report is not available.",
                    )
                return None
            path = Path(self.evidence_path or "")
            evidence_write_seq = self._evidence_write_seq
            result = self.wipe_result
            assert result is not None
            discovery_snapshot = copy.deepcopy(self.discovery)
            assert self.evidence is not None
            expected_payload = dict(self.evidence)
            expected_provenance = dict(expected_payload.get("provenance", {}))
            # ``verified`` is a post-write UI convenience; it is not present
            # in the immutable JSON bytes whose sidecar was verified.
            expected_provenance.pop("verified", None)
            expected_payload["provenance"] = expected_provenance
            if self._wipe_request is not None:
                target = self._wipe_request.device
                target_rdev = self._wipe_request.device_rdev
                boot_rdev = self._wipe_request.boot_rdev
            else:
                target = self.selected.path if self.selected is not None else ""
                target_rdev = 0
                boot_rdev = 0

        try:
            from beamo_wipe.support_export import prepare_terminal_evidence

            verified = prepare_terminal_evidence(path, target)
            payload = json.loads(verified.data.decode("utf-8"))
        except (SafetyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            with self._lock:
                if not self._report_exporting:
                    self._set_report_state_locked(status="error", message=str(exc))
            return None

        claim = _ReportExportClaim(
            evidence_path=path,
            evidence_sha256=verified.sha256,
            evidence_write_seq=evidence_write_seq,
            wipe_result=result,
            discovery=discovery_snapshot,
            target_path=target,
            target_rdev=target_rdev,
            boot_rdev=boot_rdev,
        )
        with self._lock:
            current_target = (
                self._wipe_request.device
                if self._wipe_request is not None
                else (self.selected.path if self.selected is not None else "")
            )
            if (
                self._report_exporting
                or not self._can_save_report_locked()
                or self.evidence is None
                or self._evidence_write_seq != evidence_write_seq
                or self.evidence_path != str(path)
                or self.wipe_result != result
                or self.discovery != discovery_snapshot
                or current_target != target
                or not isinstance(payload, dict)
                or payload != expected_payload
                or {
                    **self.evidence,
                    "provenance": {
                        key: value
                        for key, value in self.evidence["provenance"].items()
                        if key != "verified"
                    },
                }
                != expected_payload
                or payload.get("logfile") != result.logfile
            ):
                self._set_report_state_locked(
                    status="error",
                    message="The finished wipe report changed before it could be saved.",
                )
                return None
            self._active_report_claim = claim
            self._done_keyboard_armed = False
            self._set_report_state_locked(
                status="saving",
                message="Saving and verifying the report USB. Leave it connected.",
                session="",
                exporting=True,
            )
            return claim

    def _perform_report_export(self, claim: _ReportExportClaim) -> None:
        final_status = "error"
        final_message = "The report export failed. Shut down before removing the USB."
        final_session = ""
        try:
            exporter = self._report_exporter
            if exporter is None:
                from beamo_wipe.support_export import export_to_new_usb

                exporter = export_to_new_usb
            receipt = exporter(
                evidence_path=claim.evidence_path,
                discovery=claim.discovery,
                target_path=claim.target_path,
                target_rdev=claim.target_rdev,
                boot_rdev=claim.boot_rdev,
                expected_evidence_sha256=claim.evidence_sha256,
            )
            ok = getattr(receipt, "ok", None) is True
            safe = getattr(receipt, "safe_to_remove", None) is True
            code = getattr(receipt, "code", None)
            receipt_hash = getattr(receipt, "evidence_sha256", None)
            session = str(getattr(receipt, "session_name", "") or "")
            if (
                ok
                and safe
                and code == "saved_verified_unmounted"
                and receipt_hash == claim.evidence_sha256
                and re.fullmatch(r"report-[0-9a-f]{24}", session) is not None
            ):
                final_status = "saved"
                final_session = session
                final_message = (
                    "Report saved and verified. The report USB is safe to remove."
                )
            else:
                final_message = (
                    "The report was not saved and verified. "
                    "Shut down before removing the USB."
                )
        except SafetyError as exc:
            final_message = str(exc)
        except Exception as exc:  # noqa: BLE001 - keep failure visible on Done
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("wizard", "report_export_failed", type(exc).__name__)
            except Exception:
                pass
        finally:
            with self._lock:
                current_target = (
                    self._wipe_request.device
                    if self._wipe_request is not None
                    else (self.selected.path if self.selected is not None else "")
                )
                claim_is_current = (
                    self._active_report_claim == claim
                    and self._evidence_write_seq == claim.evidence_write_seq
                    and self.evidence_path == str(claim.evidence_path)
                    and self.wipe_result == claim.wipe_result
                    and self.discovery == claim.discovery
                    and current_target == claim.target_path
                )
                if final_status == "saved" and not claim_is_current:
                    final_status = "error"
                    final_message = (
                        "The finished wipe report changed while it was being saved. "
                        "Shut down before removing the USB."
                    )
                    final_session = ""
                # Publish the terminal UI state and re-enable Shutdown in one
                # lock transition so Tk cannot render a permanently disabled
                # button between two state changes.
                self._active_report_claim = None
                self._set_report_state_locked(
                    exporting=False,
                    status=final_status,
                    message=final_message,
                    session=final_session,
                )

    def save_report_to_usb(self) -> None:
        """Synchronously save a report. Used by console fallbacks and tests."""
        claim = self._claim_report_export()
        if claim is not None:
            self._perform_report_export(claim)

    def begin_report_export(self) -> bool:
        """Start a single background export for the graphical kiosk."""
        claim = self._claim_report_export()
        if claim is None:
            return False
        thread = threading.Thread(
            target=self._perform_report_export,
            args=(claim,),
            name="beamo-report-export",
            daemon=True,
        )
        try:
            thread.start()
        except Exception as exc:
            with self._lock:
                self._active_report_claim = None
                self._set_report_state_locked(
                    exporting=False,
                    status="error",
                    message="The report export could not start.",
                )
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("wizard", "report_thread_failed", type(exc).__name__)
            except Exception:
                pass
            return False
        return True

    @property
    def done_ok(self) -> bool:
        return bool(self.wipe_result and self.wipe_result.ok)

    def open_limits(self) -> None:
        if self.screen == Screen.METHOD:
            self.screen = Screen.LIMITS

    def close_limits(self) -> None:
        if self.screen == Screen.LIMITS:
            self.screen = Screen.METHOD

    @property
    def storage_notice(self) -> str:
        from beamo_wipe.models import DiskKind
        from beamo_wipe.storage_limits import notice

        return notice(self.selected.kind if self.selected else DiskKind.UNKNOWN)

    def open_advanced(self) -> None:
        if self.screen in (Screen.SPLASH, Screen.WORKING, Screen.ADVANCED):
            return
        self._advanced_from = self.screen
        self.screen = Screen.ADVANCED

    def close_advanced(self) -> None:
        if self.screen != Screen.ADVANCED:
            return
        self.screen = self._advanced_from or Screen.METHOD

    def back(self) -> None:
        # Under _lock like every other screen mutation: confirm_erase holds
        # the lock from its LAST_CHANCE gate through runner.start, so a
        # concurrent back() either wins (confirm then refuses, nothing
        # started) or waits and becomes a no-op once WORKING (no mapping).
        # Without this, a back-out landing mid-confirm leaves the UI on
        # METHOD while nwipe is already running.
        with self._lock:
            mapping = {
                Screen.OWNER: Screen.WHAT,
                Screen.PICK: Screen.OWNER,
                Screen.PICK_EMPTY: Screen.OWNER,
                Screen.PICK_BLOCKED: Screen.OWNER,
                Screen.CONFIRM: Screen.PICK,
                Screen.METHOD: Screen.CONFIRM,
                Screen.LAST_CHANCE: Screen.METHOD,
                Screen.ADVANCED: self._advanced_from or Screen.METHOD,
                Screen.LIMITS: Screen.METHOD,
            }
            if self.screen in mapping:
                self.screen = mapping[self.screen]
                if self.screen != Screen.LAST_CHANCE:
                    self._erase_until = None
                self.error = None

    def warning_text(self) -> str:
        if self.selected is None:
            return ""
        return confirm_warning(self.selected)

    @property
    def method_summary(self) -> str:
        return METHODS[self.method].summary

    @property
    def method_result(self) -> str:
        evidence = self.evidence or {}
        outcome = "preview" if self.preview else evidence.get("outcome", "unknown")
        verified = evidence.get("verification", {}).get("verified") is True
        return METHODS[self.method].result_description(outcome, verified=verified)

    def erase_label(self) -> str:
        if self.selected is None:
            return "Erase now"
        return erase_now_label(self.selected)


def make_demo_wizard(*args, **kwargs):
    from beamo_wipe.demo import make_demo_wizard as _make

    return _make(*args, **kwargs)
