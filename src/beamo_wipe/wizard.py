# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen state machine. UI layers only render this. No auto-start wipe."""

from __future__ import annotations

import copy
import errno
import json
import math
import os
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol

from beamo_wipe import copy as C
from beamo_wipe.copy import (
    confirm_warning,
    erase_now_label,
)
from beamo_wipe import keyboard as _keyboard
from beamo_wipe.keyboard import (
    DEFAULT_LAYOUT,
    apply_layout,
    is_allowed,
)
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
from beamo_wipe import safety as _safety
from beamo_wipe.safety import (
    SafetyError,
    assert_boot_excluded,
    assert_disk_identity,
    assert_ready_to_wipe,
    confirm_spec,
    disk_identity,
    listed_disks as safety_listed_disks,
    selectable_disks,
    token_matches,
)
from beamo_wipe.nwipe_runner import NwipeRunner, ProcessStatusError, build_nwipe_argv
from beamo_wipe import progress as _progress
from beamo_wipe.progress import ProgressTiming, ProgressView
from beamo_wipe.power import PowerMonitor, read_power


REPORT_HEAD_PREPARING = "Preparing the report"
REPORT_HEAD_UNCONFIRMED = "Report preparation could not be confirmed"
REPORT_HEAD_NOT_SAVED = "Report not saved to USB"
REPORT_HEAD_SAVING = "Saving and checking the report copy"
REPORT_HEAD_SAVED = "Report copy saved and checked"
REPORT_HEAD_FAILED = "Report copy could not be saved and checked"
REPORT_HEAD_UNKNOWN = "Report status could not be confirmed"
PREV_RESULT_NOTICE = "The previous result could not be confirmed. {notice}"
RECOVERY_MAY_RUNNING = "The erase may still be running. Keep disks connected. Contact support. "
RECOVERY_NO_RESTART = "No erase was restarted or resumed."
TERMINAL_EVIDENCE_MISSING = "No terminal evidence"
RECOVERY_UNAVAILABLE_MSG = "Recovery evidence is unavailable. The previous result could not be confirmed."
BOOT_USB_LINE = "Beamo USB (not erasable): {line}"
NO_DISK_SELECTED = "No disk is selected."
PREVIEW_POWER_PREFIX = "Preview power (not a hardware reading). "
CLEANUP_UNCONFIRMED = "Process status or cleanup could not be confirmed. The disk may still be erasing."
WAIT_REPORT_USB = "Wait for the report USB to finish before shutting down."
PREF_NOT_RECOVERED = "Report preference could not be recovered. Shutdown will ask before discarding reports."
PREF_RECOVERED = "Report preference recovered for this live session. Previous export success could not be confirmed."
PREF_RECOVERY_UNAVAILABLE = "Report preference recovery is unavailable. Keep this session open until you save the report."
CHECKING_AGAIN = "Checking disks again."
FAKE_SOURCE_REQUIRED = "A fresh fake-device discovery source is required."
INVALID_INVENTORY = "Discovery returned an invalid inventory."
BOOT_UNIDENTIFIED = "Boot device could not be identified."
ALREADY_RUNNING = "A wipe is already running."
PREVIEW_NO_EXEC = "Preview and dry-run cannot exec nwipe."
CHECKING_NO_START = "Disk checking could not start. Try again."
REREAD_FAILED = "Could not re-read disks. Erase did not start."
IDENTITY_UNCONFIRMED_MSG = "Disk identity could not be confirmed. Check disks again."
NOT_IN_SAFE_LIST = "Selected disk is not in the safe list."
CLOSED_DURING_CHECK = "Interface closed during disk checking. Erase did not start."
PREFLIGHT_BLOCKED = "The safety checks prevented startup. Check disks again or save a diagnostic report."
STARTUP_UNCONFIRMED = "Startup could not be confirmed. Save a diagnostic report for support."
TMP_NOT_WRITABLE = "Temporary storage is not writable."
TMP_NO_SPACE = "Temporary storage has no available space."
FINALIZE_UNCONFIRMED = "Report finalization could not be confirmed."
EVIDENCE_INVALID = "Report evidence did not pass validation."
TMP_IO_ERROR = "Temporary storage reported an I/O error."
TMP_IO_FAILED = "Temporary storage could not be read or written."
CHANGED_CONTEXT = "Changed evidence context"
EVIDENCE_UNVERIFIED = "Unverified evidence"
FOREIGN_PROVENANCE = "Foreign evidence provenance"
CONTRADICTORY_READBACK = "Contradictory evidence readback"
CHANGED_TERMINAL = "Changed terminal state"
EVIDENCE_NOT_SAVING = "Report evidence is not being saved. {error} The erase is still running."
EVIDENCE_SAVING = "Saving report evidence… The erase result is unchanged."
RETRY_SAVE_REMAINING = " Retry save ({remaining} left)."
KEEP_SESSION_OPEN = " Keep this session open and contact support."
TEMP_EVIDENCE_LOST = " Temporary evidence is lost at shutdown or power loss."


def error_needs_support(error: object) -> bool:
    """True when a wizard error refers the owner to support.

    Compares against the translated constants, never substrings, so the
    rule holds in every session language.
    """
    if not isinstance(error, str) or not error:
        return False
    from beamo_wipe.app import STARTUP_BLOCKED  # local: app imports wizard
    from beamo_wipe.outcomes import VIEWS

    return (
        error.startswith(RECOVERY_MAY_RUNNING)
        or error == STARTUP_BLOCKED
        or error == STARTUP_UNCONFIRMED
        or error == VIEWS["stop_unconfirmed"].announcement
    )
NO_EXPORT_EVIDENCE = "No current verified evidence to export"
NO_FINISHED_REPORT = "A current finished wipe report is not available."
EVIDENCE_UNREADABLE = "The saved wipe evidence could not be read. Try saving the report again."
REPORT_CHANGED_BEFORE_SAVE = "The finished wipe report changed before it could be saved."
REPORT_SAVING = "Saving and verifying the report USB. Leave it connected."
EXPORT_FAILED = "The report export failed. Shut down before removing the USB."
REPORT_NOT_SAVED = "The report was not saved and verified. Shut down before removing the USB."
REPORT_CHANGED_DURING_SAVE = "The finished wipe report changed while it was being saved. Shut down before removing the USB."
EXPORT_NO_START = "The report export could not start."
DIAG_VERIFYING = "Saving and verifying. Leave the USB connected."
DIAG_CHECKING = "Checking connected disks."
DIAG_NO_PREVIEW = "Diagnostic USB export is unavailable in preview or dry-run."
DIAG_BASELINE_READY = "Baseline checked. Now insert one new removable FAT32 USB and choose {action}."
DIAG_NOT_SAVED = "Diagnostic report was not saved and verified. Shut down before removing the USB."
DIAG_CONTEXT_CHANGED = "Startup status changed. Save a new diagnostic report before shutting down."
DIAG_FAILED = "Diagnostic export failed. Shut down before removing the USB."
DIAG_NO_START = "Diagnostic export could not start. Try again."
ERASE_STOPPED_BY_YOU = "The erase was stopped by you"
ERASE_INTERRUPTED_MSG = "The erase was interrupted"
ERASE_COMPLETION_UNCONFIRMED = "The erase process reported completion; the result could not be confirmed"
ERASE_UNFINISHED = "The erase did not finish"


if TYPE_CHECKING:
    from beamo_wipe.session_recovery import SessionStore


class Runner(Protocol):
    progress: Optional[float]
    result: Optional[WipeResult]

    def start(self, request: WipeRequest) -> None: ...
    def poll(self, request: WipeRequest) -> Optional[WipeResult]: ...
    def cancel(self) -> None: ...


COUNTDOWN_S = 5.0
SPLASH_S = 3.0
EVIDENCE_RETRIES = 3


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
    saving_evidence: bool = False
    can_retry_evidence: bool = False
    retries_remaining: int = 0
    evidence_status: str = "unknown"

    @property
    def headline(self) -> str:
        if self.saving_evidence:
            return REPORT_HEAD_PREPARING
        if self.evidence_error:
            return REPORT_HEAD_UNCONFIRMED
        return {
            "idle": REPORT_HEAD_NOT_SAVED,
            "saving": REPORT_HEAD_SAVING,
            "saved": REPORT_HEAD_SAVED,
            "error": REPORT_HEAD_FAILED,
        }.get(self.status, REPORT_HEAD_UNKNOWN)

    @property
    def tone(self) -> str:
        # Report warnings never reuse the red erase-failure badge, and a
        # saved copy never reuses the green erase-success badge: checking a
        # report copy is not disk read-back verification. The saved state
        # gets its own small in-panel treatment (Saved label, saved icon,
        # report wording). Only a fully saved copy takes the success tone.
        if self.evidence_error or self.status == "error":
            return "warn"
        if self.status == "saved" and not self.saving_evidence:
            return "ok"
        return "info"


@dataclass(frozen=True)
class DiagnosticView:
    revision: int
    message: str
    ready: bool
    busy: bool


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
    privacy_reduced: bool = False


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


_StartClaim = tuple[Disk, DiscoveryResult, bool, str, MethodId, bool]


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
        self.power = PowerMonitor(None if dry_run else read_power)
        self._rediscover = rediscover
        self._wall_clock = wall_clock  # for testing; default is evidence._iso_now_wall
        if dry_run:
            os.environ.setdefault("BEAMO_WIPE_DRY_RUN", "1")
        self.preview = False
        self.screen = Screen.SPLASH
        self.report_wanted = False
        self.report_share_redacted = False
        self.sound_output = ""
        self.sounds_enabled = False
        self.sound_message = ""
        self._sound_played_for: Optional[str] = None
        self._intent_store = None
        self.report_recovery_warning = ""
        self._shutdown_from: Optional[Screen] = None
        self.shutdown_generation = 0
        self._saved_report_claim: Optional[_ReportExportClaim] = None
        self._saved_diagnostic_context: Optional[tuple[str, DiscoveryResult]] = None
        self._report_help_from: Optional[Screen] = None
        self._refresh_confirm_from: Optional[Screen] = None
        self.owner_ok = False
        self.selected: Optional[Disk] = None
        self.confirm_input = ""
        self.keyboard_layout = DEFAULT_LAYOUT
        self.text_size = "standard"
        self.language = "en"
        self.typing_check = ""
        self.keyboard_message = ""
        self._keyboard_from: Optional[Screen] = None
        self._apply_keyboard = apply_layout
        self.method = DEFAULT_METHOD
        self.wants_shutdown = False
        self.wants_new_session = False
        self._new_session_pending = False
        self.error: Optional[str] = None
        self.wipe_result: Optional[WipeResult] = None
        self._splash_until = self._clock() + SPLASH_S
        self._erase_until: Optional[float] = None
        self._authorized_operation: Optional[tuple[Any, ...]] = None
        self._wipe_request: Optional[WipeRequest] = None
        # Set when cancel_wipe starts (under _lock, before runner.cancel())
        # so a concurrent tick() drops the post-cancel poll result instead
        # of finishing with a misleading engine-'failed' outcome.
        self._cancel_requested = False
        self.stop_confirmation: Optional[object] = None
        self._advanced_from: Optional[Screen] = None
        self.log_text = ""
        self._done_keyboard_armed = False
        # Evidence bookkeeping (auditable, off-target)
        self._evidence_start_wall: Optional[str] = None
        self._evidence_start_mono: Optional[float] = None
        self._evidence_end_mono: Optional[float] = None
        self._evidence_end_wall = ""
        self._evidence_wall_provenance = "unavailable"
        self._progress_timing = ProgressTiming(self._clock, time.time)
        self._display_progress: Optional[ProgressView] = None
        self._display_progress_at = 0.0
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
        self.evidence_status = "unknown"  # unknown | saving | saved | failed
        self.evidence_error_code = ""
        self._finishing = False
        self._evidence_saving = False
        self._evidence_retries = 0
        self._pending_evidence: Optional[tuple[dict[str, Any], Any, Optional[WipeResult], Optional[str]]] = None
        self._pending_evidence_path: Optional[Path] = None
        self._report_exporter = report_exporter
        self.report_status = "idle"  # idle | saving | saved | error
        self.report_message = ""
        self.report_session = ""
        self._report_exporting = False
        self._report_revision = 0
        self._active_report_claim: Optional[_ReportExportClaim] = None
        self._lock = threading.RLock()
        self._refresh_seq = 0
        self._start_claim: Optional[_StartClaim] = None
        self._start_abort = threading.Event()
        self._operation_thread: Optional[threading.Thread] = None
        self.startup_error_code = discovery.error_code
        self.diagnostic_ui = "graphical"
        self._session_started = time.monotonic()
        self.diagnostic_message = ""
        self._diagnostic_baseline = ()
        self._diagnostic_busy = False
        self._diagnostic_from = Screen.PICK_BLOCKED
        self._logged_support_identity = None
        self._startup_blocked = False
        self._session_store: Optional[SessionStore] = None
        self._recovered = False

    def enable_session_recovery(self, store) -> None:
        """Restore evidence only. No request, confirmation, PID or runner state."""
        self._session_store = store
        if not store.previous and not store.invalid:
            return
        from beamo_wipe.session_recovery import NOTICE
        self._recovered = True
        self._startup_blocked = True
        self.report_wanted = True
        self.owner_ok = False
        self.confirm_input = ""
        self._erase_until = None
        self._authorized_operation = None
        self._wipe_request = None
        self.screen = Screen.PICK_BLOCKED
        self.startup_error_code = "recovery_indeterminate"
        self.error = PREV_RESULT_NOTICE.format(notice=NOTICE)
        self.report_recovery_warning = NOTICE
        self._recover_when_quiescent()

    def _recover_when_quiescent(self) -> None:
        store = self._session_store
        if not self._recovered or store is None or self.wipe_result is not None:
            return
        try:
            if not store.is_quiescent():
                self.error = RECOVERY_MAY_RUNNING
                self.error += RECOVERY_NO_RESTART
                return
            if store.invalid or store.record is None or store.record["context"] is None:
                from beamo_wipe.session_recovery import NOTICE
                self.error = PREV_RESULT_NOTICE.format(notice=NOTICE)
                return
            context, discovery, target = store.context()
            self.discovery = discovery  # historical baseline protects every old disk
            self.selected = target
            self.method = MethodId(context["method"])
            try:
                if store.record["phase"] != "terminal":
                    raise SafetyError(TERMINAL_EVIDENCE_MISSING)
                path, evidence = store.terminal()
            except (OSError, SafetyError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
                # Commit the unknown operation state before attempting its save.
                # A failed recovery save must not be retried by timer ticks.
                from beamo_wipe.outcomes import VIEWS
                self.wipe_result = WipeResult(False, None, VIEWS["indeterminate"].message, "")
                self.screen = Screen.DONE
                self.error = None
                inputs = dict(
                    disk=target, discovery=discovery, method=self.method,
                    request=None, result=None, started_at_wall=None, ended_at_wall=None,
                    started_mono=None, ended_mono=None, argv=[], log_text="", interrupted=True,
                    wall_provenance="unavailable", language=self.language,
                    keyboard_layout=self.keyboard_layout)
                self._evidence_write_seq += 1
                self._pending_evidence = (copy.deepcopy(inputs), self._evidence_context(),
                                          self.wipe_result, self._result_evidence_key(self.wipe_result))
                self._evidence_saving = True
                self.evidence_status = "saving"
                self._persist_evidence(self._evidence_write_seq)
                return
            from beamo_wipe.outcomes import present_evidence
            view = present_evidence(evidence)
            self.evidence = evidence
            self.evidence_path = str(path)
            self.evidence_status = "saved"
            self.evidence["provenance"]["verified"] = True
            self.wipe_result = WipeResult(view.success, evidence["exit_evidence"]["exit_code"],
                                          view.message, evidence["logfile"])
            self._evidence_written_for = self._result_evidence_key(self.wipe_result)
            self.screen = Screen.DONE
            self.stop_confirmation = None
            self.error = None
            self._touch_report_locked()
        except (OSError, SafetyError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            self.error = RECOVERY_UNAVAILABLE_MSG

    def _recovery_busy(self) -> bool:
        if not self._recovered or self._session_store is None:
            return False
        try:
            return not self._session_store.is_quiescent()
        except (OSError, SafetyError):
            return True

    @property
    def now(self) -> float:
        return self._clock()

    @property
    def protected_boot(self):
        """Confirmed boot identity for display only; never an erase target."""
        if not self.discovery.boot_identified or self.discovery.error:
            return None
        return self.discovery.boot

    @property
    def protected_boot_text(self) -> str:
        from beamo_wipe.inventory import card_nesting_text

        boot = self.protected_boot
        if boot is None:
            return ""
        title = C.BOOT_USB_BANNER if boot.bus == "USB" else C.BOOT_DISC_BANNER
        lines = [title, self.disk_view(boot).announcement]
        nested = card_nesting_text(self.nested_components(boot))
        if nested:
            lines.append(nested)
        return "\n".join(lines)

    @property
    def empty_detail(self) -> str:
        """Read-only boot-device line for the empty screen.

        The boot USB is shown so the owner can see it was found; it stays
        non-selectable (selectable_disks never includes it).
        """
        boot = self.discovery.boot
        if boot is None:
            return ""
        view = self.disk_view(boot)
        return BOOT_USB_LINE.format(line=view.compact_line)

    @property
    def selectable(self):
        return selectable_disks(self.discovery)

    @property
    def listed_disks(self):
        """Boot (marked) plus selectable targets. Nothing else is shown."""
        return safety_listed_disks(self.discovery)

    @property
    def other_devices(self):
        from beamo_wipe.inventory import other_devices

        return other_devices(self.discovery)

    @property
    def inventory_count(self) -> str:
        from beamo_wipe.inventory import count_summary

        return count_summary(self.discovery)

    @property
    def inventory_count_announcement(self) -> str:
        from beamo_wipe.inventory import count_summary

        return count_summary(self.discovery, spoken=True)

    def nested_components(self, disk: Optional[Disk]):
        """Display-only children of a picker card. Never selectable."""
        from beamo_wipe.inventory import nested_under

        if (
            disk is None
            or not self.discovery.boot_identified
            or self.discovery.error
        ):
            return ()
        return nested_under(disk.path, self.discovery.excluded)

    def disk_view(self, disk: Optional[Disk] = None):
        from beamo_wipe.identity import present_disk

        target = disk if disk is not None else self.selected
        if target is None:
            raise SafetyError(NO_DISK_SELECTED)
        return present_disk(
            target, self.listed_disks, compare_serials=self.screen == Screen.PICK
        )

    @property
    def operation_disk(self) -> Optional[Disk]:
        """Wipe-request target. Never a substituted disk."""
        request = self._wipe_request
        if request is None:
            return self.selected
        for disk in self.listed_disks:
            if disk.path == request.device:
                return disk
        return None

    @property
    def operation_identity_text(self) -> str:
        """Compact request-bound identity for operation screens."""
        disk = self.operation_disk
        if disk is not None:
            return self.disk_view(disk).announcement
        request = self._wipe_request
        if request is not None:
            from beamo_wipe.discover import IDENTITY_UNAVAILABLE

            return f"{request.device}: {IDENTITY_UNAVAILABLE}"
        return ""

    @property
    def operation_method_text(self) -> str:
        """Compact request-bound method line for operation screens."""
        request = self._wipe_request
        method = request.method if request is not None else self.method
        return METHODS[method].operation_summary

    @property
    def confirm(self) -> Optional[ConfirmSpec]:
        if self.selected is None:
            return None
        try:
            return confirm_spec(self.selected, self.listed_disks)
        except SafetyError:
            return None

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

    @property
    def progress_view(self) -> ProgressView:
        with self._lock:
            observation = getattr(self.runner, "progress_observation", None)
            spec = METHODS[self.method]
            final_operation = bool(
                observation and observation.counters[0] == observation.counters[1]
                and 0 < observation.counters[2] == observation.counters[3]
                and (observation.phase == "Verifying" and spec.verify == "last"
                     or observation.phase == "Writing" and spec.verify == "off")
            )
            timing = self._progress_timing.view(observation, final_operation)
            phase = timing.phase
            if phase == "Preparing" and self.progress is not None:
                phase = _progress.PHASE_UNKNOWN
            remaining = timing.remaining
            if self.screen == Screen.STOPPING:
                phase, remaining = _progress.PHASE_STOPPING, None
                self._progress_timing.clear_estimate()
            elif getattr(self.runner, "finalizing", False):
                phase, remaining = _progress.PHASE_FINALIZING, None
                self._progress_timing.clear_estimate()
            if self.wipe_result is not None or self._recovered:
                remaining = None
            terminal = (
                self.wipe_result is not None
                or self._recovered
                or self.screen == Screen.STOPPING
                or bool(getattr(self.runner, "finalizing", False))
            )
            stale_for = None if terminal else timing.stale_for
            estimate_state = "" if terminal else timing.estimate_state
            percent = self.progress
            now = self.now
            previous = self._display_progress
            # Share one displayed percentage across every interface. Phase,
            # estimate suppression and terminal results are never delayed.
            if (previous is not None and previous.phase == phase
                    and percent is not None and previous.percent is not None
                    and self.wipe_result is None and 0 <= now - self._display_progress_at < 5):
                percent = previous.percent
            else:
                self._display_progress_at = now
            stages = _progress.plan_stages(
                spec.overwrite_passes, bool(spec.verification_passes)
            )
            position, mismatch = _progress.locate_stage(stages, observation)
            old = bool(percent is not None and stale_for is not None)
            step_percent = (
                observation.percent
                if observation is not None
                and position is not None
                and not mismatch
                else None
            )
            view = ProgressView(
                phase,
                percent,
                timing.elapsed,
                remaining,
                stale_for=stale_for,
                percent_is_old=old,
                stages=stages,
                position=position,
                mismatch=mismatch,
                step_percent=step_percent,
                estimate_state=estimate_state,
            )
            self._display_progress = view
            return view

    def _capture_wall(self) -> tuple[str, str]:
        """Return (stamp, provenance). Format never implies a trusted clock."""
        from beamo_wipe.evidence import _iso_now_wall, valid_wall

        try:
            if self._wall_clock is not None:
                raw = self._wall_clock()
                provenance = "injected"
            else:
                raw = _iso_now_wall()
                provenance = "os_utc"
        except Exception:
            return "", "unavailable"
        stamp = valid_wall(raw)
        if not stamp:
            return "", "unavailable"
        return stamp, provenance

    @property
    def elapsed_text(self) -> str:
        from beamo_wipe.progress import duration
        if self._recovered:
            value = (self.evidence or {}).get("timestamps", {}).get("duration_s")
            return "Elapsed: " + duration(value)
        return "Elapsed: " + duration(self.progress_view.elapsed)

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
        self.power.tick(self.now)
        with self._lock:
            self._recover_when_quiescent()
        if (
            self.screen == Screen.SPLASH
            and not self.preview
            and self.now >= self._splash_until
        ):
            self.screen = Screen.KEYBOARD
        # Poll under lock to avoid races with cancel_wipe / confirm_erase
        # that both touch _wipe_request / screen / evidence.
        should_finish = None
        with self._lock:
            if self.screen == Screen.WORKING and self._wipe_request is not None:
                status_warning = CLEANUP_UNCONFIRMED
                try:
                    result = self.runner.poll(self._wipe_request)
                except Exception:
                    if self.error != status_warning:
                        self.error = status_warning
                        self._touch_report_locked()
                    return
                if self.error == status_warning:
                    self.error = None
                    self._touch_report_locked()
                if result is not None and not self._cancel_requested:
                    should_finish = result
                # When a cancel is in flight, drop the poll result: the
                # post-cancel runner state is not an engine verdict, and
                # finishing with it would lose the user's cancel (evidence
                # would say engine-'failed' instead of 'interrupted').
        if should_finish is not None:
            self._finish(should_finish)

    @property
    def power_text(self) -> str:
        prefix = PREVIEW_POWER_PREFIX if self.dry_run else ""
        return prefix + self.power.status.text

    def skip_splash(self) -> None:
        with self._lock:
            if self.screen == Screen.SPLASH:
                self.screen = Screen.KEYBOARD

    def skip_intro(self) -> None:
        """Tests: advance past splash and keyboard. Production walks each screen."""
        with self._lock:
            if self.screen == Screen.SPLASH:
                self.screen = Screen.KEYBOARD
            if self.screen == Screen.KEYBOARD:
                self.typing_check = ""
                self.screen = Screen.WHAT

    def set_text_size(self, size: str) -> bool:
        """Session-only type size. Unknown values are refused."""
        if size not in {"standard", "large", "extra"}:
            return False
        with self._lock:
            self.text_size = size
            return True

    def cycle_text_size(self) -> str:
        order = ("standard", "large", "extra")
        with self._lock:
            index = order.index(self.text_size) if self.text_size in order else 0
            self.text_size = order[(index + 1) % len(order)]
            return self.text_size

    @property
    def text_scale(self) -> float:
        return {"standard": 1.0, "large": 1.2, "extra": 1.35}.get(self.text_size, 1.0)

    def accept_keyboard(self) -> None:
        with self._lock:
            if self.screen != Screen.KEYBOARD:
                return
            dest = self._keyboard_from or Screen.WHAT
            if dest in {
                Screen.WORKING,
                Screen.CHECKING,
                Screen.STOPPING,
                Screen.REFRESHING,
                Screen.KEYBOARD,
                Screen.SPLASH,
            }:
                dest = Screen.WHAT
            self._keyboard_from = None
            self.typing_check = ""
            self.screen = dest

    @property
    def can_open_keyboard(self) -> bool:
        return (
            self.screen
            in {
                Screen.KEYBOARD,
                Screen.WHAT,
                Screen.OWNER,
                Screen.PICK,
                Screen.PICK_EMPTY,
                Screen.PICK_BLOCKED,
                Screen.CONFIRM,
                Screen.METHOD,
                Screen.LAST_CHANCE,
                Screen.ADVANCED,
                Screen.LIMITS,
                Screen.REPORT_HELP,
                Screen.DISK_HELP,
            }
            and self._wipe_request is None
            and not self.wants_shutdown
            and not self._startup_blocked
            and not self._diagnostic_busy
        )

    def open_keyboard(self) -> None:
        with self._lock:
            if not self.can_open_keyboard or self.screen == Screen.KEYBOARD:
                return
            self._keyboard_from = self.screen
            self.screen = Screen.KEYBOARD
            self.typing_check = ""
            self.keyboard_message = ""

    def set_typing_check(self, text: str) -> None:
        with self._lock:
            if self.screen != Screen.KEYBOARD:
                return
            raw = text if isinstance(text, str) else ""
            self.typing_check = "".join(ch for ch in raw[:64] if ch.isprintable())

    def set_language(self, code: str) -> bool:
        """Apply a UI language session-wide. Rejects unknown codes unchanged.

        Unlike a layout change, a language change never alters what the
        keyboard types, so confirmations stay valid.
        """
        from beamo_wipe import lang as ui_lang

        with self._lock:
            if not ui_lang.is_supported(code):
                return False
            if code == self.language:
                return True
            try:
                ui_lang.set_language(code)
            except ValueError:
                return False
            self.language = code
            return True

    def set_keyboard_layout(self, layout_id: str) -> bool:
        """Apply an allowlisted layout. Failed applies leave the previous layout."""
        with self._lock:
            if not self.can_open_keyboard:
                return False
            if not is_allowed(layout_id):
                self.error = _keyboard.UNAVAILABLE
                self.keyboard_message = _keyboard.UNAVAILABLE
                return False
            if layout_id == self.keyboard_layout:
                self.error = None
                self.keyboard_message = ""
                return True
            if self.screen in {
                Screen.WORKING,
                Screen.CHECKING,
                Screen.STOPPING,
                Screen.REFRESHING,
            }:
                return False
            applier = self._apply_keyboard
        result = applier(layout_id)
        with self._lock:
            if not result.ok:
                self.error = result.message or _keyboard.APPLY_FAILED
                self.keyboard_message = self.error
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("keyboard", "apply_failed", layout_id if is_allowed(layout_id) else "rejected")
                except Exception:
                    pass
                return False
            self.keyboard_layout = layout_id
            self.typing_check = ""
            self.keyboard_message = result.message
            self.error = None
            self._invalidate_after_layout_change_locked()
            return True

    def _invalidate_after_layout_change_locked(self) -> None:
        self.owner_ok = False
        self.confirm_input = ""
        self.selected = None
        self._erase_until = None
        self._authorized_operation = None
        self._keyboard_from = None
        self.typing_check = ""
        if self.screen not in {Screen.KEYBOARD, Screen.SPLASH, Screen.WHAT}:
            self.screen = Screen.WHAT

    def reset_for_preview(self) -> None:
        """Start the wizard over. Preview only — never used on a live wipe."""
        from beamo_wipe.nwipe_runner import DryRunRunner

        if self.screen in {Screen.CHECKING, Screen.STOPPING, Screen.WORKING}:
            return
        fail = bool(getattr(self.runner, "fail", False))
        duration = float(getattr(self.runner, "duration_s", 8.0))
        self.runner = DryRunRunner(duration_s=duration, fail=fail)
        self.screen = Screen.SPLASH
        self.report_wanted = False
        self.report_share_redacted = False
        self._shutdown_from = None
        self.shutdown_generation += 1
        self._saved_report_claim = None
        self._saved_diagnostic_context = None
        self._report_help_from = None
        self.owner_ok = False
        self.selected = None
        self.confirm_input = ""
        self.keyboard_layout = DEFAULT_LAYOUT
        self.text_size = "standard"
        try:
            self.set_language("en")
        except Exception:
            self.language = "en"
        self.typing_check = ""
        self.keyboard_message = ""
        self._keyboard_from = None
        self.method = DEFAULT_METHOD
        self.wants_shutdown = False
        self.error = None
        self.wipe_result = None
        self._splash_until = self.now + SPLASH_S
        self._erase_until = None
        self._authorized_operation = None
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
        self._evidence_write_seq += 1
        self._pending_evidence = None
        self._pending_evidence_path = None
        self._evidence_saving = False
        self._evidence_retries = 0
        with self._lock:
            self._active_report_claim = None
            self._set_report_state_locked(
                status="idle", message="", session="", exporting=False
            )
        # evidence / evidence_path / evidence_error are kept for audit

    @property
    def can_erase_another(self) -> bool:
        return (
            self.screen == Screen.DONE and self.wipe_result is not None
            and not self.preview and not self.wants_shutdown
            and not self.wants_new_session and not self._report_exporting
            and not self._evidence_saving and not self._diagnostic_busy
            and not self._finishing
            and not self._new_session_store_blocked()
            and self.result_view.code != "stop_unconfirmed"
        )

    def _new_session_store_blocked(self) -> bool:
        store = self._session_store
        if store is None:
            return False
        try:
            return store.invalid or not store.is_quiescent()
        except (OSError, SafetyError):
            return True

    @property
    def exit_confirmation_title(self) -> str:
        from beamo_wipe import copy as C
        return C.ANOTHER_TITLE if self._new_session_pending else C.SHUTDOWN_TITLE

    @property
    def exit_confirmation_loss(self) -> str:
        from beamo_wipe import copy as C
        return C.ANOTHER_LOSS if self._new_session_pending else C.SHUTDOWN_LOSS

    @property
    def exit_confirmation_discard(self) -> str:
        from beamo_wipe import copy as C
        return C.ANOTHER_DISCARD if self._new_session_pending else C.SHUTDOWN_DISCARD

    @property
    def exit_media_steps(self) -> str:
        from beamo_wipe import copy as C
        return C.media_steps(stay_in_session=self._new_session_pending)

    @property
    def diagnostic_step(self) -> str:
        from beamo_wipe import copy as C
        from beamo_wipe.support_export import next_step_for, next_step_needs_support
        step = next_step_for(self.diagnostic_message)
        if step and next_step_needs_support(self.diagnostic_message):
            return step + " " + C.support_text()
        return step

    @property
    def support_identity(self):
        """Non-sensitive code plus build id when a report cannot be saved."""
        from beamo_wipe.support_code import identity_for_wizard, record_identity

        ident = identity_for_wizard(self)
        logged = getattr(self, "_logged_support_identity", None)
        if ident is not None and ident != logged:
            record_identity(ident)
            self._logged_support_identity = ident
        return ident

    def erase_another_disk(self) -> None:
        """Request replacement by a freshly constructed application session."""
        with self._lock:
            if not self.can_erase_another:
                return
            self._new_session_pending = True
            # Every unsaved result needs an explicit decision, even when the
            # owner did not opt into reports before the previous erase.
            if not self._has_verified_export_locked():
                self._shutdown_from = self.screen
                self.shutdown_generation += 1
                self.screen = Screen.SHUTDOWN_CONFIRM
                self._done_keyboard_armed = False
                return
            self._request_new_session_locked()

    def _request_new_session_locked(self) -> None:
        self.owner_ok = False
        self.confirm_input = ""
        self._authorized_operation = None
        self._erase_until = None
        self._done_keyboard_armed = False
        self.wants_new_session = True

    def shutdown(self) -> None:
        with self._lock:
            if self._recovery_busy():
                return
            if self.wants_shutdown or self.wants_new_session or self.screen in {
                Screen.WORKING,
                Screen.REFRESHING, Screen.CHECKING, Screen.STOPPING,
            }:
                return
            if self._diagnostic_busy or self._evidence_saving:
                return
            if self._report_exporting:
                self._set_report_state_locked(
                    message=WAIT_REPORT_USB
                )
                return
            if self.screen == Screen.SHUTDOWN_CONFIRM:
                return
            if self.report_wanted and not self._has_verified_export_locked():
                self._shutdown_from = self.screen
                self.shutdown_generation += 1
                self.screen = Screen.SHUTDOWN_CONFIRM
                self._done_keyboard_armed = False
                return
            self.wants_shutdown = True

    def _has_verified_export_locked(self) -> bool:
        # Only the constrained exporter can publish these receipts. Button
        # history, local evidence, recovery and manual/sharing copies cannot.
        claim = self._saved_report_claim
        if self.wipe_result is not None:
            return bool(
                claim is not None
                and claim.evidence_write_seq == self._evidence_write_seq
                and str(claim.evidence_path) == self.evidence_path
                and claim.wipe_result == self.wipe_result
                and claim.discovery == self.discovery
            )
        return (
            self._wipe_request is None
            and self._saved_diagnostic_context is not None
            and self._saved_diagnostic_context == self._diagnostic_context()
        )

    def _diagnostic_context(self) -> tuple[str, DiscoveryResult]:
        return (self.startup_error_code, copy.deepcopy(self.discovery))

    def keep_report_session(self) -> None:
        with self._lock:
            if self.screen != Screen.SHUTDOWN_CONFIRM or self.wants_shutdown:
                return
            self.screen = self._shutdown_from or Screen.WHAT
            self._shutdown_from = None
            self._new_session_pending = False
            self._done_keyboard_armed = False

    def confirm_shutdown_without_saving(self, generation: int) -> None:
        with self._lock:
            if (
                self.screen != Screen.SHUTDOWN_CONFIRM
                or self._shutdown_from is None
                or generation != self.shutdown_generation
                or self.wants_shutdown
                or self.wants_new_session
                or self._report_exporting
                or self._diagnostic_busy
            ):
                return
            if self._new_session_pending:
                self._request_new_session_locked()
            else:
                self.wants_shutdown = True

    def enable_report_intent_recovery(self, store) -> None:
        """Recover preference only, never erase authorization or export success."""
        with self._lock:
            self._intent_store = store
            try:
                self.report_wanted = store.load()
            except Exception:
                self.report_wanted = True  # Unreadable state must not discard intent.
                self.report_recovery_warning = PREF_NOT_RECOVERED
            if self.report_wanted and not self.report_recovery_warning:
                self.report_recovery_warning = PREF_RECOVERED

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
        with self._lock:
            if self.screen != Screen.WHAT:
                return
            self.screen = Screen.OWNER

    def set_owner(self, checked: bool) -> None:
        with self._lock:
            if self.screen != Screen.OWNER:
                return
            self.owner_ok = bool(checked)

    def continue_owner(self) -> None:
        with self._lock:
            if self.screen != Screen.OWNER or not self.owner_ok:
                return
            self._enter_pick()

    def _enter_pick(self) -> None:
        if self._startup_blocked:
            self.screen = Screen.PICK_BLOCKED
            return
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

    @property
    def can_refresh(self) -> bool:
        return self.screen in {
            Screen.WHAT, Screen.OWNER, Screen.PICK, Screen.PICK_EMPTY,
            Screen.PICK_BLOCKED, Screen.CONFIRM, Screen.METHOD,
            Screen.LAST_CHANCE, Screen.ADVANCED, Screen.LIMITS, Screen.REPORT_HELP, Screen.DISK_HELP,
            Screen.REFRESH_CONFIRM,
        } and self._wipe_request is None and not self.wants_shutdown and not self._startup_blocked and not self._diagnostic_busy

    def begin_refresh(self) -> Optional[int]:
        """Claim the checking state; the caller runs I/O elsewhere.

        Runs on the UI thread and returns a sequence number, or None when
        refresh is not allowed from the current screen. A second attempt
        while a scan is in flight is refused (None): one scan runs at a
        time, so results can never pile up or race the UI.
        """
        with self._lock:
            if self.screen == Screen.REFRESHING or not self.can_refresh:
                return None
            self._refresh_seq += 1
            self.screen = Screen.REFRESHING
            self.discovery = DiscoveryResult(error=CHECKING_AGAIN, boot_identified=False)
            self.selected = None
            self.owner_ok = False
            self.confirm_input = ""
            self.method = DEFAULT_METHOD
            self._erase_until = None
            self._authorized_operation = None
            self._advanced_from = None
            self._report_help_from = None
            self._refresh_confirm_from = None
            self._done_keyboard_armed = False
            self.error = None
            return self._refresh_seq

    def _run_rediscovery(self):
        """Discovery I/O only. May run on a worker thread.

        Touches no wizard state and no UI: the injected source (or the live
        ``discover``) runs its subprocess and parsing here while the event
        loop stays responsive. May raise; the caller applies fail-closed
        handling through :meth:`finish_refresh`.
        """
        if self._rediscover is None and (self.dry_run or self.preview):
            raise SafetyError(FAKE_SOURCE_REQUIRED)
        return (self._rediscover or discover)()

    def finish_refresh(self, seq: int, outcome) -> bool:
        """Apply a scan result on the UI thread. Stale results drop.

        Returns True when this sequence owned the in-flight scan and the
        result (or its fail-closed error) was applied; False when the
        sequence is unknown or the screen already moved on.
        """
        with self._lock:
            if seq != self._refresh_seq or self.screen != Screen.REFRESHING:
                return False
        try:
            if isinstance(outcome, BaseException):
                raise outcome
            fresh = outcome
            if not isinstance(fresh, DiscoveryResult):
                raise SafetyError(INVALID_INVENTORY)
            assert_boot_excluded(fresh)
            if not fresh.boot_identified or fresh.boot is None or fresh.error:
                raise SafetyError(BOOT_UNIDENTIFIED)
        except Exception as exc:
            from beamo_wipe.diagnostics import log_diag
            log_diag("discover", "refresh_failed", type(exc).__name__)
            fresh = DiscoveryResult(error=C.REDISCOVER_ERROR, boot_identified=False, error_code="refresh_failed")
        with self._lock:
            # Validation runs outside the lock. A duplicate completion may
            # have committed this scan and allowed a newer scan or navigation.
            if seq != self._refresh_seq or self.screen != Screen.REFRESHING:
                return False
            self.discovery = fresh
            self.startup_error_code = fresh.error_code
            self.error = fresh.error
            # WHAT -> OWNER -> PICK requires all acknowledgements again.
            self.screen = Screen.PICK_BLOCKED if fresh.error else Screen.WHAT
        return True

    def refresh_disks(self) -> bool:
        """Synchronous refresh for sequential callers (consoles, GTK view).

        Same claim/reset/validate/apply contract as the threaded Tk path,
        with I/O inline. Returns False only when refresh is not allowed.
        """
        seq = self.begin_refresh()
        if seq is None:
            return False
        try:
            outcome = self._run_rediscovery()
        except BaseException as exc:
            outcome = exc
        self.finish_refresh(seq, outcome)
        return True

    def open_refresh_confirm(self) -> bool:
        """Show the reset explanation. Does not clear authorization."""
        with self._lock:
            if self.screen == Screen.REFRESHING:
                return False
            if self.screen == Screen.REFRESH_CONFIRM:
                return True
            if not self.can_refresh:
                return False
            self._refresh_confirm_from = self.screen
            self.screen = Screen.REFRESH_CONFIRM
            return True

    def confirm_refresh(self) -> bool:
        """Activate rediscovery after the wording screen."""
        with self._lock:
            if self.screen != Screen.REFRESH_CONFIRM:
                return False
        return self.refresh_disks()

    def cancel_refresh_confirm(self) -> None:
        with self._lock:
            if self.screen != Screen.REFRESH_CONFIRM:
                return
            dest = self._refresh_confirm_from or Screen.WHAT
            self._refresh_confirm_from = None
            self.screen = dest

    def _operation_key(self) -> Optional[tuple[Any, ...]]:
        disk = self.selected
        if disk is None or self.method not in METHODS:
            return None
        spec = METHODS[self.method]
        boot = self.discovery.boot
        return (
            disk_identity(disk),
            self.method,
            spec.nwipe_method,
            spec.rounds,
            spec.verify,
            spec.noblank,
            os.path.realpath(boot.path) if boot is not None else "",
            tuple(sorted(os.path.realpath(item.path) for item in self.selectable)),
            bool(self.discovery.boot_identified),
            self.discovery.error or "",
        )

    def _clear_authorization_locked(self) -> None:
        self.confirm_input = ""
        self._erase_until = None
        self._authorized_operation = None

    def _authorization_matches(self) -> bool:
        key = self._operation_key()
        return (
            key is not None
            and self._authorized_operation is not None
            and key == self._authorized_operation
        )

    def open_disk_help(self) -> None:
        """Reading identification help revokes the target, never authorizes it."""
        with self._lock:
            if self.screen != Screen.PICK or self.wants_shutdown:
                return
            self._clear_authorization_locked()
            self.selected = None
            self.error = None
            self.screen = Screen.DISK_HELP

    def select_disk(self, path: str) -> None:
        with self._lock:
            if self.screen != Screen.PICK:
                return
            want = os.path.realpath(path)
            boot = self.discovery.boot
            if boot is not None and os.path.realpath(boot.path) == want:
                return
            for disk in self.selectable:
                if os.path.realpath(disk.path) == want:
                    if self.selected is None or os.path.realpath(self.selected.path) != want:
                        self._clear_authorization_locked()
                    self.selected = disk
                    self.error = None
                    return

    def move_selection(self, delta: int) -> None:
        """Move the pick-list highlight. First Up/Down chooses an edge disk."""
        with self._lock:
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
        with self._lock:
            if self.screen != Screen.PICK or self.selected is None or self.selected.is_boot:
                return
            want = os.path.realpath(self.selected.path)
            if want not in {os.path.realpath(d.path) for d in self.selectable}:
                return
            if self.discovery.boot is not None:
                if want == os.path.realpath(self.discovery.boot.path):
                    return
            from beamo_wipe.identity import AMBIGUOUS_IDENTITY, identity_confirmable

            if not identity_confirmable(self.selected, self.listed_disks):
                self.error = AMBIGUOUS_IDENTITY
                return
            self.error = None
            self.confirm_input = ""
            self._authorized_operation = None
            self.screen = Screen.CONFIRM

    def set_confirm_input(self, text: str) -> None:
        with self._lock:
            if self.screen != Screen.CONFIRM:
                return
            self.confirm_input = text

    def continue_confirm(self) -> None:
        with self._lock:
            if self.screen != Screen.CONFIRM or not self.token_ok:
                return
            self.screen = Screen.METHOD

    def set_method(self, method: MethodId) -> None:
        with self._lock:
            if self.screen != Screen.METHOD:
                return
            if method not in METHODS:
                return
            if method != self.method and self._authorized_operation is not None:
                self._clear_authorization_locked()
            self.method = method

    def continue_method(self) -> None:
        with self._lock:
            if self.screen != Screen.METHOD:
                return
            if not self.token_ok or self.selected is None:
                self.screen = Screen.CONFIRM
                return
            key = self._operation_key()
            if key is None:
                self.screen = Screen.CONFIRM
                return
            self._authorized_operation = key
            self.screen = Screen.LAST_CHANCE
            self._erase_until = self.now + COUNTDOWN_S

    def _claim_start(self) -> Optional[_StartClaim]:
        with self._lock:
            if self._recovered or self._startup_blocked:
                return None
            # Double-start guard first: a second caller blocked on _lock
            # arrives after the first moved to WORKING. Refuse it with a
            # visible error (checking LAST_CHANCE first would silently
            # swallow it, since the screen is already WORKING).
            if self.screen == Screen.WORKING and self._wipe_request is not None:
                self.error = ALREADY_RUNNING
                return None
            if self.wants_shutdown or self.wants_new_session or self.screen != Screen.LAST_CHANCE:
                return None
            if not self.erase_enabled or self.selected is None:
                return None
            if self._authorized_operation is None:
                self._authorized_operation = self._operation_key()
            if not self._authorization_matches():
                self._clear_authorization_locked()
                self.error = C.AUTHORIZATION_STALE
                self.screen = Screen.CONFIRM if self.selected is not None else Screen.PICK
                return None
            if (self.dry_run or self.preview) and isinstance(self.runner, NwipeRunner):
                self.error = PREVIEW_NO_EXEC
                return None
            # Claim on the caller thread before scheduling any work. All screen
            # mutations reject CHECKING; slow I/O never owns the UI state lock.
            claim = (self.selected, copy.deepcopy(self.discovery), self.owner_ok,
                     self.confirm_input, self.method, self.countdown_left <= 0.0)
            self._start_claim = claim
            self._start_abort.clear()
            self.error = None
            self.screen = Screen.CHECKING
            return claim

    def confirm_erase(self) -> None:
        """Synchronous console/test entry point, sharing the graphical claim."""
        claim = self._claim_start()
        if claim is not None:
            self._perform_start(claim)

    def begin_erase(self) -> bool:
        claim = self._claim_start()
        if claim is None:
            return False
        return self._launch_operation(lambda: self._perform_start(claim), Screen.CHECKING)

    def _launch_operation(self, action: Callable[[], None], screen: Screen) -> bool:
        try:
            worker = threading.Thread(target=action, name="beamo-erase-transition", daemon=True)
            self._operation_thread = worker
            worker.start()
            return True
        except Exception:
            with self._lock:
                if self.screen == screen:
                    if screen == Screen.CHECKING:
                        self._erase_until = self.now + COUNTDOWN_S
                        self.screen = Screen.LAST_CHANCE
                    else:
                        self.screen = Screen.WORKING
                    self._start_claim = None
                    self._cancel_requested = False
                    from beamo_wipe.outcomes import VIEWS
                    self.error = (CHECKING_NO_START if screen == Screen.CHECKING
                                  else VIEWS["stop_unconfirmed"].announcement)
            return False

    def interface_failed(self) -> None:
        """Retire UI actions without a worker ever calling a destroyed toolkit.

        If launch is already in progress, its owner stops it after start returns.
        Otherwise this prevents launch at the final worker boundary.
        """
        self._start_abort.set()
        self.begin_cancel(origin="system")

    def _perform_start(self, claim: _StartClaim) -> None:
        disk, discovery, owner, token, method, countdown_complete = claim
        try:
            if not self.dry_run and not self.preview:
                try:
                    discovery = (self._rediscover or discover)()
                    if not isinstance(discovery, DiscoveryResult):
                        raise TypeError("Invalid discovery result")
                except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError, AttributeError):
                    self.error = REREAD_FAILED
                    self.startup_error_code = "rediscovery_failed"
                    return
                except Exception:  # noqa: BLE001 — fail closed on any rediscover error
                    self.error = REREAD_FAILED
                    self.startup_error_code = "rediscovery_failed"
                    return
                if not discovery.boot_identified or discovery.boot is None:
                    self.error = C.REDISCOVER_ERROR
                    self.startup_error_code = "rediscovery_failed"
                    return
                try:
                    assert_boot_excluded(discovery)
                    assert_disk_identity(disk, discovery)
                except SafetyError:
                    self.error = IDENTITY_UNCONFIRMED_MSG
                    self.startup_error_code = "identity_rejected"
                    return
                self.discovery = discovery
                try:
                    disk = next(
                        d
                        for d in selectable_disks(discovery)
                        if os.path.realpath(d.path) == os.path.realpath(disk.path)
                    )
                except StopIteration:
                    self.error = NOT_IN_SAFE_LIST
                    self.startup_error_code = "identity_rejected"
                    return
                self.selected = disk
            try:
                request = assert_ready_to_wipe(
                    owner_ok=owner,
                    disk=disk,
                    discovery=discovery,
                    typed_token=token,
                    countdown_complete=countdown_complete,
                    method=method,
                )
                build_nwipe_argv(request)
                self._saved_diagnostic_context = None
                self._saved_report_claim = None
                if self._session_store is not None:
                    self._session_store.arm(discovery, request)
                if self._start_abort.is_set():
                    self.error = CLOSED_DURING_CHECK
                    return
                self.runner.start(request)
            except SafetyError as exc:
                self.error = (_safety.TOKEN_MISMATCH if str(exc) == _safety.TOKEN_MISMATCH else
                              PREFLIGHT_BLOCKED)
                self.startup_error_code = "preflight_rejected"
                return
            except OSError as exc:
                from beamo_wipe.outcomes import VIEWS
                from beamo_wipe.diagnostics import log_diag

                self.error = VIEWS["start_failed"].announcement
                self.startup_error_code = "engine_start_failed"
                log_diag("nwipe", "start_failed", f"{type(exc).__name__}; errno={exc.errno}")
                return
            except Exception:
                self.error = STARTUP_UNCONFIRMED
                self.startup_error_code = "unexpected_startup_failure"
                return
            with self._lock:
                self.error = None
                self.startup_error_code = ""
                self._wipe_request = request
                self._cancel_requested = False
                self._evidence_written_for = None
                self._evidence_flag_hint = {}
                self.screen = Screen.WORKING
                # Record evidence start (wall + monotonic) + redacted argv for later completion
                wall, provenance = self._capture_wall()
                self._evidence_start_wall = wall
                self._evidence_wall_provenance = provenance
                self._evidence_start_mono = self.now
                self._evidence_end_mono = None
                self._progress_timing = ProgressTiming(self._clock, time.time)
                self._progress_timing.start(self._evidence_start_mono)
                self._display_progress = None
                try:
                    # Build redacted argv now (never contains secrets; already sanitized)
                    self._evidence_argv = list(build_nwipe_argv(request))
                except Exception:
                    self._evidence_argv = []
                # Write initial started evidence (atomic, off-target)
                # Do not hold the lock during file I/O; copy needed state
                # and release lock before writing.
            self._write_evidence(result=None, cancelled=False, interrupted=False)
            if self._start_abort.is_set():
                self.cancel_wipe(origin="system")
        except Exception:
            # Malformed discovery metadata must not kill a background worker
            # silently or leave the operator with an apparently idle success.
            with self._lock:
                self.error = STARTUP_UNCONFIRMED
                self.startup_error_code = "unexpected_startup_failure"
        finally:
            with self._lock:
                if self._start_claim is claim:
                    self._start_claim = None
                    if self.screen == Screen.CHECKING:
                        if self.error:
                            # Identity/preflight failure must not leave Erase
                            # armed from the previous countdown.
                            self._erase_until = self.now + COUNTDOWN_S
                        self.screen = Screen.LAST_CHANCE

    def _finish(self, result: WipeResult, *, cancelled: bool = False, interrupted: bool = False, from_stop: bool = False) -> None:
        # Guard against double-finish from concurrent tick/cancel
        with self._lock:
            if self.screen == Screen.STOPPING and not from_stop:
                return
            if self.screen == Screen.DONE and self.wipe_result is not None:
                return
            self._evidence_end_mono = self.now
            end_wall, end_provenance = self._capture_wall()
            self._evidence_end_wall = end_wall
            if self._evidence_wall_provenance == "unavailable":
                self._evidence_wall_provenance = end_provenance
            self._progress_timing.finish(self._evidence_end_mono)
            if self._progress_timing.invalid_clock:
                self._evidence_end_mono = None
            self.wipe_result = result
            self._finishing = True
            self.screen = Screen.DONE
            self.stop_confirmation = None
            self.error = None
            self._done_keyboard_armed = False
            self.log_text = result.summary
            self._active_report_claim = None
            self._set_report_state_locked(
                status="idle", message="", session="", exporting=False
            )
        # Persist auditable evidence (atomic, off-target, truthful outcome)
        try:
            self._write_evidence(result=result, cancelled=cancelled, interrupted=interrupted)
        finally:
            with self._lock:
                self._finishing = False
                self._touch_report_locked()

    def request_stop(self) -> None:
        """Open a user confirmation without pausing engine polling."""
        with self._lock:
            if self.screen == Screen.WORKING and self._wipe_request is not None:
                if self.stop_confirmation is None:
                    self.stop_confirmation = object()

    def keep_erasing(self) -> None:
        with self._lock:
            self.stop_confirmation = None

    def confirm_stop(self, confirmation: Optional[object], *, asynchronous: bool = True) -> bool:
        """Reject stale confirmations, including completion while reading."""
        with self._lock:
            if confirmation is None or confirmation is not self.stop_confirmation:
                return False
            self.stop_confirmation = None
            if self.screen != Screen.WORKING:
                return False
            # Claim under the same lock; no subsequent run can inherit consent.
            if not self._claim_stop():
                return False
        if asynchronous:
            return self._launch_operation(lambda: self._perform_stop("user"), Screen.STOPPING)
        self._perform_stop("user")
        return True

    def _claim_stop(self) -> bool:
        with self._lock:
            if self._wipe_request is None or self.screen != Screen.WORKING or self._cancel_requested:
                return False
            self._cancel_requested = True
            self.stop_confirmation = None
            self._progress_timing.clear_estimate()
            self.screen = Screen.STOPPING
            self.error = None
            return True

    def cancel_wipe(self, *, origin: str = "user") -> None:
        """Synchronous console/test entry point; only one caller owns stop."""
        if self._claim_stop():
            self._perform_stop(origin)

    def begin_cancel(self, *, origin: str = "user") -> bool:
        if not self._claim_stop():
            return False
        return self._launch_operation(lambda: self._perform_stop(origin), Screen.STOPPING)

    def _perform_stop(self, origin: str) -> None:
        with self._lock:
            request = self._wipe_request
            if request is None or self.screen != Screen.STOPPING:
                return
        try:
            # Preserve a terminal engine result that predates the stop request.
            try:
                self.runner.poll(request)
            except ProcessStatusError:
                # A failed status read must not disable the user's stop action.
                # cancel() still requires confirmed exit and successful cleanup.
                pass
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
            from beamo_wipe.outcomes import VIEWS
            with self._lock:
                self.error = VIEWS["stop_unconfirmed"].announcement
                self._cancel_requested = False
                self.screen = Screen.WORKING
            return
        # Hold lock while checking and transitioning to avoid race with
        # tick()->_finish.
        with self._lock:
            if self._wipe_request is None or self.screen != Screen.STOPPING:
                return
            from beamo_wipe.models import WipeResult as _WR

            observed = getattr(self.runner, "result", None)
            if observed is None:
                from beamo_wipe.outcomes import VIEWS
                self._cancel_requested = False
                self.screen = Screen.WORKING
                self.error = VIEWS["stop_unconfirmed"].announcement
                return
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
                interrupted = True
                cancelled = origin == "user" and observed is not None and not observed.ok
            # _write_evidence and _finish outside lock to avoid I/O under lock
            need_evidence = res
        self._finish(need_evidence, cancelled=cancelled, interrupted=interrupted, from_stop=True)
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
            self._evidence_saving = True
            self.evidence_status = "saving"
            self._evidence_retries = 0
            self._pending_evidence = None
            self._pending_evidence_path = None
            self._touch_report_locked()
        try:
            # Gather log tail for checksum (best effort, off-target)
            log_text = ""
            try:
                # Prefer runner's _log_tail if available, else read file
                log_text = getattr(self.runner, "_log_tail", "") or ""
                if not log_text and self._wipe_request and self._wipe_request.logfile:
                    try:
                        fd = os.open(
                            self._wipe_request.logfile,
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
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

            if result is not None:
                end_wall = self._evidence_end_wall
            else:
                end_wall, end_provenance = self._capture_wall()
                if self._evidence_wall_provenance == "unavailable":
                    self._evidence_wall_provenance = end_provenance
            start_wall = self._evidence_start_wall or ""
            start_mono = self._evidence_start_mono
            end_mono = self._evidence_end_mono if result is not None else None
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

            # Freeze the observation once. A save retry never reads a runner,
            # mutable log, wall clock or current device inventory.
            inputs: dict[str, Any] = dict(
                disk=copy.deepcopy(self.selected), discovery=copy.deepcopy(self.discovery),
                method=self.method, request=copy.deepcopy(self._wipe_request), result=result,
                started_at_wall=start_wall, ended_at_wall=end_wall if result is not None else "",
                started_mono=start_mono, ended_mono=end_mono, argv=copy.deepcopy(argv),
                log_text=log_text or "", interrupted=interrupted, cancelled=cancelled,
                wall_provenance=self._evidence_wall_provenance,
                language=self.language, keyboard_layout=self.keyboard_layout,
            )
            with self._lock:
                if write_seq != self._evidence_write_seq:
                    return
                self._pending_evidence = (inputs, self._evidence_context(), result, key)
            self._persist_evidence(write_seq)
        except Exception as exc:
            self._evidence_failed(exc, "data", write_seq)

    def _evidence_context(self):
        return copy.deepcopy((self.selected, self.discovery, self.method, self._wipe_request))

    def _evidence_failed(self, exc: Exception, stage: str, seq: int) -> None:
        # Exceptions can contain disk identifiers, paths and customer data.
        # Only fixed descriptions and errno categories may reach any UI/log.
        from beamo_wipe.evidence import EvidenceFinalizationError
        error: BaseException = exc
        seen = set()
        number = None
        while id(error) not in seen:
            seen.add(id(error))
            if isinstance(error, OSError) and error.errno is not None:
                number = error.errno
                break
            cause = error.__cause__
            if cause is None:
                break
            error = cause
        if number in {errno.EACCES, errno.EPERM, errno.EROFS}:
            code, message = "permissions", TMP_NOT_WRITABLE
        elif number in {errno.ENOSPC, errno.EDQUOT}:
            code, message = "storage_full", TMP_NO_SPACE
        elif stage == "finalization" or isinstance(exc, EvidenceFinalizationError):
            code, message = "finalization", FINALIZE_UNCONFIRMED
        elif isinstance(exc, (SafetyError, ValueError, TypeError, KeyError)):
            code, message = "invalid_data", EVIDENCE_INVALID
        elif number in {errno.EIO, errno.EAGAIN, errno.EINTR, errno.ETIMEDOUT}:
            code, message = "transient_io", TMP_IO_ERROR
        else:
            code, message = "io", TMP_IO_FAILED
        with self._lock:
            if seq != self._evidence_write_seq:
                return
            self.evidence_error_code = code
            self.evidence_error = message
            self.evidence_status = "failed"
            self._evidence_saving = False
            self._touch_report_locked()
        try:
            from beamo_wipe.diagnostics import log_diag
            log_diag("wizard", "evidence_save_failed", f"{code}; stage={stage}; errno={number}")
        except Exception:
            pass

    def _persist_evidence(self, seq: int) -> bool:
        stage = "data"
        try:
            from beamo_wipe.evidence import build_evidence, write_evidence_atomic, load_evidence, verify_evidence_checksum
            with self._lock:
                pending = self._pending_evidence
                if pending is None or seq != self._evidence_write_seq:
                    return False
                inputs, context, result, key = copy.deepcopy(pending)
                if context != self._evidence_context():
                    raise SafetyError(CHANGED_CONTEXT)
                path = self._pending_evidence_path
            ev = build_evidence(**inputs)
            if self._recovered:
                ev["recovery"] = {"status": "indeterminate", "interface_restarted": True}
            # Reject non-finite numbers or non-JSON input before any write.
            json.dumps(ev, allow_nan=False)
            target = inputs["disk"].path if inputs["disk"] else ""
            stage = "write"
            if path is None:
                import beamo_wipe.safety as safety
                directory = self._session_store.directory if self._session_store else safety.default_log_dir()
                path = write_evidence_atomic(ev, log_dir=directory, device_path=target, target_device=target)
            stage = "readback"
            written = load_evidence(path, private=True)
            from beamo_wipe.evidence import _read_regular_nofollow
            _read_regular_nofollow(Path(str(path) + ".sha256"), private=True)
            if not verify_evidence_checksum(path):
                raise SafetyError(EVIDENCE_UNVERIFIED)
            # Compare the actual bytes' meaning to the frozen observation;
            # provenance is the only information supplied by the writer.
            expected = copy.deepcopy(ev)
            provenance = written.get("provenance", {})
            if provenance.get("evidence_file") != str(path):
                raise SafetyError(FOREIGN_PROVENANCE)
            expected["provenance"] = provenance
            if json.dumps(written, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
                raise SafetyError(CONTRADICTORY_READBACK)
            with self._lock:
                if seq != self._evidence_write_seq:
                    return False
                if context != self._evidence_context() or (result is not None and self.wipe_result != result):
                    raise SafetyError(CHANGED_TERMINAL)
                self._pending_evidence_path = path
            stage = "finalization"
            if self._session_store is not None and result is not None and not self._recovered:
                self._session_store.finish(path)
            with self._lock:
                if seq != self._evidence_write_seq:
                    return False
                if context != self._evidence_context() or (result is not None and self.wipe_result != result):
                    raise SafetyError(CHANGED_TERMINAL)
                written["provenance"]["verified"] = True
                self.evidence = written
                self.evidence_path = str(path)
                self.evidence_error = None
                self.evidence_error_code = ""
                self.evidence_status = "saved"
                self._evidence_saving = False
                self._evidence_written_for = key
                self._touch_report_locked()
            return True
        except Exception as exc:
            self._evidence_failed(exc, stage, seq)
            return False

    def _can_retry_evidence_locked(self) -> bool:
        pending = self._pending_evidence
        return bool(
            self.screen == Screen.DONE and self.wipe_result is not None
            and self.evidence_error and not self._evidence_saving
            and self._evidence_retries < EVIDENCE_RETRIES and pending is not None
            and pending[1] == self._evidence_context()
            and pending[2] == self.wipe_result
            and not self.wants_shutdown and not self.wants_new_session and not self._report_exporting
            and not self._diagnostic_busy and not self._recovery_busy()
        )

    @property
    def can_retry_evidence(self) -> bool:
        with self._lock:
            return self._can_retry_evidence_locked()

    def _claim_evidence_retry(self) -> Optional[int]:
        with self._lock:
            if not self._can_retry_evidence_locked():
                return None
            self._evidence_retries += 1
            self._evidence_saving = True
            self.evidence_status = "saving"
            self._touch_report_locked()
            return self._evidence_write_seq

    def retry_evidence_save(self) -> bool:
        """One explicit bounded save attempt. No runner methods are reachable."""
        seq = self._claim_evidence_retry()
        return self._persist_evidence(seq) if seq is not None else False

    def begin_evidence_retry(self) -> bool:
        seq = self._claim_evidence_retry()
        if seq is None:
            return False
        try:
            threading.Thread(target=self._persist_evidence, args=(seq,), daemon=True).start()
        except Exception as exc:
            self._evidence_failed(exc, "io", seq)
            return False
        return True

    @property
    def check_alerts(self) -> tuple[str, ...]:
        """Concise engine-check warnings. Never a substitute for result_view."""
        from beamo_wipe.engine_checks import alert_summaries

        if self.preview:
            return ()
        with self._lock:
            evidence = self.evidence if isinstance(self.evidence, dict) else {}
            return alert_summaries(evidence.get("checks") or ())

    @property
    def evidence_warning(self) -> str:
        with self._lock:
            if not self.evidence_error:
                return ""
            if self.screen == Screen.WORKING:
                return EVIDENCE_NOT_SAVING.format(error=self.evidence_error)
            if self._evidence_saving:
                return EVIDENCE_SAVING
            remaining = max(0, EVIDENCE_RETRIES - self._evidence_retries)
            if self._can_retry_evidence_locked():
                action = RETRY_SAVE_REMAINING.format(remaining=remaining)
                return self.evidence_error + action + TEMP_EVIDENCE_LOST
            return (
                self.evidence_error
                + KEEP_SESSION_OPEN
                + TEMP_EVIDENCE_LOST
                + " "
                + C.support_text()
            )

    @property
    def done_support_needed(self) -> bool:
        """True when the DONE screen must show the support destination."""
        from beamo_wipe.engine_checks import HIDDEN_MAYBE
        from beamo_wipe.outcomes import view_needs_support

        return view_needs_support(self.result_view.code) or (
            HIDDEN_MAYBE in self.check_alerts
        )

    @property
    def evidence_support_needed(self) -> bool:
        """True when the evidence warning refers the owner to support."""
        with self._lock:
            return bool(
                self.evidence_error
                and self.screen != Screen.WORKING
                and not self._evidence_saving
                and not self._can_retry_evidence_locked()
            )

    def export_evidence(self, dest_dir: str) -> str:
        """Copy evidence JSON + sidecar to a second USB directory. Returns dest path or raises."""
        if not self.can_save_report or not self.evidence_path:
            raise SafetyError(NO_EXPORT_EVIDENCE)
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
            or self.wants_shutdown
            or self.wants_new_session
            or self.screen != Screen.DONE
            or result is None
            or self.evidence_error
            or self._evidence_saving
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
            or (type(exit_evidence.get("exit_code")) is not int
                and not (self._recovered and exit_evidence.get("exit_code") is None))
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
                saving_evidence=self._evidence_saving,
                can_retry_evidence=self._can_retry_evidence_locked(),
                retries_remaining=max(0, EVIDENCE_RETRIES - self._evidence_retries),
                evidence_status=self.evidence_status,
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
                        message=NO_FINISHED_REPORT,
                    )
                return None
            path = Path(self.evidence_path or "")
            evidence_write_seq = self._evidence_write_seq
            result = self.wipe_result
            assert result is not None
            discovery_snapshot = copy.deepcopy(self.discovery)
            privacy_reduced = bool(self.report_share_redacted)
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
                context = (
                    self._session_store.record["context"]
                    if self._recovered and self._session_store is not None
                    and self._session_store.record is not None else {}
                )
                target_rdev = context.get("target_rdev", 0)
                boot_rdev = context.get("boot_rdev", 0)

        try:
            from beamo_wipe.support_export import prepare_terminal_evidence

            verified = prepare_terminal_evidence(path, target)
            payload = json.loads(verified.data.decode("utf-8"))
        except (OSError, SafetyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            with self._lock:
                if not self._report_exporting:
                    message = (
                        EVIDENCE_UNREADABLE
                        if isinstance(exc, OSError) else str(exc)
                    )
                    self._set_report_state_locked(status="error", message=message)
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
            privacy_reduced=privacy_reduced,
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
                    message=REPORT_CHANGED_BEFORE_SAVE,
                )
                return None
            self._active_report_claim = claim
            self._done_keyboard_armed = False
            self._set_report_state_locked(
                status="saving",
                message=REPORT_SAVING,
                session="",
                exporting=True,
            )
            return claim

    def _perform_report_export(self, claim: _ReportExportClaim) -> None:
        final_status = "error"
        final_message = EXPORT_FAILED
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
                privacy_reduced=claim.privacy_reduced,
            )
            from beamo_wipe.support_export import (
                OWNER_WIPE_FILE,
                present_export_receipt,
                receipt_is_saved,
            )

            if receipt_is_saved(
                receipt,
                expected_sha256=claim.evidence_sha256,
                owner_file=OWNER_WIPE_FILE,
                share_copy=claim.privacy_reduced,
            ):
                final_status = "saved"
                final_session = receipt.session_name
                final_message = present_export_receipt(receipt)
            else:
                final_message = REPORT_NOT_SAVED
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
                    final_message = REPORT_CHANGED_DURING_SAVE
                    final_session = ""
                # Publish the terminal UI state and re-enable Shutdown in one
                # lock transition so Tk cannot render a permanently disabled
                # button between two state changes.
                if final_status == "saved":
                    self._saved_report_claim = claim
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
        try:
            thread = threading.Thread(
                target=self._perform_report_export,
                args=(claim,),
                name="beamo-report-export",
                daemon=True,
            )
            thread.start()
        except Exception as exc:
            with self._lock:
                self._active_report_claim = None
                self._set_report_state_locked(
                    exporting=False,
                    status="error",
                    message=EXPORT_NO_START,
                )
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("wizard", "report_thread_failed", type(exc).__name__)
            except Exception:
                pass
            return False
        return True

    @property
    def diagnostic_view(self) -> DiagnosticView:
        with self._lock:
            return DiagnosticView(self._report_revision, self.diagnostic_message,
                                  bool(self._diagnostic_baseline), self._diagnostic_busy)

    @property
    def can_open_diagnostic(self) -> bool:
        return (not self._recovery_busy() and not self.preview and self._wipe_request is None and self.wipe_result is None
                and not self.wants_shutdown and not self._diagnostic_busy
                and (self.screen in {Screen.PICK_BLOCKED, Screen.PICK_EMPTY}
                     or (self.screen == Screen.LAST_CHANCE and bool(self.error))
                     or (self.screen == Screen.WHAT and self.startup_error_code == "graphical_unavailable")))

    def open_diagnostic(self) -> None:
        with self._lock:
            if not self.can_open_diagnostic:
                return
            self._diagnostic_from = self.screen
            self.screen = Screen.DIAGNOSTIC
            self.diagnostic_message = ""
            self._diagnostic_baseline = ()
            self._report_revision += 1

    def close_diagnostic(self) -> None:
        with self._lock:
            if self.screen == Screen.DIAGNOSTIC and not self._diagnostic_busy:
                self.screen = self._diagnostic_from
                self._diagnostic_baseline = ()

    def diagnostic_action(self, *, background: bool = False) -> bool:
        """Prepare BEFORE insertion; the next explicit action saves to new media."""
        with self._lock:
            if (
                self.wants_shutdown
                or self._recovery_busy()
                or self.screen != Screen.DIAGNOSTIC
                or self._diagnostic_busy
                or self._wipe_request is not None
            ):
                return False
            self._diagnostic_busy = True
            baseline = self._diagnostic_baseline
            context = self._diagnostic_context()
            self.diagnostic_message = DIAG_VERIFYING if baseline else DIAG_CHECKING
            self._report_revision += 1
        def perform():
            try:
                from beamo_wipe import support_export as export
                from beamo_wipe.diagnostic_report import create_report
                if self.dry_run:
                    raise SafetyError(DIAG_NO_PREVIEW)
                if not baseline:
                    prepared = export.capture_diagnostic_baseline()
                    with self._lock:
                        self._diagnostic_baseline = prepared
                        self.diagnostic_message = DIAG_BASELINE_READY.format(action=C.SAVE_DIAGNOSTIC_REPORT)
                else:
                    code = self.startup_error_code or (
                        "no_eligible_disks" if self._diagnostic_from == Screen.PICK_EMPTY else "boot_unidentified")
                    data = create_report(code, self.discovery, ui=self.diagnostic_ui, session_started=self._session_started)
                    receipt = export.export_diagnostic_to_new_usb(data=data, baseline=baseline)
                    import hashlib
                    from beamo_wipe.support_export import (
                        OWNER_DIAGNOSTIC_FILE,
                        present_export_receipt,
                        receipt_is_saved,
                    )

                    if not receipt_is_saved(
                        receipt,
                        expected_sha256=hashlib.sha256(data).hexdigest(),
                        owner_file=OWNER_DIAGNOSTIC_FILE,
                        share_copy=False,
                    ):
                        raise SafetyError(DIAG_NOT_SAVED)
                    with self._lock:
                        if context != self._diagnostic_context():
                            raise SafetyError(
                                DIAG_CONTEXT_CHANGED
                            )
                        self._saved_diagnostic_context = context
                        self.diagnostic_message = present_export_receipt(receipt)
                        self._diagnostic_baseline = ()
            except SafetyError as exc:
                with self._lock:
                    self.diagnostic_message = str(exc)
            except Exception:
                with self._lock:
                    self.diagnostic_message = DIAG_FAILED
            finally:
                with self._lock:
                    self._diagnostic_busy = False
                    self._report_revision += 1
        if background:
            try:
                threading.Thread(target=perform, name="beamo-diagnostic-export", daemon=True).start()
            except Exception:
                with self._lock:
                    self._diagnostic_busy = False
                    self.diagnostic_message = DIAG_NO_START
                    self._report_revision += 1
                return False
        else:
            perform()
        return True

    @property
    def done_ok(self) -> bool:
        return self.result_view.success

    @property
    def result_view(self):
        from beamo_wipe.outcomes import present_evidence, preview_view
        if self.preview:
            return preview_view(bool(self.wipe_result and self.wipe_result.ok))
        view = present_evidence(None if self.evidence_error or self._evidence_saving else self.evidence)
        if self.evidence_error and self.wipe_result is not None and not self._recovered:
            from dataclasses import replace
            inputs = self._pending_evidence[0] if self._pending_evidence else {}
            if inputs.get("cancelled"):
                message = ERASE_STOPPED_BY_YOU
            elif inputs.get("interrupted"):
                message = ERASE_INTERRUPTED_MSG
            elif self.wipe_result.ok:
                message = ERASE_COMPLETION_UNCONFIRMED
            else:
                message = ERASE_UNFINISHED
            view = replace(view, message=message)
        if self._recovered:
            from dataclasses import replace
            from beamo_wipe.session_recovery import NOTICE
            return replace(view, next_step=NOTICE + " " + view.next_step)
        return view

    @property
    def can_open_report_help(self) -> bool:
        return self.screen in {Screen.WHAT, Screen.METHOD, Screen.ADVANCED} and self._wipe_request is None

    def open_report_help(self) -> None:
        with self._lock:
            if self.can_open_report_help:
                self._report_help_from = self.screen
                self.screen = Screen.REPORT_HELP

    def set_report_share_redacted(self, wanted: bool) -> None:
        with self._lock:
            if self.screen == Screen.REPORT_HELP and type(wanted) is bool:
                self.report_share_redacted = wanted

    def set_sound_output(self, sink_id: str) -> None:
        """Record the session's chosen output. Session memory only."""
        with self._lock:
            if type(sink_id) is str:
                self.sound_output = sink_id

    def set_sounds_enabled(self, enabled: bool) -> None:
        """Outcome sounds on/off. Silent by default; session memory only."""
        with self._lock:
            if type(enabled) is bool:
                self.sounds_enabled = enabled

    @property
    def sound_toggle_text(self) -> str:
        from beamo_wipe import copy as _copy

        return (
            _copy.SOUND_TOGGLE_ON
            if self.sounds_enabled
            else _copy.SOUND_TOGGLE_OFF
        )

    def toggle_sounds(self) -> None:
        """Flip outcome sounds and report the state. Session memory only."""
        from beamo_wipe import copy as _copy

        with self._lock:
            self.sounds_enabled = not self.sounds_enabled
            self.sound_message = (
                _copy.SOUND_TOGGLE_ON
                if self.sounds_enabled
                else _copy.SOUND_TOGGLE_OFF
            )

    def maybe_play_outcome_sound(self):
        """Auto-play the final outcome's earcon at most once. Silent rules:

        Only on a real Done screen with a result and sounds enabled;
        re-renders never replay. Never touches sound_message.
        """
        from beamo_wipe import sound as _sound

        with self._lock:
            if (
                self.screen != Screen.DONE
                or self.preview
                or self.wipe_result is None
                or not self.sounds_enabled
            ):
                return None
            key = self._result_evidence_key(self.wipe_result)
            if key == self._sound_played_for:
                return None
            self._sound_played_for = key
            code = self.result_view.code
        return _sound.play_outcome(_sound.kind_for_code(code))

    def hear_outcome_sound(self):
        """Explicit replay of the final outcome's sound.

        Works while sounds are off; preview reports silence honestly.
        """
        from beamo_wipe import sound as _sound

        with self._lock:
            if self.screen != Screen.DONE or self.wipe_result is None:
                return None
            code = self.result_view.code
        result = _sound.play_test(_sound.kind_for_code(code))
        with self._lock:
            self.sound_message = result.message
        return result

    def hear_both_sounds(self):
        """Explicit preview: finished, then attention. Works while off."""
        from beamo_wipe import sound as _sound

        first = _sound.play_test(_sound.KIND_FINISHED)
        if not first.ok:
            with self._lock:
                self.sound_message = first.message
            return first
        second = _sound.play_test(_sound.KIND_ATTENTION)
        combined = (
            first.message + " " + second.message
            if second.ok
            else second.message
        )
        with self._lock:
            self.sound_message = combined
        from beamo_wipe.sound import SoundResult

        return SoundResult(second.ok, combined)

    def set_report_wanted(self, wanted: bool) -> None:
        with self._lock:
            if self.screen == Screen.REPORT_HELP and type(wanted) is bool:
                self.report_wanted = wanted
                if self._intent_store is not None:
                    try:
                        self._intent_store.save(wanted)
                        self.report_recovery_warning = ""
                    except Exception:
                        self.report_recovery_warning = PREF_RECOVERY_UNAVAILABLE

    def close_report_help(self) -> None:
        with self._lock:
            if self.screen == Screen.REPORT_HELP:
                self.screen = self._report_help_from or Screen.WHAT
                self._report_help_from = None

    def open_limits(self) -> None:
        with self._lock:
            if self.screen == Screen.METHOD:
                self.screen = Screen.LIMITS

    def close_limits(self) -> None:
        with self._lock:
            if self.screen == Screen.LIMITS:
                self.screen = Screen.METHOD

    @property
    def storage_notice(self) -> str:
        from beamo_wipe.models import DiskKind
        from beamo_wipe.storage_limits import notice

        return notice(self.selected.kind if self.selected else DiskKind.UNKNOWN)

    def open_advanced(self) -> None:
        with self._lock:
            if self.screen in (Screen.SPLASH, Screen.KEYBOARD, Screen.CHECKING, Screen.STOPPING, Screen.WORKING, Screen.ADVANCED, Screen.REFRESHING, Screen.REFRESH_CONFIRM, Screen.DIAGNOSTIC, Screen.REPORT_HELP):
                return
            self._advanced_from = self.screen
            self.screen = Screen.ADVANCED

    def close_advanced(self) -> None:
        with self._lock:
            if self.screen != Screen.ADVANCED:
                return
            self.screen = self._advanced_from or Screen.METHOD

    def back(self) -> None:
        # The start claim moves to CHECKING under this same lock. Back either
        # wins before the claim, or becomes a no-op throughout checking,
        # working and stopping; it never waits for discovery or termination.
        with self._lock:
            if self.screen == Screen.SHUTDOWN_CONFIRM:
                self.keep_report_session()
                return
            if self.screen == Screen.REFRESH_CONFIRM:
                self.cancel_refresh_confirm()
                return
            if self.screen == Screen.REPORT_HELP:
                self.close_report_help()
                return
            if self.screen == Screen.DIAGNOSTIC:
                self.close_diagnostic()
                return
            if self.screen == Screen.KEYBOARD:
                dest = self._keyboard_from
                self._keyboard_from = None
                self.typing_check = ""
                if dest and dest not in {
                    Screen.KEYBOARD,
                    Screen.SPLASH,
                    Screen.WORKING,
                    Screen.CHECKING,
                    Screen.STOPPING,
                    Screen.REFRESHING,
                }:
                    self.screen = dest
                return
            mapping = {
                Screen.OWNER: Screen.WHAT,
                Screen.DISK_HELP: Screen.PICK,
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

    def prepare_text(self) -> str:
        from beamo_wipe.copy import prepare_selected

        if self.selected is None:
            return ""
        return prepare_selected(self.selected)

    def warning_text(self) -> str:
        if self.selected is None:
            return ""
        return confirm_warning(self.selected)

    @property
    def method_summary(self) -> str:
        return METHODS[self.method].summary

    @property
    def operation_summary(self) -> str:
        return METHODS[self.method].operation_summary

    @property
    def method_result(self) -> str:
        return self.result_view.message

    def erase_label(self) -> str:
        if self.selected is None:
            return "Erase now"
        return erase_now_label(self.selected, self.listed_disks)


def make_demo_wizard(*args, **kwargs):
    from beamo_wipe.demo import make_demo_wizard as _make

    return _make(*args, **kwargs)
