# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen state machine. UI layers only render this. No auto-start wipe."""

from __future__ import annotations

import time
from typing import Callable, Optional, Protocol

from beamo_wipe.copy import confirm_warning, erase_now_label
from beamo_wipe.methods import DEFAULT_METHOD
from beamo_wipe.models import (
    ConfirmSpec,
    Disk,
    DiscoveryResult,
    MethodId,
    Screen,
    WipeRequest,
    WipeResult,
)
from beamo_wipe.safety import (
    SafetyError,
    assert_boot_excluded,
    confirm_spec,
    selectable_disks,
    token_matches,
)
from beamo_wipe.nwipe_runner import DryRunRunner, build_nwipe_argv


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
    ) -> None:
        self.discovery = discovery
        self.runner = runner
        self._clock = clock or time.monotonic
        self.dry_run = dry_run
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

    @property
    def now(self) -> float:
        return self._clock()

    @property
    def selectable(self):
        return selectable_disks(self.discovery)

    @property
    def confirm(self) -> Optional[ConfirmSpec]:
        if self.selected is None:
            return None
        return confirm_spec(self.selected, self.selectable)

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
        if self.screen == Screen.SPLASH and self.now >= self._splash_until:
            self.screen = Screen.WHAT
        if self.screen == Screen.WORKING and self._wipe_request is not None:
            result = self.runner.poll(self._wipe_request)
            if result is not None:
                self._finish(result)

    def skip_splash(self) -> None:
        if self.screen == Screen.SPLASH:
            self.screen = Screen.WHAT

    def shutdown(self) -> None:
        self.wants_shutdown = True

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
        for disk in self.discovery.disks:
            if disk.path == path:
                if disk.is_boot:
                    return
                if disk not in self.selectable and disk.path not in {
                    d.path for d in self.selectable
                }:
                    return
                self.selected = disk
                return

    def continue_pick(self) -> None:
        if self.screen != Screen.PICK or self.selected is None or self.selected.is_boot:
            return
        self.confirm_input = ""
        self.screen = Screen.CONFIRM

    def set_confirm_input(self, text: str) -> None:
        self.confirm_input = text

    def continue_confirm(self) -> None:
        if self.screen != Screen.CONFIRM or not self.token_ok:
            return
        self.screen = Screen.METHOD

    def set_method(self, method: MethodId) -> None:
        self.method = method

    def continue_method(self) -> None:
        if self.screen != Screen.METHOD:
            return
        self.screen = Screen.LAST_CHANCE
        self._erase_until = self.now + COUNTDOWN_S

    def confirm_erase(self) -> None:
        if not self.erase_enabled or self.selected is None:
            return
        try:
            if not self.dry_run:
                from beamo_wipe.safety import require_live_or_dry_run

                require_live_or_dry_run()
            assert_boot_excluded(self.discovery)
            if not self.owner_ok:
                raise SafetyError("Owner checkbox is required.")
            if self.selected.is_boot:
                raise SafetyError("Refusing to erase the Beamo boot device.")
            spec = self.confirm
            if spec is None or not token_matches(self.confirm_input, spec):
                raise SafetyError("Confirm token does not match.")
            boot = self.discovery.boot
            if boot is None:
                raise SafetyError("Boot device missing.")
            from beamo_wipe.safety import logfile_for, assert_not_boot

            assert_not_boot(self.selected.path, boot.path)
            log = logfile_for(self.selected.path)
            request = WipeRequest(
                device=self.selected.path,
                method=self.method,
                boot_device=boot.path,
                logfile=log,
            )
            # Building argv is the last gate: autonuke without a device is rejected.
            build_nwipe_argv(request)
        except SafetyError as exc:
            self.error = str(exc)
            return
        self._wipe_request = request
        self.screen = Screen.WORKING
        self.runner.start(request)

    def _finish(self, result: WipeResult) -> None:
        self.wipe_result = result
        self.screen = Screen.DONE
        if result.ok:
            self.log_text = result.summary
        else:
            self.log_text = result.summary

    @property
    def done_ok(self) -> bool:
        return bool(self.wipe_result and self.wipe_result.ok)

    def open_advanced(self) -> None:
        if self.screen in (Screen.SPLASH, Screen.WORKING):
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

    def warning_text(self) -> str:
        if self.selected is None:
            return ""
        return confirm_warning(self.selected)

    def erase_label(self) -> str:
        if self.selected is None:
            return "Erase now"
        return erase_now_label(self.selected)


def make_demo_wizard(fail: bool = False) -> Wizard:
    from pathlib import Path

    from beamo_wipe.discover import discover, load_lsblk_json_text
    import os

    text = Path(__file__).with_name("demo_lsblk.json").read_text(encoding="utf-8")
    payload = load_lsblk_json_text(text)
    env = {
        **os.environ,
        "BEAMO_WIPE_DRY_RUN": "1",
        "BEAMO_WIPE_DEMO": "1",
        "BEAMO_WIPE_BOOT_DEVICE": "/dev/sdb",
    }
    discovery = discover(lsblk_payload=payload, boot_path="/dev/sdb", env=env)
    runner = DryRunRunner(duration_s=2.4, fail=fail)
    return Wizard(discovery, runner, dry_run=True)
