# SPDX-License-Identifier: GPL-3.0-or-later
"""Best-effort block of OS sleep while an erase is running.

Does not wrap nwipe, does not block shutdown, and never prevents a wipe
from starting. Firmware lid and held power-button behavior are outside
this helper.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from beamo_wipe.safety import CLEAN_SUBPROCESS_ENV

INHIBIT_BIN = "/usr/bin/systemd-inhibit"
SLEEP_BIN = "/bin/sleep"
WHAT = "sleep:idle"
WHO = "Beamo Wipe"
WHY = "An erase is running"
MODE = "block"


def inhibit_argv() -> list[str]:
    return [
        INHIBIT_BIN,
        f"--what={WHAT}",
        f"--who={WHO}",
        f"--why={WHY}",
        f"--mode={MODE}",
        SLEEP_BIN,
        "infinity",
    ]


class SleepInhibit:
    """Hold a logind sleep/idle inhibit for the life of one erase."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None

    @property
    def active(self) -> bool:
        proc = self._proc
        if proc is None:
            return False
        try:
            return proc.poll() is None
        except (OSError, AttributeError):
            # Status could not be confirmed; retain the handle for another stop.
            return True

    def start(self) -> None:
        self.stop()
        if self._proc is not None:
            # The previous inhibitor may still be alive. Do not lose its handle
            # by replacing it with a second process.
            return
        if os.environ.get("BEAMO_WIPE_LIVE") != "1":
            return
        if os.environ.get("BEAMO_WIPE_DRY_RUN") == "1":
            return
        argv = inhibit_argv()
        if "--what=shutdown" in argv or "shutdown" in WHAT.split(":"):
            raise RuntimeError("sleep inhibit must not block shutdown")
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
                cwd="/",
                env=dict(CLEAN_SUBPROCESS_ENV),
                start_new_session=True,
            )
        except (OSError, ValueError):
            self._proc = None
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("power", "sleep_inhibit_unavailable", INHIBIT_BIN)
            except Exception:
                pass

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except (OSError, AttributeError):
                    proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
            self._proc = None
        except (OSError, subprocess.TimeoutExpired, AttributeError):
            # A failed terminate/kill leaves liveness uncertain. A successful
            # poll can still prove that the process exited in the meantime.
            try:
                if proc.poll() is not None:
                    self._proc = None
            except (OSError, AttributeError):
                pass
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("power", "sleep_inhibit_stop_failed", "terminate")
            except Exception:
                pass
