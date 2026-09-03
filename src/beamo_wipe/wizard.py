# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen state machine. UI layers only render this. No auto-start wipe."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
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
    def erase_enabled(self) -> bool:
        return self.screen == Screen.LAST_CHANCE and self.countdown_left <= 0.0

    @property
    def progress(self) -> Optional[float]:
        return getattr(self.runner, "progress", None)

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
                if result is not None:
                    should_finish = result
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
        self._advanced_from = None
        self.log_text = ""
        self._done_keyboard_armed = False
        # Preserve evidence file on disk; clear in-memory start markers only
        self._evidence_start_wall = None
        self._evidence_start_mono = None
        self._evidence_argv = None
        self._evidence_written_for = None
        # evidence / evidence_path / evidence_error are kept for audit

    def shutdown(self) -> None:
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
                self.error = f"{self.discovery.error} ({diag})"
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
        # Persist auditable evidence (atomic, off-target, truthful outcome)
        self._write_evidence(result=result, cancelled=False, interrupted=False)

    def cancel_wipe(self) -> None:
        """User or system interruption. Produce interrupted evidence."""
        try:
            self.runner.cancel()
        except Exception as exc:
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

            res = _WR(ok=False, exit_code=143, summary="interrupted", logfile=self._wipe_request.logfile)
            # _write_evidence and _finish outside lock to avoid I/O under lock
            need_evidence = res
        self._write_evidence(result=need_evidence, cancelled=True, interrupted=True)
        self._finish(need_evidence)

    def _write_evidence(
        self, *, result: Optional[WipeResult], cancelled: bool, interrupted: bool
    ) -> None:
        """Build and atomically persist evidence. Never raises to caller."""
        # Deduplicate: poll may deliver same result twice
        key = None
        try:
            key = f"{(self._wipe_request.logfile if self._wipe_request else '')}:{(result.exit_code if result else 'start')}:{(result.summary if result else '')}"
        except Exception:
            key = None
        if key is not None and self._evidence_written_for == key:
            return
        try:
            from beamo_wipe.evidence import build_evidence, write_evidence_atomic

            # Gather log tail for checksum (best effort, off-target)
            log_text = ""
            try:
                # Prefer runner's _log_tail if available, else read file
                log_text = getattr(self.runner, "_log_tail", "") or ""
                if not log_text and self._wipe_request and self._wipe_request.logfile:
                    try:
                        with open(self._wipe_request.logfile, "r", encoding="utf-8", errors="replace") as fh:
                            # Last 8 KiB is enough for checksum; full log stays in logfile
                            fh.seek(0, 2)
                            size = fh.tell()
                            fh.seek(max(0, size - 8192))
                            log_text = fh.read()
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
                import json as _json

                with open(path, "r", encoding="utf-8") as _fh:
                    written = _json.load(_fh)
                ev["provenance"] = written.get("provenance", ev["provenance"])
            except Exception as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("wizard", "provenance_reload_failed", type(exc).__name__)
                except Exception:
                    pass
                ev["provenance"]["evidence_file"] = str(path)
            self.evidence = ev
            self.evidence_path = str(path)
            self.evidence_error = None
            if key is not None:
                self._evidence_written_for = key
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
        except SafetyError as exc:
            self.evidence_error = str(exc)
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("wizard", "evidence_safety_error", str(exc)[:120])
            except Exception:
                pass
        except Exception as exc:
            self.evidence_error = f"Could not write evidence: {exc}"
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
    def done_ok(self) -> bool:
        return bool(self.wipe_result and self.wipe_result.ok)

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
        mapping = {
            Screen.OWNER: Screen.WHAT,
            Screen.PICK: Screen.OWNER,
            Screen.PICK_EMPTY: Screen.OWNER,
            Screen.PICK_BLOCKED: Screen.OWNER,
            Screen.CONFIRM: Screen.PICK,
            Screen.METHOD: Screen.CONFIRM,
            Screen.LAST_CHANCE: Screen.METHOD,
            Screen.ADVANCED: self._advanced_from or Screen.METHOD,
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

    def erase_label(self) -> str:
        if self.selected is None:
            return "Erase now"
        return erase_now_label(self.selected)


def make_demo_wizard(*args, **kwargs):
    from beamo_wipe.demo import make_demo_wizard as _make

    return _make(*args, **kwargs)
