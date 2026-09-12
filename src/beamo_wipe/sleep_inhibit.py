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
        return proc is not None and proc.poll() is None

    def start(self) -> None:
        self.stop()
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
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired, AttributeError):
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("power", "sleep_inhibit_stop_failed", "terminate")
            except Exception:
                pass
