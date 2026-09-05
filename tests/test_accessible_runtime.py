# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendered GTK/ATK regressions. Run in Debian with fake disks, never nwipe."""

import json
import os
import subprocess
import sys
import time
from dataclasses import replace

import pytest

pytest.importorskip("gi")
from beamo_wipe.ui.accessible_wizard import AccessibleWizard, Gtk, Gdk  # noqa: E402
from beamo_wipe.demo import make_demo_wizard  # noqa: E402
from beamo_wipe.models import DiskKind, MethodId, Screen  # noqa: E402
from beamo_wipe.methods import METHODS  # noqa: E402
from beamo_wipe.outcomes import VIEWS  # noqa: E402
from test_result_presentations import CASES, case_evidence  # noqa: E402


def drain():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def widgets(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from widgets(child)


def text(app):
    return "\n".join(
        w.get_text() for w in widgets(app.window) if isinstance(w, Gtk.Label)
    )


@pytest.fixture
def ui():
    instances = []

    def build(wizard=None):
        app = AccessibleWizard(wizard or make_demo_wizard())
        app.window.resize(800, 600)
        instances.append(app)
        drain()
        return app

    yield build
    for app in instances:
        app.close()
    drain()


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_accessible_results_use_canonical_announcement(ui, case):
    wizard, _, _ = case_evidence(case)
    app = ui(wizard)
    expected = VIEWS[case[0]]
    assert expected.announcement in text(app)
    names = [w.get_accessible().get_name() for w in widgets(app.window)]
    assert expected.announcement in names
    assert wizard.selected.serial in text(app)
    assert "Check disks again (F5)" not in app.actions


@pytest.mark.parametrize("kind", [DiskKind.SSD, DiskKind.HDD, DiskKind.UNKNOWN])
@pytest.mark.parametrize("method", list(MethodId))
def test_accessible_methods_and_limits(ui, kind, method):
    wizard = make_demo_wizard()
    wizard.selected = replace(wizard.selectable[0], kind=kind)
    wizard.method = method
    wizard.screen = Screen.METHOD
    app = ui(wizard)
    assert wizard.storage_notice in text(app)
    for spec in METHODS.values():
        assert spec.summary in text(app)
    from types import SimpleNamespace

    assert app._key_press(app.window, SimpleNamespace(keyval=Gdk.KEY_l))
    drain()
    assert wizard.screen == Screen.LIMITS
    assert any(
        isinstance(w, Gtk.TextView) and not w.get_editable()
        for w in widgets(app.window)
    )
    app.actions["Back"].clicked()
    assert wizard.screen == Screen.METHOD and wizard.method == method


def test_accessible_refresh_requires_full_confirmation(ui, tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    app = ui()
    wizard = app.w
    wizard.skip_splash()
    app.render()
    app.actions["Continue"].clicked()
    check = next(w for w in widgets(app.window) if isinstance(w, Gtk.CheckButton))
    assert not app.actions["Continue"].get_sensitive()
    check.set_active(True)
    app.actions["Continue"].clicked()
    assert wizard.selected is None
    select = next(v for k, v in app.actions.items() if k.startswith("Select "))
    select.clicked()
    entry = next(w for w in widgets(app.window) if isinstance(w, Gtk.Entry))
    entry.set_text("WRONG")
    assert not app.actions["Continue"].get_sensitive()
    entry.set_text(wizard.confirm.token)
    app.actions["Continue"].clicked()
    app.actions["Continue"].clicked()
    assert wizard.screen == Screen.LAST_CHANCE
    assert "Last chance to stop" in text(app)
    assert "If this is the wrong disk, go back." in text(app)
    assert not app.actions["Erase now"].get_sensitive()
    stale_erase = app.actions["Erase now"]
    app.actions["Check disks again (F5)"].clicked()
    assert wizard.screen == Screen.WHAT
    assert wizard.selected is None and not wizard.owner_ok and not wizard.confirm_input
    # A queued action from the previous screen never starts a wipe.
    stale_erase.emit("clicked")
    assert not wizard.runner.started
    app.actions["Continue"].clicked()
    next(w for w in widgets(app.window) if isinstance(w, Gtk.CheckButton)).set_active(
        True
    )
    app.actions["Continue"].clicked()
    next(v for k, v in app.actions.items() if k.startswith("Select ")).clicked()
    next(w for w in widgets(app.window) if isinstance(w, Gtk.Entry)).set_text(
        wizard.confirm.token
    )
    app.actions["Continue"].clicked()
    wizard.set_method(MethodId.QUICK_ZERO)
    app.actions["Continue"].clicked()
    wizard._erase_until = 0
    app.update_status()
    assert app.actions["Erase now"].get_sensitive()
    app.actions["Erase now"].clicked()
    assert wizard.screen == Screen.WORKING and wizard.runner.started
    assert "Check disks again (F5)" not in app.actions
    app.actions["Cancel erase"].clicked()
    assert wizard.screen == Screen.DONE


def test_excluded_devices_are_read_only_and_no_selection(ui):
    wizard = make_demo_wizard(scenario="empty")
    wizard.skip_splash()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    app = ui(wizard)
    assert wizard.screen == Screen.PICK_EMPTY
    assert "Other detected devices" in text(app)
    readers = [w for w in widgets(app.window) if isinstance(w, Gtk.TextView)]
    assert readers and all(not w.get_editable() for w in readers)
    assert all(w.get_allocation().height >= 180 for w in readers)
    assert not any(name.startswith("Select ") for name in app.actions)


def test_held_activation_keys_cannot_repeat(ui):
    from types import SimpleNamespace

    app = ui()
    for key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
        event = SimpleNamespace(keyval=key)
        assert not app._key_press(app.window, event)
        assert app._key_press(app.window, event)
        app._key_release(app.window, event)
        assert not app._key_press(app.window, event)
        app._key_release(app.window, event)


def test_atspi_exposes_quick_zero_result_to_external_client(ui):
    pytest.importorskip("pyatspi")
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        pytest.fail("AT-SPI check requires dbus-run-session")
    wizard, _, _ = case_evidence(CASES[1])
    app = ui(wizard)
    script = """import json, time, pyatspi
names=[]
def walk(node):
    if node.name: names.append(node.name)
    for child in node: walk(child)
for attempt in range(30):
    names=[]
    walk(pyatspi.Registry.getDesktop(0))
    if any("verification was not performed" in name for name in names): break
    time.sleep(0.1)
print(json.dumps(names))
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while proc.poll() is None and time.monotonic() < deadline:
        drain()
        time.sleep(0.01)
    if proc.poll() is None:
        proc.kill()
    output, errors = proc.communicate(timeout=2)
    assert proc.returncode == 0, errors
    names = json.loads(output)
    assert wizard.result_view.announcement in names
    assert "Shut down" in names
    assert app.w.result_view.code == "unverified"


def test_low_resolution_footer_and_focus(ui):
    for screen in (
        Screen.WHAT,
        Screen.OWNER,
        Screen.PICK,
        Screen.METHOD,
        Screen.LAST_CHANCE,
        Screen.DONE,
    ):
        wizard = make_demo_wizard()
        wizard.selected = wizard.selectable[0]
        wizard.screen = screen
        app = ui(wizard)
        assert app.window.get_focus() is not None
        width, height = app.window.get_size()
        assert width <= 800 and height <= 600
        for button in app.footer.get_children():
            x, y = button.translate_coordinates(app.window, 0, 0)
            allocation = button.get_allocation()
            assert x >= 0 and y >= 0
            assert x + allocation.width <= width
            assert y + allocation.height <= height
        app.close()


def test_callback_failure_stops_with_system_origin(ui, monkeypatch):
    app = ui()
    app.w.screen = Screen.WORKING
    origins = []
    monkeypatch.setattr(app.w, "cancel_wipe", lambda **kw: origins.append(kw["origin"]))
    app._runtime_failure(RuntimeError, RuntimeError("fake"), None)
    assert app.failed and origins == ["system"]


def test_orca_announces_every_result(ui, tmp_path):
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
                f"{__file__}::test_orca_announces_every_result",
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

    def wait_for(phrase):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            drain()
            content = logfile.read_text(errors="replace") if logfile.exists() else ""
            if any(
                "SPEECH OUTPUT:" in line and phrase in line
                for line in content.splitlines()
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
        app = ui(case_evidence(CASES[0])[0])
        for case in CASES:
            wizard, _, _ = case_evidence(case)
            app.w = wizard
            app.render()
            wait_for(wizard.result_view.message)
        wizard.evidence = None
        app.render()
        wait_for(VIEWS["indeterminate"].message)
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


@pytest.mark.parametrize("live", [False, True])
def test_reader_lifecycle_owns_only_its_child(monkeypatch, live):
    from beamo_wipe.ui import accessible_wizard as module

    calls = []

    class Reader:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            calls.append(("wait", timeout))

    monkeypatch.setattr("beamo_wipe.safety.running_on_live_usb", lambda: live)
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda argv, **kw: calls.append(argv) or Reader()
    )

    class Window:
        def __init__(self, *args):
            pass

        def run(self):
            return 0

    monkeypatch.setattr(module, "AccessibleWizard", Window)
    assert module.run_accessible(make_demo_wizard()) == 0
    if live:
        assert calls == [
            ["/usr/bin/pulseaudio", "--start", "--exit-idle-time=60"],
            ["/usr/bin/orca"],
            "terminate",
            ("wait", 5),
        ]
    else:
        assert calls == []
