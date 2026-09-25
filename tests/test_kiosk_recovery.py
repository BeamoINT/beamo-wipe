"""Execute the shipped supervisor with every external action stubbed.

No installed launcher, disk command, X server, tty mutation, or power command
is reachable from this harness. Pipes deliberately exercise EOF recovery.
"""
from pathlib import Path
import subprocess
import signal
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHROOT = ROOT / "packaging/live/config/includes.chroot"
KIOSK = CHROOT / "usr/local/sbin/beamo-wipe-kiosk"
SERVICE = CHROOT / "etc/systemd/system/beamo-wipe-kiosk.service"


def prepare_kiosk(tmp_path, *, graphical=1, console=1, engine=1,
                  power=1, missing=(), accessible=False):
    commands = tmp_path / "commands"
    commands.mkdir()
    trace = tmp_path / "trace"
    # Fixed PATH in production is replaced only in this private test copy.
    # Even cleanup and sleep are stubs; no host device path is opened.
    bodies = {
        "startx": f'exit {graphical}',
        "beamo-wipe": f'exit {console}',
        "pgrep": f'exit {engine}',
        "systemctl": f'exit {power}',
        "sleep": "exit 0",
        "rm": "exit 0",
        "stty": "exit 0",
        "cat": "printf '%s\\n' beamo.ui=accessible" if accessible else "exit 0",
        "timeout": 'shift; "$@"',
        "espeak-ng": "exit 0",
    }
    functions = []
    for name, body in bodies.items():
        if name in missing:
            continue
        trace_line = f'printf "%s\\n" "{name} $*" >> "{trace}"'
        if name in ("beamo-wipe", "espeak-ng"):
            path = commands / name
            path.write_text(f"#!/bin/sh\n{trace_line}\n{body}\n")
            path.chmod(0o700)
        else:
            # Shell functions avoid platform-dependent process-launch latency
            # for no-op utilities, while recording their complete arguments.
            body = body.replace("exit ", "return ")
            guard = ""
            if name == "startx":
                guard = 'starts=$(( ${starts:-0} + 1 )); [ "$starts" -le 12 ] || exit 90; '
            functions.append(f"{name}() {{ {trace_line}; {guard}{body}; }}")
    script = KIOSK.read_text().replace("/tmp/beamo-wipe", str(tmp_path / "logs")).replace(
        "export PATH=/usr/sbin:/usr/bin:/sbin:/bin", f'export PATH="{commands}"'
    ).replace("/usr/local/bin/beamo-wipe", str(commands / "beamo-wipe"))
    script = script.replace("/dev/ttyS0", str(tmp_path / "no-serial"))
    script_path = tmp_path / "supervisor"
    script_path.write_text("#!/bin/sh\n" + "\n".join(functions) + "\n" + script)
    return script_path, trace


def run_kiosk(tmp_path, inputs="", **kwargs):
    script_path, trace = prepare_kiosk(tmp_path, **kwargs)
    try:
        result = subprocess.run(
            ["/bin/sh", str(script_path)], input=inputs, text=True,
            capture_output=True, timeout=10, env={"HOME": str(tmp_path)},
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Supervisor did not reach stable recovery within the harness deadline")
    calls = trace.read_text().splitlines() if trace.exists() else []
    return result, calls


def launches(calls, command):
    return [line for line in calls if line.startswith(command + " ")]


def test_crash_loop_stops_after_three_attempts(tmp_path):
    result, calls = run_kiosk(tmp_path)
    assert result.returncode == 0
    assert len(launches(calls, "startx")) == 3
    assert len(launches(calls, "beamo-wipe")) == 3
    assert "Automatic retries have stopped" in result.stdout
    assert "may still be running" in result.stdout
    assert "Input is unavailable" in result.stdout
    assert not launches(calls, "systemctl")


@pytest.mark.parametrize("missing", [("startx",), ("beamo-wipe",), ("startx", "beamo-wipe")])
def test_missing_dependencies_reach_recovery(tmp_path, missing):
    result, calls = run_kiosk(tmp_path, missing=missing)
    assert "Automatic retries have stopped" in result.stdout
    assert len(launches(calls, "startx")) <= 3
    assert len(launches(calls, "beamo-wipe")) <= 3


def test_successful_graphical_exit_does_not_crash_loop(tmp_path):
    result, calls = run_kiosk(tmp_path, graphical=0)
    assert len(launches(calls, "startx")) == 1
    assert not launches(calls, "beamo-wipe")
    assert "Beamo Wipe has closed" in result.stdout


def test_successful_console_fallback_returns_to_menu(tmp_path):
    result, calls = run_kiosk(tmp_path, console=0)
    assert len(launches(calls, "startx")) == 1
    assert len(launches(calls, "beamo-wipe")) == 1
    assert "Beamo Wipe has closed" in result.stdout


def test_manual_retries_do_not_reset_automatic_budget(tmp_path):
    result, calls = run_kiosk(tmp_path, "1\n2\n3\ninvalid\n")
    assert len(launches(calls, "startx")) == 4
    assert len(launches(calls, "beamo-wipe")) == 5
    assert "Graphical exit code: 1" in result.stdout
    assert "Text screen exit code: 1" in result.stdout
    assert "not available" in result.stdout
    assert "Choose 1, 2, 3, 4 or 5" in result.stdout


@pytest.mark.parametrize("choice,confirmation,action", [("4", "RESTART", "reboot"), ("5", "SHUTDOWN", "poweroff")])
@pytest.mark.parametrize("engine", [0, 1, 2, 127])
def test_power_requires_confirm_and_no_running_engine(tmp_path, choice, confirmation, action, engine):
    result, calls = run_kiosk(tmp_path, f"{choice}\n{confirmation}\n", engine=engine)
    power_calls = launches(calls, "systemctl")
    if engine == 1:
        assert power_calls == [f"systemctl --no-block {action}"]
        assert "request failed" in result.stdout
    else:
        assert not power_calls
        assert "cannot confirm that erasing has stopped" in result.stdout


@pytest.mark.parametrize("answer", ["", "no", "restart", "SHUTDOWN", "RESTART extra"])
def test_restart_cancellation_never_calls_power(tmp_path, answer):
    result, calls = run_kiosk(tmp_path, f"4\n{answer}\n")
    assert not launches(calls, "systemctl")
    assert "Cancelled" in result.stdout


def test_missing_process_check_blocks_power(tmp_path):
    result, calls = run_kiosk(tmp_path, "4\nRESTART\n", missing=("pgrep",))
    assert not launches(calls, "systemctl")
    assert "cannot confirm that erasing has stopped" in result.stdout


def test_accessible_recovery_speaks_safety_and_choices(tmp_path):
    result, calls = run_kiosk(tmp_path, accessible=True)
    spoken = " ".join(launches(calls, "espeak-ng"))
    assert "may still be running" in spoken
    assert "Try Beamo Wipe again" in spoken
    assert "Shut down" in spoken
    assert "Nothing is erased yet" not in spoken


def test_systemd_cannot_reset_supervisor_budget():
    service = SERVICE.read_text()
    assert "Restart=no" in service
    assert "TTYVTDisallocate=no" in service
    assert "TemporaryFileSystem=/tmp:mode=1777,nosuid,nodev,size=50%" in service
    assert "TemporaryFileSystem=/var/tmp:mode=1777,nosuid,nodev,size=10%" in service
    assert "ExecStart=/usr/local/sbin/beamo-wipe-kiosk" in service


def test_kiosk_private_tmp_is_a_volatile_filesystem():
    service = SERVICE.read_text()
    assert "TemporaryFileSystem=/tmp:mode=1777,nosuid,nodev,size=50%" in service
    assert "PrivateTmp=yes" not in service


@pytest.mark.parametrize("status", [126, 127, 139])
def test_permission_import_and_signal_failures_are_bounded(tmp_path, status):
    result, calls = run_kiosk(tmp_path, "3\n", graphical=status, console=status)
    assert len(launches(calls, "startx")) == 3
    assert len(launches(calls, "beamo-wipe")) == 3
    assert f"Graphical exit code: {status}" in result.stdout
    assert f"Text screen exit code: {status}" in result.stdout


@pytest.mark.parametrize("missing", [("sleep",), ("stty",), ("espeak-ng",), ("timeout",)])
def test_optional_terminal_speech_or_delay_failure_keeps_recovery(tmp_path, missing):
    result, calls = run_kiosk(tmp_path, missing=missing, accessible=True)
    assert "Automatic retries have stopped" in result.stdout
    assert len(launches(calls, "startx")) == 3


def test_existing_logs_are_preserved_and_raw_contents_not_exposed(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    log = folder / "diagnostics.log"
    log.write_text("private raw data\x1b[2J")
    result, _ = run_kiosk(tmp_path, "3\n")
    assert "Application log folder:" in result.stdout
    assert "private raw data" not in result.stdout
    assert log.read_text() == "private raw data\x1b[2J"


def test_log_symlink_is_not_advertised_as_available(tmp_path):
    (tmp_path / "logs").symlink_to(tmp_path, target_is_directory=True)
    result, _ = run_kiosk(tmp_path, "3\n")
    assert "Application log folder is not available" in result.stdout


def test_successful_power_request_does_not_claim_completed_shutdown(tmp_path):
    result, calls = run_kiosk(tmp_path, "5\nSHUTDOWN\n", power=0)
    assert launches(calls, "systemctl") == ["systemctl --no-block poweroff"]
    assert "Power request accepted. Wait for the computer to finish" in result.stdout


def test_missing_power_tool_leaves_recovery_available(tmp_path):
    result, calls = run_kiosk(tmp_path, "5\nSHUTDOWN\n1\n", missing=("systemctl",))
    assert "power request failed" in result.stdout
    assert len(launches(calls, "startx")) == 4


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_idle_recovery_is_stable_and_signals_never_relaunch(tmp_path, signum):
    script, trace = prepare_kiosk(tmp_path)
    output = tmp_path / "output"
    with output.open("w") as stream:
        proc = subprocess.Popen(["/bin/sh", str(script)], stdin=subprocess.PIPE,
                                stdout=stream, stderr=stream)
        try:
            deadline = time.monotonic() + 5
            while "Choose 1, 2, 3, 4 or 5" not in output.read_text():
                assert time.monotonic() < deadline, output.read_text()
                time.sleep(0.01)
            before = trace.read_text()
            time.sleep(0.05)
            assert proc.poll() is None
            assert trace.read_text() == before
            proc.send_signal(signum)
            # Some shells defer a trap until their blocking read returns.
            proc.communicate(input=b"\n", timeout=2)
            assert proc.returncode == 0
            assert trace.read_text() == before
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_recovery_restores_terminal_and_never_invokes_engine(tmp_path):
    result, calls = run_kiosk(tmp_path, "2\n3\n4\n\n")
    assert "stty sane" in calls
    assert "stty susp undef quit undef intr undef" in calls
    assert "\x1b[?25h" in result.stdout
    assert not launches(calls, "nwipe")
    assert not launches(calls, "systemctl")
    # Every fresh recovery frame fits an 80x25 terminal, including the prompt.
    for frame in result.stdout.split("\x1b[H")[1:]:
        visible = frame.split("\x1b")[0]
        assert max(map(len, visible.splitlines())) <= 80
        assert len(visible.splitlines()) <= 25


def test_long_invalid_input_is_not_executed_or_echoed(tmp_path):
    result, calls = run_kiosk(tmp_path, "x" * 4096 + "\n$(nwipe)\n")
    assert "Nothing was started" in result.stdout
    assert len(launches(calls, "startx")) == 3
    assert not launches(calls, "nwipe")
