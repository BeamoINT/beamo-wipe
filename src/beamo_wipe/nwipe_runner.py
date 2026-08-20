# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and run nwipe. Never autonuke without a single explicit device."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from typing import Callable, List, Optional

from beamo_wipe.methods import METHODS, NwipeMethodSpec
from beamo_wipe.models import MethodId, WipeRequest, WipeResult
from beamo_wipe.safety import SafetyError, assert_not_boot

PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")


def build_nwipe_argv(request: WipeRequest) -> List[str]:
    spec: NwipeMethodSpec = METHODS[request.method]
    if not request.device.startswith("/dev/"):
        raise SafetyError("Target must be a /dev/ path.")
    if request.device == request.boot_device:
        raise SafetyError("Target is the boot device.")
    argv = [
        "nwipe",
        "--autonuke",
        "--nogui",
        "--nowait",
        f"--method={spec.nwipe_method}",
        f"--verify={spec.verify}",
        f"--rounds={str(spec.rounds)}",
        f"--logfile={request.logfile}",
        "--PDFreportpath=noPDF",
        f"--exclude={request.boot_device}",
    ]
    if spec.noblank:
        argv.append("--noblank")
    argv.append(request.device)
    validate_argv(argv, request)
    return argv


def validate_argv(argv: List[str], request: WipeRequest) -> None:
    if "--force" in argv:
        raise SafetyError("Refusing to pass --force to nwipe.")
    if argv[0] != "nwipe":
        raise SafetyError("First argument must be nwipe.")
    if "--autonuke" not in argv or "--nogui" not in argv:
        raise SafetyError("Non-interactive nwipe flags required.")
    positionals = [a for a in argv[1:] if not a.startswith("-") and not a.startswith("/tmp/")]
    # logfile and exclude contain paths as --flag=value, so they are not positionals.
    devices = [a for a in argv if a.startswith("/dev/")]
    if request.device not in devices:
        raise SafetyError("Target device missing from argv.")
    if argv[-1] != request.device:
        raise SafetyError("Target device must be the only positional path, last.")
    extra = [d for d in devices if d != request.device]
    if extra:
        raise SafetyError("Refusing to pass more than one target device.")
    exclude = f"--exclude={request.boot_device}"
    if exclude not in argv:
        raise SafetyError("Boot device must be excluded.")
    # autonuke with NO device would wipe every disk — already checked last arg.
    if "--autonuke" in argv and argv[-1].startswith("-"):
        raise SafetyError("autonuke without an explicit device is forbidden.")
    _ = positionals  # kept for readability


def parse_percent(text: str) -> Optional[float]:
    last = None
    for match in PERCENT_RE.finditer(text or ""):
        value = float(match.group(1))
        if 0.0 <= value <= 100.0:
            last = value
    return last


class NwipeRunner:
    """Real subprocess runner. Use DryRunRunner in tests and --demo."""

    def __init__(self, binary: str = "nwipe") -> None:
        self.binary = binary
        self._proc: Optional[subprocess.Popen[str]] = None
        self._lock = threading.Lock()
        self.progress: Optional[float] = None
        self.result: Optional[WipeResult] = None
        self._log_tail = ""

    def start(self, request: WipeRequest) -> None:
        assert_not_boot(request.device, request.boot_device)
        argv = build_nwipe_argv(request)
        argv[0] = self.binary
        os.makedirs(os.path.dirname(request.logfile) or "/tmp/beamo-wipe", exist_ok=True)
        with self._lock:
            if self._proc is not None:
                raise SafetyError("A wipe is already running.")
            self.result = None
            self.progress = 0.0
            self._proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

    def poll(self, request: WipeRequest) -> Optional[WipeResult]:
        proc = self._proc
        if proc is None:
            return self.result
        code = proc.poll()
        self._refresh_progress(request.logfile, proc)
        if code is None:
            try:
                proc.send_signal(signal.SIGUSR1)
            except (ProcessLookupError, OSError):
                pass
            return None
        output = ""
        if proc.stdout:
            try:
                output = proc.stdout.read() or ""
            except OSError:
                output = ""
        ok = code == 0
        self.result = WipeResult(
            ok=ok,
            exit_code=code,
            summary="finished" if ok else f"nwipe exited {code}",
            logfile=request.logfile,
        )
        self.progress = 100.0 if ok else self.progress
        self._proc = None
        self._log_tail = output[-4000:]
        return self.result

    def _refresh_progress(self, logfile: str, proc: subprocess.Popen[str]) -> None:
        chunks = []
        try:
            with open(logfile, encoding="utf-8", errors="replace") as fh:
                chunks.append(fh.read()[-8000:])
        except OSError:
            pass
        percent = parse_percent("\n".join(chunks))
        if percent is not None:
            self.progress = percent

    def cancel(self) -> None:
        proc = self._proc
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


class DryRunRunner:
    """Pretend wipe. Never opens a real disk. Used by tests and --demo."""

    def __init__(self, duration_s: float = 2.5, fail: bool = False) -> None:
        self.duration_s = duration_s
        self.fail = fail
        self.progress: Optional[float] = None
        self.result: Optional[WipeResult] = None
        self._started: Optional[float] = None
        self._request: Optional[WipeRequest] = None
        self.started = False
        self.cancelled = False

    def start(self, request: WipeRequest) -> None:
        validate_argv(build_nwipe_argv(request), request)
        self._request = request
        self._started = time.monotonic()
        self.started = True
        self.cancelled = False
        self.progress = 0.0
        self.result = None

    def poll(self, request: WipeRequest) -> Optional[WipeResult]:
        if self._started is None:
            return self.result
        if self.cancelled:
            self.result = WipeResult(
                ok=False,
                exit_code=143,
                summary="cancelled",
                logfile=request.logfile,
            )
            self.progress = self.progress
            self._started = None
            return self.result
        elapsed = time.monotonic() - self._started
        frac = min(1.0, elapsed / max(0.1, self.duration_s))
        self.progress = round(frac * 100.0, 1)
        if frac < 1.0:
            return None
        if self.fail:
            self.result = WipeResult(
                ok=False,
                exit_code=1,
                summary="nwipe exited 1",
                logfile=request.logfile,
            )
        else:
            self.result = WipeResult(
                ok=True,
                exit_code=0,
                summary="finished",
                logfile=request.logfile,
            )
            self.progress = 100.0
        self._started = None
        return self.result

    def cancel(self) -> None:
        self.cancelled = True
