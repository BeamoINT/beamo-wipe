# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and run nwipe. Never autonuke without a single explicit device."""

from __future__ import annotations

import os
import re
import signal
import stat
import subprocess
import threading
import time
from typing import List, Optional

from beamo_wipe import NWIPE_PINNED_VERSION
from beamo_wipe.methods import (
    ALLOWED_NWIPE_METHODS,
    ALLOWED_ROUNDS,
    ALLOWED_VERIFY,
    METHODS,
    NwipeMethodSpec,
)
from beamo_wipe.models import WipeRequest, WipeResult
from beamo_wipe.safety import (
    SafetyError,
    assert_log_not_on_target,
    assert_not_boot,
    normalize_whole_disk,
    require_real_live_for_nwipe,
    truncate_log_file,
)

PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
NWIPE_VERSION_TIMEOUT_S = 5


def _verify_pinned_nwipe(binary: str) -> None:
    if os.path.basename(binary) != "nwipe":
        return
    try:
        proc = subprocess.run(
            [binary, "-V"],
            check=False,
            capture_output=True,
            text=True,
            timeout=NWIPE_VERSION_TIMEOUT_S,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafetyError("Cannot verify the nwipe binary.") from exc
    blob = f"{proc.stdout or ''}{proc.stderr or ''}"
    if NWIPE_PINNED_VERSION not in blob:
        raise SafetyError(
            f"Refusing to exec nwipe; pinned version is {NWIPE_PINNED_VERSION}."
        )


def build_nwipe_argv(request: WipeRequest) -> List[str]:
    spec: NwipeMethodSpec = METHODS[request.method]
    if spec.nwipe_method not in ALLOWED_NWIPE_METHODS:
        raise SafetyError("nwipe method is not in the allowlist.")
    if spec.verify not in ALLOWED_VERIFY:
        raise SafetyError("nwipe verify flag is not in the allowlist.")
    if spec.rounds not in ALLOWED_ROUNDS:
        raise SafetyError("nwipe rounds value is not allowed.")
    device = normalize_whole_disk(request.device)
    boot = normalize_whole_disk(request.boot_device)
    if device == boot:
        raise SafetyError("Target is the boot device.")
    assert_not_boot(device, boot)
    assert_log_not_on_target(request.logfile, device)
    argv = [
        "nwipe",
        "--autonuke",
        "--nogui",
        "--nowait",
        f"--method={spec.nwipe_method}",
        f"--verify={spec.verify}",
        f"--rounds={str(int(spec.rounds))}",
        f"--logfile={request.logfile}",
        "--PDFreportpath=noPDF",
        f"--exclude={boot}",
    ]
    if spec.noblank:
        argv.append("--noblank")
    argv.append(device)
    validate_argv(argv, request)
    return argv


def validate_argv(argv: List[str], request: WipeRequest) -> None:
    if any(a == "--force" or a.startswith("--force=") for a in argv):
        raise SafetyError("Refusing to pass --force to nwipe.")
    if argv[0] != "nwipe":
        raise SafetyError("First argument must be nwipe.")
    if "--autonuke" not in argv or "--nogui" not in argv:
        raise SafetyError("Non-interactive nwipe flags required.")
    device = normalize_whole_disk(request.device)
    boot = normalize_whole_disk(request.boot_device)
    if argv[-1] != device:
        raise SafetyError("Target device must be the only positional path, last.")
    extra_positionals = [a for a in argv[1:-1] if not a.startswith("-")]
    if extra_positionals:
        raise SafetyError("Refusing extra positional arguments.")
    devices = [a for a in argv if a.startswith("/dev/")]
    if device not in devices:
        raise SafetyError("Target device missing from argv.")
    extra = [d for d in devices if d != device]
    if extra:
        raise SafetyError("Refusing to pass more than one target device.")
    exclude = f"--exclude={boot}"
    if exclude not in argv:
        raise SafetyError("Boot device must be excluded.")
    logfile_flags = [a for a in argv if a.startswith("--logfile=")]
    if len(logfile_flags) != 1:
        raise SafetyError("Exactly one --logfile= flag is required.")
    log_value = logfile_flags[0].split("=", 1)[1]
    if log_value.startswith("/dev/") or log_value != request.logfile:
        raise SafetyError("Log path is not the approved log file.")
    assert_log_not_on_target(log_value, device)
    if "--autonuke" in argv and argv[-1].startswith("-"):
        raise SafetyError("autonuke without an explicit device is forbidden.")
    if any("\n" in a or "\r" in a or "\0" in a for a in argv):
        raise SafetyError("Refusing control characters in nwipe arguments.")


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
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.progress: Optional[float] = None
        self.result: Optional[WipeResult] = None
        self._log_tail = ""

    def start(self, request: WipeRequest) -> None:
        if os.path.basename(self.binary) == "nwipe":
            require_real_live_for_nwipe()
            _verify_pinned_nwipe(self.binary)
        assert_not_boot(request.device, request.boot_device)
        argv = build_nwipe_argv(request)
        argv[0] = self.binary
        if os.path.basename(self.binary) == "nwipe" and argv[0] != "nwipe" and os.path.basename(argv[0]) != "nwipe":
            raise SafetyError("Refusing to exec a binary that is not nwipe.")
        log_dir = os.path.dirname(request.logfile) or "/tmp/beamo-wipe"
        os.makedirs(log_dir, exist_ok=True)
        truncate_log_file(request.logfile, request.device)
        with self._lock:
            if self._proc is not None:
                raise SafetyError("A wipe is already running.")
            self.result = None
            self.progress = 0.0
            self._log_tail = ""
            self._last_sigusr1 = time.monotonic()
            # DEVNULL so nwipe's cleanup() printf cannot fill a PIPE and hang.
            # Progress is parsed from --logfile=. SIGUSR1 is rate-limited in poll().
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
            )

    def poll(self, request: WipeRequest) -> Optional[WipeResult]:
        proc = self._proc
        if proc is None:
            return self.result
        code = proc.poll()
        self._refresh_progress(request.logfile, proc)
        if code is None:
            now = time.monotonic()
            if now - getattr(self, "_last_sigusr1", 0.0) >= 2.0:
                try:
                    proc.send_signal(signal.SIGUSR1)
                    self._last_sigusr1 = now
                except (ProcessLookupError, OSError):
                    pass
            return None
        ok = code == 0
        self.result = WipeResult(
            ok=ok,
            exit_code=code,
            summary="finished" if ok else f"nwipe exited {code}",
            logfile=request.logfile,
        )
        self.progress = 100.0 if ok else self.progress
        self._proc = None
        return self.result

    def _refresh_progress(self, logfile: str, proc: subprocess.Popen) -> None:
        del proc
        try:
            fd = os.open(logfile, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return
        text = ""
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                return
            with os.fdopen(fd, "rb") as fh:
                fd = -1
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 8000))
                text = fh.read().decode("utf-8", errors="replace")
        except OSError:
            return
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        percent = parse_percent(text)
        if percent is not None:
            self.progress = percent

    def cancel(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self.result = WipeResult(
            ok=False,
            exit_code=proc.returncode if proc.returncode is not None else 143,
            summary="cancelled",
            logfile="",
        )


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
