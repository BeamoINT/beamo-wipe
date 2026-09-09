"""Additional real-Orca acceptance check for the split visual headings.
Run with PYTHONPATH=src:tests and private 72-DPI Xvfb/D-Bus, using pytest.
Reuses the repository's exact reader startup/wait/cleanup harness.
"""
import os
import subprocess
import sys
import time
import pytest
from test_accessible_runtime import ui, drain  # noqa: F401

def test_orca_announces_destructive_warnings(ui, tmp_path):
    """Real Orca reads GTK focus events via AT-SPI; no host audio/devices used."""
    import shutil

    if os.environ.get("BEAMO_TEST_ORCA_CHILD") != "1":
        # A fresh application and private bus avoid previously destroyed test
        # windows in the AT-SPI registry. No application behavior is mocked.
        result = subprocess.run(
            [
                "dbus-run-session",
                "--",
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"{__file__}::test_orca_announces_destructive_warnings",
            ],
            env={**os.environ, "BEAMO_TEST_ORCA_CHILD": "1"},
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "warning" not in result.stdout.lower(), result.stdout
        return
    assert shutil.which("orca"), "The supported Linux image requires Orca"
    assert os.environ.get("DBUS_SESSION_BUS_ADDRESS"), "Use dbus-run-session"
    audio = subprocess.Popen(
        ["pulseaudio", "--daemonize=no", "--exit-idle-time=30"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logfile = tmp_path / "orca.log"
    reader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """import runpy, sys
entry = runpy.run_path('/usr/bin/orca', run_name='orca_entry')
from orca import debug
# Line buffering changes only diagnostic delivery, not Orca speech generation.
debug.debugFile = open(sys.argv[1], 'w', buffering=1)
debug.debugLevel = debug.LEVEL_ALL
debug.eventDebugLevel = debug.LEVEL_OFF
sys.argv = ['orca']
sys.exit(entry['main']())
""",
            str(logfile),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def wait_for(phrase, *, since=0):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            drain()
            content = logfile.read_text(errors="replace") if logfile.exists() else ""
            if any(
                "SPEECH OUTPUT:" in line and phrase in line
                for line in content[since:].splitlines()
            ):
                # Finish the current AT-SPI event before replacing its widgets.
                # This models a reader finishing a screen before navigation.
                previous_size = -1
                quiet_since = time.monotonic()
                settle_deadline = time.monotonic() + 5
                while time.monotonic() < settle_deadline:
                    drain()
                    size = logfile.stat().st_size
                    if size != previous_size:
                        quiet_since = time.monotonic()
                        previous_size = size
                    elif time.monotonic() - quiet_since >= 0.3:
                        break
                    time.sleep(0.01)
                return
            assert reader.poll() is None, content[-3000:]
            time.sleep(0.02)
        pytest.fail(f"Orca did not announce {phrase!r}: {content[-3000:]}")

    try:
        wait_for("Screen reader on")
        app = ui()
        wizard = app.w
        wizard.skip_splash()
        wizard.accept_what()
        wizard.set_owner(True)
        wizard.continue_owner()
        wizard.select_disk(wizard.selectable[0].path)
        wizard.continue_pick()
        checkpoint = len(logfile.read_text(errors="replace"))
        app.render()
        wait_for(wizard.warning_text(), since=checkpoint)
        wizard.set_confirm_input(wizard.confirm.token)
        wizard.continue_confirm()
        wizard.continue_method()
        checkpoint = len(logfile.read_text(errors="replace"))
        app.render()
        wait_for(wizard.erase_label(), since=checkpoint)
        assert not wizard.runner.started
        app.close()
    finally:
        reader.terminate()
        try:
            reader.wait(timeout=10)
        except subprocess.TimeoutExpired:
            reader.kill()
            reader.wait(timeout=5)
        if audio.poll() is None:
            audio.terminate()
            audio.wait(timeout=5)
