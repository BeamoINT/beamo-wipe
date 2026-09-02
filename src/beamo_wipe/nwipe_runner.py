# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and run nwipe. Never autonuke without a single explicit device."""

from __future__ import annotations

import fcntl
import os
import re
import signal
import stat
import subprocess
import threading
import time
from typing import List, Optional

from beamo_wipe import NWIPE_PINNED_PATH, NWIPE_PINNED_VERSION
from beamo_wipe.methods import (
    ALLOWED_NWIPE_METHODS,
    ALLOWED_ROUNDS,
    ALLOWED_VERIFY,
    METHODS,
    NwipeMethodSpec,
)
from beamo_wipe.models import WipeRequest, WipeResult
from beamo_wipe.safety import (
    CLEAN_SUBPROCESS_ENV,
    SafetyError,
    assert_existing_is_block_device,
    assert_log_not_on_target,
    assert_not_boot,
    assert_size_unchanged,
    block_rdev,
    normalize_whole_disk,
    require_real_live_for_nwipe,
    truncate_log_file,
)

PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
# nwipe 0.42 SIGUSR1: "/dev/vda: 045.23%, round 1 of 1, pass 1 of 1, eta …"
# Groups: percent, round i, round n, optional pass i, optional pass n.
NWIPE_PROGRESS_RE = re.compile(
    r":\s*(\d{1,3}(?:\.\d+)?)\s*%,\s*round\s+(\d+)\s+of\s+(\d+)"
    r"(?:,\s*pass\s+(\d+)\s+of\s+(\d+))?"
)
# nwipe 0.42 (device.c / nwipe.c) when the target is mounted and --force is unset.
NWIPE_BUSY_RE = re.compile(
    r"(?:is reported as IN USE|is IN USE but --force is not set, not wiping it)"
)
NWIPE_ABORT_RE = re.compile(r"Nwipe was aborted by the user")
# Wipe-time open (nwipe.c). device.c also logs
# "Unable to open device %s to obtain serial number" and continues.
NWIPE_OPEN_FAIL_RE = re.compile(r"Unable to open device '[^']+'\.")
# Drive Status column is exactly 8 chars between pipes (logging.c).
NWIPE_FAILURE_RE = re.compile(
    r"(?:>>> FAILURE! <<<|\|-FAILED-\||\|UABORTED\||\|INSANITY\|)"
)
NWIPE_GEOMETRY_RE = re.compile(r"No sane device geometry")
# Logged by nwipe_options_log() after pthread_sigmask(SIGUSR1) and the
# signal-handler thread exist. Until then SIGUSR1 uses the default action
# (terminate). The PRNG auto-bench (8 generators × 1.0s) runs before that.
NWIPE_SIGUSR1_READY_MARKERS = (
    "Program options are set as follows",
    " do not show GUI interface",
    "Using direct I/O",
    "Using cached I/O",
)
NWIPE_VERSION_TIMEOUT_S = 5
# Drive Status is written before create_system_multi_disc_pdf()/smartctl.
# 64KiB from EOF can be only that tail, hiding | Erased |.
NWIPE_COMPLETION_LOG_BYTES = 1024 * 1024
NWIPE_CLEAN_ENV = dict(CLEAN_SUBPROCESS_ENV)
# nwipe 0.42 `nwipe -V` prints this line (src/nwipe.c). Substring "0.42"
# would also match 0.420 / 10.42 / a binary that mentions the pin in help.
NWIPE_VERSION_LINE_RE = re.compile(
    rf"(?im)^nwipe version {re.escape(NWIPE_PINNED_VERSION)}(?:\s|$)"
)


def resolve_nwipe_binary(binary: str) -> str:
    """Production always execs the pinned path. Relative PATH lookup is forbidden."""
    if not binary:
        raise SafetyError("nwipe binary path is missing.")
    base = os.path.basename(binary)
    if base != "nwipe":
        # Hardened: only the `nwipe` basename is ever exec'd in production
        # (prevents /tmp/evil). For local pytest, allow any absolute fake
        # when BEAMO_WIPE_DRY_RUN is set — never on the live USB where
        # BEAMO_WIPE_LIVE=1 and BEAMO_WIPE_DRY_RUN is unset.
        if os.environ.get("BEAMO_WIPE_DRY_RUN") == "1":
            if not os.path.isabs(binary):
                raise SafetyError("Refusing to exec a relative non-nwipe binary.")
            return binary
        raise SafetyError("Refusing to exec a non-nwipe binary.")
    if binary in {"nwipe", NWIPE_PINNED_PATH}:
        return NWIPE_PINNED_PATH
    # Any other absolute path named `nwipe` is not the pinned path
    # — fail-closed (prevents /usr/local/bin/nwipe shadow). Test fakes
    # for nwipe must use the non-nwipe dry-run path above.
    raise SafetyError("nwipe is not at the pinned path.")


def nwipe_version_is_pinned(text: str) -> bool:
    """True only for the pinned `nwipe version X.Y` line, not a substring."""
    return bool(NWIPE_VERSION_LINE_RE.search(text or ""))


def _verify_pinned_nwipe(binary: str) -> None:
    if os.path.basename(binary) != "nwipe":
        return
    assert_nwipe_binary_safe(binary)
    try:
        proc = subprocess.run(
            [binary, "-V"],
            check=False,
            capture_output=True,
            text=True,
            timeout=NWIPE_VERSION_TIMEOUT_S,
            shell=False,
            env=NWIPE_CLEAN_ENV,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafetyError("Cannot verify the nwipe binary.") from exc
    blob = f"{proc.stdout or ''}{proc.stderr or ''}"
    if not nwipe_version_is_pinned(blob):
        raise SafetyError(
            f"Refusing to exec nwipe; pinned version is {NWIPE_PINNED_VERSION}."
        )


def assert_nwipe_binary_safe(path: str) -> None:
    """Pinned engine must be a root-owned ELF, not a script or a writable stub."""
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise SafetyError("Cannot stat nwipe binary.") from exc
    if stat.S_ISLNK(st.st_mode):
        raise SafetyError("Refusing to exec nwipe through a symlink.")
    if not stat.S_ISREG(st.st_mode):
        raise SafetyError("nwipe is not a regular file.")
    if not (st.st_mode & stat.S_IXUSR):
        raise SafetyError("nwipe is not executable.")
    if stat.S_IMODE(st.st_mode) & 0o022:
        raise SafetyError("nwipe binary is writable by group or others.")
    if st.st_mode & (stat.S_ISUID | stat.S_ISGID):
        raise SafetyError("nwipe binary must not be setuid or setgid.")
    if os.geteuid() == 0 and st.st_uid != 0:
        raise SafetyError("nwipe binary must be owned by root.")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SafetyError("Cannot open nwipe binary.") from exc
    try:
        # Re-validate after open to close TOCTOU: the fd must still be the
        # same regular file we just lstat'd, not a swapped inode.
        try:
            fst = os.fstat(fd)
        except OSError as exc:
            raise SafetyError("Cannot stat nwipe binary.") from exc
        if stat.S_ISLNK(fst.st_mode) or not stat.S_ISREG(fst.st_mode):
            raise SafetyError("nwipe is not a regular file.")
        if fst.st_ino != st.st_ino or fst.st_dev != st.st_dev:
            raise SafetyError("nwipe binary changed during check.")
        if stat.S_IMODE(fst.st_mode) & 0o022:
            raise SafetyError("nwipe binary is writable by group or others.")
        if fst.st_mode & (stat.S_ISUID | stat.S_ISGID):
            raise SafetyError("nwipe binary must not be setuid or setgid.")
        magic = os.read(fd, 4)
    finally:
        os.close(fd)
    if magic != b"\x7fELF":
        raise SafetyError("nwipe binary is not an ELF executable.")


def pinned_nwipe_already_running(*, exclude_pid: Optional[int] = None) -> bool:
    """True if another process is already exec'ing the pinned engine."""
    try:
        pinned = os.path.realpath(NWIPE_PINNED_PATH)
    except OSError:
        return False
    try:
        names = os.listdir("/proc")
    except OSError:
        return False
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        if exclude_pid is not None and pid == exclude_pid:
            continue
        try:
            exe = os.path.realpath(os.readlink(f"/proc/{name}/exe"))
        except OSError:
            continue
        if exe == pinned:
            return True
    return False


def build_nwipe_argv(request: WipeRequest) -> List[str]:
    try:
        spec: NwipeMethodSpec = METHODS[request.method]
    except KeyError as exc:
        raise SafetyError("Unknown wipe method.") from exc
    if spec.nwipe_method not in ALLOWED_NWIPE_METHODS:
        raise SafetyError("nwipe method is not in the allowlist.")
    if spec.verify not in ALLOWED_VERIFY:
        raise SafetyError("nwipe verify flag is not in the allowlist.")
    if spec.rounds not in ALLOWED_ROUNDS:
        raise SafetyError("nwipe rounds value is not allowed.")
    device = normalize_whole_disk(request.device, allow_optical=False)
    boot = normalize_whole_disk(request.boot_device, allow_optical=True)
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
    for required in ("--autonuke", "--nogui", "--nowait", "--PDFreportpath=noPDF"):
        if argv.count(required) != 1:
            raise SafetyError(f"Exactly one {required} flag is required.")
    for prefix in ("--method=", "--verify=", "--rounds=", "--logfile=", "--exclude="):
        hits = [a for a in argv if a.startswith(prefix)]
        if len(hits) != 1:
            raise SafetyError(f"Exactly one {prefix} flag is required.")
    if argv.count("--noblank") > 1:
        raise SafetyError("Refusing duplicate --noblank flags.")
    device = normalize_whole_disk(request.device, allow_optical=False)
    boot = normalize_whole_disk(request.boot_device, allow_optical=True)
    if argv[-1] != device:
        raise SafetyError("Target device must be the only positional path, last.")
    extra_positionals = [a for a in argv[1:-1] if not a.startswith("-")]
    if extra_positionals:
        raise SafetyError("Refusing extra positional arguments.")
    for flag in argv[1:-1]:
        if not _nwipe_flag_allowed(flag):
            raise SafetyError("Refusing unexpected nwipe argument.")
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
    if "--PDFreportpath=noPDF" not in argv:
        raise SafetyError("PDF reports must be disabled.")
    if "--autonuke" in argv and argv[-1].startswith("-"):
        raise SafetyError("autonuke without an explicit device is forbidden.")
    if any("\n" in a or "\r" in a or "\0" in a for a in argv):
        raise SafetyError("Refusing control characters in nwipe arguments.")


def _nwipe_flag_allowed(flag: str) -> bool:
    if flag in {"--autonuke", "--nogui", "--nowait", "--noblank"}:
        return True
    if flag == "--PDFreportpath=noPDF":
        return True
    if flag.startswith("--method="):
        return flag.split("=", 1)[1] in ALLOWED_NWIPE_METHODS
    if flag.startswith("--verify="):
        return flag.split("=", 1)[1] in ALLOWED_VERIFY
    if flag.startswith("--rounds="):
        try:
            return int(flag.split("=", 1)[1], 10) in ALLOWED_ROUNDS
        except ValueError:
            return False
    if flag.startswith("--logfile="):
        return bool(flag.split("=", 1)[1]) and not flag.split("=", 1)[1].startswith("-")
    if flag.startswith("--exclude="):
        rest = flag.split("=", 1)[1]
        if not rest or any(ch in rest for ch in " \t\n\r\0,;"):
            return False
        try:
            normalize_whole_disk(rest, allow_optical=True)
        except SafetyError:
            return False
        return True
    return False


def parse_percent(text: str) -> Optional[float]:
    last = None
    for match in PERCENT_RE.finditer(text or ""):
        value = float(match.group(1))
        if 0.0 <= value <= 100.0:
            last = value
    return last


def _device_log_names(device: str) -> List[str]:
    names = []
    for raw in (device, os.path.realpath(device), os.path.basename(device)):
        if raw and raw not in names:
            names.append(raw)
    return names


def _line_mentions_device(line: str, device: str) -> bool:
    for name in _device_log_names(device):
        if not name:
            continue
        if re.search(r"(?:^|[^\w/])" + re.escape(name) + r"(?:[^\w]|$)", line):
            return True
    return False


def target_skipped_busy(log_text: str, device: str) -> bool:
    """True if nwipe logged that *this* target is in use and was not wiped."""
    text = log_text or ""
    for line in text.splitlines():
        if not NWIPE_BUSY_RE.search(line):
            continue
        if _line_mentions_device(line, device):
            return True
    return False


def nwipe_accepts_sigusr1(log_text: str) -> bool:
    """True once the log shows nwipe 0.42 has installed its SIGUSR1 handler."""
    text = log_text or ""
    return any(marker in text for marker in NWIPE_SIGUSR1_READY_MARKERS)


def _target_open_failed(log_text: str, device: str) -> bool:
    for line in (log_text or "").splitlines():
        if not NWIPE_OPEN_FAIL_RE.search(line):
            continue
        if _line_mentions_device(line, device):
            return True
    return False


def _target_geometry_failed(log_text: str, device: str) -> bool:
    for line in (log_text or "").splitlines():
        if not NWIPE_GEOMETRY_RE.search(line):
            continue
        if _line_mentions_device(line, device):
            return True
    return False


def _target_reported_failure(log_text: str, device: str) -> bool:
    for line in (log_text or "").splitlines():
        if not NWIPE_FAILURE_RE.search(line):
            continue
        if _line_mentions_device(line, device):
            return True
    return False


def _iter_target_progress(log_text: str, device: str):
    """Yield SIGUSR1 progress matches for this device, in log order."""
    for line in (log_text or "").splitlines():
        if not _line_mentions_device(line, device):
            continue
        match = NWIPE_PROGRESS_RE.search(line)
        if match is None:
            continue
        value = float(match.group(1))
        if 0.0 <= value <= 100.0:
            yield match, value


def _target_last_percent(log_text: str, device: str) -> Optional[float]:
    """Last SIGUSR1 progress percent for this device.

    The Erasure Summary table also prints ``0.00%`` / ``100.00%`` on a
    device line. That is not live progress and must not replace a SIGUSR1
    reading (WORKING would jump to 0% just before Done).
    """
    last = None
    for _match, value in _iter_target_progress(log_text, device):
        last = value
    return last


def _job_percent_from_match(match: re.Match, value: float) -> float:
    """Map a pass-local SIGUSR1 percent onto the whole job.

    dodshort reports 100% at the end of each of 3 passes. Showing that as
    the only progress number makes WORKING flash 100% then wrap to 0%.
    """
    round_i, round_n = int(match.group(2)), int(match.group(3))
    if round_n <= 0:
        return value
    pass_i, pass_n = match.group(4), match.group(5)
    if pass_i is None or pass_n is None:
        total = round_n
        done = max(0, round_i - 1)
        return min(100.0, (done + value / 100.0) / total * 100.0)
    pass_i_n, pass_n_n = int(pass_i), int(pass_n)
    if pass_n_n <= 0:
        return value
    total = round_n * pass_n_n
    done = (round_i - 1) * pass_n_n + (pass_i_n - 1)
    return min(100.0, (done + value / 100.0) / total * 100.0)


def _target_job_percent(log_text: str, device: str) -> Optional[float]:
    last = None
    for match, value in _iter_target_progress(log_text, device):
        last = _job_percent_from_match(match, value)
    return last


def _progress_is_final_pass(match: re.Match) -> bool:
    """True if this SIGUSR1 line is the last pass of the last round."""
    round_i, round_n = int(match.group(2)), int(match.group(3))
    if round_i != round_n:
        return False
    pass_i, pass_n = match.group(4), match.group(5)
    if pass_i is None or pass_n is None:
        return True
    return int(pass_i) == int(pass_n)


def _target_reached_last_pass(log_text: str, device: str) -> bool:
    """True if the last SIGUSR1 line is 100% of the last pass of the last round.

    Extra thorough (dodshort) reports 100% at the end of each of 3 passes.
    That is not Finished unless the last logged pass is the last pass.
    """
    last = None
    for match, value in _iter_target_progress(log_text, device):
        last = value >= 100.0 and _progress_is_final_pass(match)
    return bool(last)


def _target_reported_success(log_text: str, device: str) -> bool:
    """True only for the Drive Status 'Erased' row.

    nwipe 0.42 SIGUSR1 logs ``/dev/X: Success`` whenever the wipe thread
    pointer is unset and result is 0 — including after nwipe_options_log()
    and before pthread_create. That line is not a completed wipe.
    """
    for line in (log_text or "").splitlines():
        if not _line_mentions_device(line, device):
            continue
        if re.search(r"\|\s*Erased\s*\|", line):
            return True
    return False


def evaluate_nwipe_completion(
    exit_code: int, log_text: str, device: str
) -> tuple[bool, str]:
    """Map nwipe's process exit to owner-facing success.

    nwipe 0.42 returns 0 and logs "Nwipe successfully completed" when no wipe
    thread ran (busy skip, open failure, insane geometry) and also after a
    user abort that already logged a percent. SIGUSR1 may log
    ``/dev/X: Success`` before pthread_create. 100% of pass 1 of 3 (dodshort)
    is not Finished. Those must not become Finished.
    """
    if target_skipped_busy(log_text, device):
        return False, "nwipe skipped the disk because it is in use"
    if NWIPE_ABORT_RE.search(log_text or ""):
        return False, "nwipe was aborted"
    if _target_open_failed(log_text, device):
        return False, "nwipe could not open the disk"
    if _target_geometry_failed(log_text, device):
        return False, "nwipe could not use the disk"
    if _target_reported_failure(log_text, device):
        return False, "nwipe reported a failure"
    if exit_code != 0:
        return False, f"nwipe exited {exit_code}"
    if _target_reported_success(log_text, device):
        return True, "finished"
    if _target_reached_last_pass(log_text, device):
        return True, "finished"
    return False, "nwipe exited without wiping"


class NwipeRunner:
    """Real subprocess runner. Use DryRunRunner in tests and --demo."""

    def __init__(self, binary: str = NWIPE_PINNED_PATH) -> None:
        self.binary = binary
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._lock_fd: Optional[int] = None
        self.progress: Optional[float] = None
        self.result: Optional[WipeResult] = None
        self._log_tail = ""
        self._last_sigusr1 = 0.0
        self._sigusr1_armed = False

    def start(self, request: WipeRequest) -> None:
        resolved = resolve_nwipe_binary(self.binary)
        real_engine = os.path.basename(resolved) == "nwipe"
        if real_engine:
            require_real_live_for_nwipe()
            if pinned_nwipe_already_running(exclude_pid=os.getpid()):
                raise SafetyError("A wipe is already running.")
            _verify_pinned_nwipe(resolved)
            assert_existing_is_block_device(request.device, required=True)
            assert_size_unchanged(request.device, request.device_size_bytes)
            now_rdev = block_rdev(request.device)
            if now_rdev is None:
                raise SafetyError("Target is not a block device.")
            if not request.device_rdev or now_rdev != request.device_rdev:
                raise SafetyError("Disk identity changed. Refusing to erase.")
        assert_not_boot(request.device, request.boot_device)
        argv = build_nwipe_argv(request)
        argv[0] = resolved
        assert_log_not_on_target(request.logfile, request.device)
        truncate_log_file(request.logfile, request.device)
        popen_env = None
        if real_engine:
            env = dict(NWIPE_CLEAN_ENV)
            env["TERM"] = "linux"
            popen_env = env
        with self._lock:
            if self._proc is not None:
                raise SafetyError("A wipe is already running.")
            self._acquire_wipe_lock(request)
            self.result = None
            self.progress = None
            self._log_tail = ""
            self._last_sigusr1 = 0.0
            self._sigusr1_armed = False
            popen_kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "shell": False,
                "close_fds": True,
                "cwd": "/",
                "env": popen_env,
                # New session: the wizard ignores SIGINT, but nwipe is in the
                # same TTY group and would abort on Ctrl-C / leftover INTR.
                "start_new_session": True,
            }
            # Python os.open uses O_CLOEXEC. pass_fds keeps the flock in the
            # child so a crashed wizard cannot start a second nwipe.
            if self._lock_fd is not None:
                popen_kwargs["pass_fds"] = (self._lock_fd,)
            try:
                self._proc = subprocess.Popen(argv, **popen_kwargs)
            except Exception:
                self._release_wipe_lock()
                raise

    def poll(self, request: WipeRequest) -> Optional[WipeResult]:
        proc = self._proc
        if proc is None:
            return self.result
        code = proc.poll()
        self._refresh_progress(request.logfile, request.device)
        if code is None:
            if not getattr(self, "_sigusr1_armed", False):
                ready_text = self._read_log_tail(request.logfile, 65536)
                if nwipe_accepts_sigusr1(ready_text):
                    self._sigusr1_armed = True
            now = time.monotonic()
            if getattr(self, "_sigusr1_armed", False) and now - getattr(
                self, "_last_sigusr1", 0.0
            ) >= 2.0:
                try:
                    proc.send_signal(signal.SIGUSR1)
                    self._last_sigusr1 = now
                except (ProcessLookupError, OSError) as exc:
                    try:
                        from beamo_wipe.diagnostics import log_diag

                        log_diag("nwipe", "sigusr1_failed", type(exc).__name__)
                    except Exception:
                        pass
            return None
        log_text = self._read_log_tail(request.logfile, NWIPE_COMPLETION_LOG_BYTES)
        if log_text:
            self._log_tail = log_text
            percent = _target_job_percent(log_text, request.device)
            if percent is not None:
                self.progress = percent
        ok, summary = evaluate_nwipe_completion(code, log_text, request.device)
        self.result = WipeResult(
            ok=ok,
            exit_code=code,
            summary=summary,
            logfile=request.logfile,
        )
        self.progress = 100.0 if ok else self.progress
        self._proc = None
        self._release_wipe_lock()
        return self.result

    def _read_log_tail(self, logfile: str, nbytes: int) -> str:
        try:
            fd = os.open(logfile, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            # Missing log is expected before nwipe creates it; permission/
            # symlink errors are diagnostic for maintainer (log isolation)
            if getattr(exc, "errno", None) not in (2,):  # not ENOENT
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("nwipe", "log_open_failed", type(exc).__name__)
                except Exception:
                    pass
            return ""
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("nwipe", "log_not_regular", f"mode={oct(st.st_mode)}")
                except Exception:
                    pass
                return ""
            with os.fdopen(fd, "rb") as fh:
                fd = -1
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - nbytes))
                return fh.read().decode("utf-8", errors="replace")
        except OSError as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("nwipe", "log_read_failed", type(exc).__name__)
            except Exception:
                pass
            return ""
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _refresh_progress(self, logfile: str, device: str) -> None:
        text = self._read_log_tail(logfile, 8000)
        if not text:
            return
        self._log_tail = text
        percent = _target_job_percent(text, device)
        if percent is not None:
            self.progress = percent

    def _acquire_wipe_lock(self, request: WipeRequest) -> None:
        directory = os.path.dirname(request.logfile)
        if not directory:
            raise SafetyError("Cannot lock: log directory missing.")
        lock_path = os.path.join(directory, "wipe.lock")
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise SafetyError(f"Cannot create wipe lock: {exc}") from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                os.close(fd)
                raise SafetyError("Wipe lock is not a regular file.")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise SafetyError("A wipe is already running.")
        except Exception:
            os.close(fd)
            raise
        self._lock_fd = fd

    def _release_wipe_lock(self) -> None:
        fd = self._lock_fd
        self._lock_fd = None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("nwipe", "unlock_failed", type(exc).__name__)
            except Exception:
                pass
        try:
            os.close(fd)
        except OSError as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("nwipe", "lock_close_failed", type(exc).__name__)
            except Exception:
                pass

    def cancel(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
        except OSError as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("nwipe", "cancel_terminate_failed", type(exc).__name__)
            except Exception:
                pass
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("nwipe", "cancel_kill_failed", type(exc).__name__)
                except Exception:
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("nwipe", "cancel_kill_still_alive", type(exc).__name__)
                except Exception:
                    pass
        self.result = WipeResult(
            ok=False,
            exit_code=proc.returncode if proc.returncode is not None else 143,
            summary="cancelled",
            logfile="",
        )
        self._release_wipe_lock()


class DryRunRunner:
    """Pretend wipe. Never opens a real disk. Used by tests and --demo."""

    def __init__(
        self,
        duration_s: float = 2.5,
        fail: bool = False,
        clock=None,
    ) -> None:
        self.duration_s = duration_s
        self.fail = fail
        self._clock = clock or time.monotonic
        self.progress: Optional[float] = None
        self.result: Optional[WipeResult] = None
        self._started: Optional[float] = None
        self._request: Optional[WipeRequest] = None
        self.started = False
        self.cancelled = False

    def start(self, request: WipeRequest) -> None:
        validate_argv(build_nwipe_argv(request), request)
        self._request = request
        self._started = self._clock()
        self.started = True
        self.cancelled = False
        self.progress = None
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
        elapsed = self._clock() - self._started
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
