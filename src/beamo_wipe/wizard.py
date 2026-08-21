# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen state machine. UI layers only render this. No auto-start wipe."""

from __future__ import annotations

import os
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


class Wizard:
    def __init__(
        self,
        discovery: DiscoveryResult,
        runner: Runner,
        clock: Callable[[], float] | None = None,
        dry_run: bool = True,
        rediscover: Callable[[], DiscoveryResult] | None = None,
    ) -> None:
        self.discovery = discovery
        self.runner = runner
        self._clock = clock or time.monotonic
        self.dry_run = dry_run
        self._rediscover = rediscover
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
        if self.screen == Screen.WORKING and self._wipe_request is not None:
            result = self.runner.poll(self._wipe_request)
            if result is not None:
                self._finish(result)

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

    def shutdown(self) -> None:
        self.wants_shutdown = True

    def arm_done_keyboard(self) -> None:
        """Allow Enter on Done after the confirming key has been released."""
        if self.screen == Screen.DONE:
            self._done_keyboard_armed = True

    def accept_done_keyboard(self) -> None:
        """Enter on Done. Ignored while Return is still held from Erase."""
        if self.screen != Screen.DONE or not self._done_keyboard_armed:
            return
        if self.preview:
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
        if not self.discovery.boot_identified or self.discovery.error:
            self.screen = Screen.PICK_BLOCKED
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
        if self.screen != Screen.LAST_CHANCE:
            return
        if not self.erase_enabled or self.selected is None:
            return
        if (self.dry_run or self.preview) and isinstance(self.runner, NwipeRunner):
            self.error = "Preview and dry-run cannot exec nwipe."
            return
        discovery = self.discovery
        disk = self.selected
        if not self.dry_run and not self.preview:
            try:
                discovery = (self._rediscover or discover)()
            except (OSError, ValueError) as exc:
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

    def _finish(self, result: WipeResult) -> None:
        self.wipe_result = result
        self.screen = Screen.DONE
        self._done_keyboard_armed = False
        self.log_text = result.summary

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
