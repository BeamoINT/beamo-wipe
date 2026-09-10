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
from beamo_wipe.ui.accessible_wizard import AccessibleWizard, Gtk, Gdk, GLib  # noqa: E402
from beamo_wipe.demo import make_demo_wizard  # noqa: E402
from beamo_wipe.models import DiskKind, MethodId, Screen  # noqa: E402
from beamo_wipe.methods import METHODS  # noqa: E402
from beamo_wipe.outcomes import VIEWS  # noqa: E402
from test_result_presentations import CASES, case_evidence  # noqa: E402


def drain():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def wait_for_window_size(window, size):
    # resize() queues an X11 request. An empty GTK event queue does not mean
    # the server's configure event or the next layout frame has arrived yet.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        drain()
        allocation = window.get_allocation()
        if (
            window.get_mapped()
            and tuple(window.get_size()) == size
            and (allocation.width, allocation.height) == size
        ):
            return
        time.sleep(0.01)
    pytest.fail(
        f"Window did not reach {size}: size={tuple(window.get_size())}, "
        f"allocation={(allocation.width, allocation.height)}, "
        f"mapped={window.get_mapped()}"
    )


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

    def build(wizard=None, *, size=(800, 600)):
        app = AccessibleWizard(wizard or make_demo_wizard())
        instances.append(app)
        if size is not None:
            app.window.resize(*size)
        else:
            size = tuple(app.window.get_default_size())
        wait_for_window_size(app.window, size)
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
    wait_transition(app)
    assert wizard.screen == Screen.WORKING and wizard.runner.started
    assert "Check disks again (F5)" not in app.actions
    app.actions["Cancel erase"].clicked()
    wait_transition(app)
    assert wizard.screen == Screen.DONE


def test_excluded_devices_are_read_only_and_no_selection(ui):
    wizard = make_demo_wizard(scenario="empty")
    wizard.skip_splash()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    app = ui(wizard)
    assert wizard.screen == Screen.PICK_EMPTY
    assert "not erasable" in text(app).lower()
    assert wizard.discovery.boot.display_name in text(app)
    assert wizard.discovery.boot.path not in text(app)
    assert "Other detected devices" in text(app)
    readers = [w for w in widgets(app.window) if isinstance(w, Gtk.TextView)]
    assert readers and all(not w.get_editable() for w in readers)
    assert all(w.get_allocation().height >= 180 for w in readers)
    assert not any(name.startswith("Select ") for name in app.actions)


def test_last_chance_enter_without_erase_focus_never_erases(ui):
    from types import SimpleNamespace

    wizard = make_demo_wizard()
    wizard.skip_splash()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    wizard._erase_until = 0
    app = ui(wizard)
    app.update_status()
    erase = app.actions["Erase now"]
    assert erase.get_sensitive()
    warning = next(
        w
        for w in widgets(app.window)
        if isinstance(w, Gtk.Label) and w.get_can_focus() and w is not erase
    )
    warning.grab_focus()
    drain()
    assert app.window.get_focus() is warning
    assert app._key_press(app.window, SimpleNamespace(keyval=Gdk.KEY_Return))
    drain()
    assert wizard.screen == Screen.LAST_CHANCE
    assert not wizard.runner.started
    app._key_release(app.window, SimpleNamespace(keyval=Gdk.KEY_Return))
    erase.grab_focus()
    drain()
    assert app._key_press(app.window, SimpleNamespace(keyval=Gdk.KEY_Return))
    wait_transition(app)
    assert wizard.screen == Screen.WORKING and wizard.runner.started


def test_escape_cancels_working_erase(ui):
    from types import SimpleNamespace

    wizard = make_demo_wizard()
    wizard.skip_splash()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    wizard._erase_until = 0
    wizard.confirm_erase()
    app = ui(wizard)
    assert wizard.screen == Screen.WORKING
    assert app._key_press(app.window, SimpleNamespace(keyval=Gdk.KEY_Escape))
    wait_transition(app)
    assert wizard.screen == Screen.DONE
    assert not wizard.runner.started or wizard.wipe_result is not None


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


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_result_focus_does_not_create_a_text_selection(ui, case):
    wizard, _, _ = case_evidence(case)
    app = ui(wizard)
    heading = app.window.get_focus()
    assert isinstance(heading, Gtk.Label)
    assert heading.get_text() == wizard.result_view.announcement
    assert heading.get_can_focus()
    assert heading.get_selectable()
    has_selection, start, end = heading.get_selection_bounds()
    assert not has_selection and start == end


@pytest.mark.parametrize("workarea_size", [(800, 600), (1600, 1000)])
def test_accessible_default_fits_monitor_workarea(ui, monkeypatch, workarea_size):
    workarea = Gdk.Rectangle()
    workarea.width, workarea.height = workarea_size
    monkeypatch.setattr(Gdk.Monitor, "get_workarea", lambda _monitor: workarea)
    app = ui(size=None)
    expected = (min(900, workarea.width), min(700, workarea.height))
    assert tuple(app.window.get_default_size()) == expected
    assert tuple(app.window.get_size()) == expected


def test_accessible_window_shrinks_after_default_is_mapped(ui, monkeypatch):
    workarea = Gdk.Rectangle()
    workarea.width, workarea.height = 1600, 1000
    monkeypatch.setattr(Gdk.Monitor, "get_workarea", lambda _monitor: workarea)
    app = ui(size=None)
    assert tuple(app.window.get_size()) == (900, 700)
    app.window.resize(800, 600)
    wait_for_window_size(app.window, (800, 600))
    assert tuple(app.window.get_size()) == (800, 600)


@pytest.mark.parametrize("screen", list(Screen))
def test_every_accessible_screen_keeps_actions_inside_800x600(ui, screen):
    wizard = make_demo_wizard()
    wizard.skip_splash()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.screen = screen  # presentation only; no process is started
    app = ui(wizard)
    for button in widgets(app.footer):
        if not isinstance(button, Gtk.Button):
            continue
        x, y = button.translate_coordinates(app.window, 0, 0)
        assert x >= 0 and y >= 0
        assert x + button.get_allocated_width() <= 800
        assert y + button.get_allocated_height() <= 600


def test_accessible_method_choices_visible_above_grouped_actions(ui):
    wizard = make_demo_wizard()
    wizard.selected = wizard.selectable[0]
    wizard.screen = Screen.METHOD
    app = ui(wizard)
    footer_y = app.footer.translate_coordinates(app.window, 0, 0)[1]
    choices = [w for w in widgets(app.body) if isinstance(w, Gtk.RadioButton)]
    assert len(choices) == len(METHODS)
    for choice in choices:
        _, y = choice.translate_coordinates(app.window, 0, 0)
        assert y >= 0
        assert y + choice.get_allocated_height() <= footer_y
    # Keyboard traversal reaches every footer action through native controls.
    reached = set()
    for _ in range(50):
        app.window.child_focus(Gtk.DirectionType.TAB_FORWARD)
        focus = app.window.get_focus()
        if isinstance(focus, Gtk.Button):
            reached.add(focus)
    assert set(app.actions.values()) <= reached


@pytest.mark.parametrize("screen", [Screen.CONFIRM, Screen.LAST_CHANCE])
def test_accessible_long_identity_and_warning_remain_readable(ui, screen):
    from beamo_wipe import copy as C

    wizard = make_demo_wizard()
    wizard.selected = replace(wizard.selectable[0], model="M" * 128, serial="A" * 128)
    wizard.screen = screen
    app = ui(wizard)
    assert wizard.selected.serial in text(app)
    assert wizard.selected.path not in text(app)
    assert "You cannot get" in text(app)
    assert (C.TITLE_CONFIRM if screen == Screen.CONFIRM else C.TITLE_LAST) in text(app)
    arrival = app.window.get_focus()
    warning = wizard.warning_text() if screen == Screen.CONFIRM else wizard.erase_label()
    assert arrival.get_text() == warning
    has_selection, start, end = arrival.get_selection_bounds()
    assert not has_selection and start == end
    assert not wizard.runner.started


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
    monkeypatch.setattr(app.w, "begin_cancel", lambda **kw: origins.append(kw["origin"]))
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
        app = ui(case_evidence(CASES[0])[0])
        for case in CASES:
            wizard, _, _ = case_evidence(case)
            app.w = wizard
            checkpoint = len(logfile.read_text(errors="replace"))
            app.render()
            wait_for(wizard.result_view.message, since=checkpoint)
        wizard.evidence = None
        checkpoint = len(logfile.read_text(errors="replace"))
        app.render()
        wait_for(VIEWS["indeterminate"].message, since=checkpoint)
        # Short visual headings must not suppress the full warning on arrival.
        # An overridden accessible name alone is insufficient: Orca reads the
        # label's text interface instead. Exercise the actual speech output.
        app.w = wizard = make_demo_wizard()
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


def test_accessible_startup_diagnostic_path(ui):
    w = make_demo_wizard()
    w.preview = False
    w.screen = Screen.PICK_BLOCKED
    app = ui(w)
    assert "Diagnostic report" in app.actions
    w.open_diagnostic()
    app.render()
    drain()
    assert "Support diagnostics only" in text(app)
    assert "Prepare" in app.actions
    assert w.evidence is None and not w.can_save_report


@pytest.mark.parametrize("wanted", [True, False])
def test_accessible_report_help_intent_refresh_and_scroll(ui, wanted):
    from beamo_wipe import copy as C

    w = make_demo_wizard()
    w.skip_splash()
    app = ui(w)
    app.actions[C.REPORT_HELP_TITLE].clicked()
    drain()
    reader = next(
        item for item in widgets(app.window) if isinstance(item, Gtk.TextView)
    )
    assert reader.get_accessible().get_name() == C.REPORT_HELP_TEXT
    choice = next(
        item for item in widgets(app.window) if isinstance(item, Gtk.CheckButton)
    )
    assert not choice.get_active()
    choice.set_active(wanted)
    assert w.report_wanted is wanted
    fresh = w.discovery
    w._rediscover = lambda: fresh
    app.actions["Check disks again (F5)"].clicked()
    drain()
    assert w.report_wanted is wanted and w.screen == Screen.WHAT
    assert w.selected is None and not w.owner_ok and not w.confirm_input
    app.actions[C.REPORT_HELP_TITLE].clicked()
    drain()
    choice = next(
        item for item in widgets(app.window) if isinstance(item, Gtk.CheckButton)
    )
    assert choice.get_active() is wanted
    app.actions[C.BTN_BACK].clicked()
    drain()
    assert w.screen == Screen.WHAT and not w.runner.started


@pytest.mark.parametrize("origin", [Screen.DONE, Screen.PICK_BLOCKED, Screen.WHAT])
def test_accessible_unsaved_report_close_escape_and_stale_actions(ui, origin):
    from beamo_wipe import copy as C
    from types import SimpleNamespace

    w = make_demo_wizard()
    w.screen, w.report_wanted = origin, True
    app = ui(w)
    app._close()
    drain()
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not app.closed
    assert C.SHUTDOWN_TITLE in text(app) and C.SHUTDOWN_LOSS in text(app)
    assert list(app.actions) == [C.SHUTDOWN_KEEP, C.SHUTDOWN_DISCARD]
    for button in app.actions.values():
        assert button.get_allocation().height > 0 and button.get_can_focus()
    stale = app.actions[C.SHUTDOWN_DISCARD]
    app._key_press(app.window, SimpleNamespace(keyval=Gdk.KEY_Escape))
    app._key_release(app.window, SimpleNamespace(keyval=Gdk.KEY_Escape))
    assert w.screen == origin and not w.wants_shutdown
    app._close()
    stale.clicked()
    assert not w.wants_shutdown
    app.actions[C.SHUTDOWN_DISCARD].clicked()
    assert w.wants_shutdown and app.closed


def test_accessible_finished_announces_receipt_location(ui, tmp_path):
    from test_usb_report_workflow import _done_wizard, _success_receipt

    w = _done_wizard(
        lambda **kw: _success_receipt(
            **kw,
            log_status="complete",
            destination_label="SanDisk Ultra, 16 GB",
        ),
        tmp_path,
    )
    w.screen = Screen.REPORT_HELP
    w.set_report_share_redacted(True)
    w.screen = Screen.DONE
    w.save_report_to_usb()
    app = ui(w)
    shown = text(app)
    assert "SanDisk Ultra, 16 GB" in shown
    assert "Folder: BEAMO-WIPE-REPORTS/" in shown
    assert "RESULT.txt is the original report." in shown
    assert "SHARE.txt is a sharing copy" in shown
    assert "Engine log: complete." in shown


@pytest.mark.parametrize("wanted,saved", [(False, False), (True, True), (True, False)])
def test_accessible_finished_shutdown_receipt_state(ui, tmp_path, wanted, saved):
    from test_usb_report_workflow import _done_wizard, _success_receipt

    w = _done_wizard(_success_receipt, tmp_path)
    w.report_wanted = wanted
    if saved:
        w.save_report_to_usb()
    app = ui(w)
    app.actions["Shut down"].clicked()
    assert app.closed is (not wanted or saved)
    assert w.wants_shutdown is app.closed


def test_recovered_result_is_announced_without_confirmation(ui):
    wizard, _, _ = case_evidence(CASES[0])
    wizard._recovered = True
    wizard.owner_ok = False
    wizard.confirm_input = ""
    wizard._wipe_request = None
    app = ui(wizard)
    assert "No erase was restarted or resumed" in text(app)
    assert "power loss" in text(app)
    assert "Check disks again (F5)" not in app.actions


def test_accessible_evidence_failure_retry(ui, tmp_path, monkeypatch):
    from beamo_wipe import evidence
    from test_evidence_retry import start, complete, fail
    writer = evidence.write_evidence_atomic
    monkeypatch.setattr(evidence, 'write_evidence_atomic', fail)
    w, clock = start(tmp_path, monkeypatch)
    app = ui(w)
    assert w.evidence_warning in text(app)
    assert app.actions['Cancel erase'].get_sensitive()
    assert 'Retry evidence save' not in app.actions
    complete(w, clock)
    app.render()
    assert w.evidence_warning in text(app)
    retry = app.actions['Retry evidence save']
    assert retry.get_sensitive() and retry.get_can_focus()
    assert retry.get_accessible().get_name() == 'Retry evidence save'
    assert not app.actions['Save report to USB'].get_sensitive()
    monkeypatch.setattr(evidence, 'write_evidence_atomic', writer)
    retry.clicked()
    deadline = time.monotonic() + 3
    while w.report_view.saving_evidence and time.monotonic() < deadline:
        drain()
        time.sleep(.01)
    app.tick()
    assert not w.evidence_error and w.can_save_report
    assert 'Retry evidence save' not in app.actions


def wait_transition(app):
    import time
    deadline = time.monotonic() + 3
    while app.w.screen in {Screen.CHECKING, Screen.STOPPING} and time.monotonic() < deadline:
        drain()
        time.sleep(0.005)
    assert app.w.screen not in {Screen.CHECKING, Screen.STOPPING}
    app.tick()


@pytest.mark.parametrize("phase", ["checking", "stopping"])
def test_busy_accessible_view_remains_responsive(ui, monkeypatch, tmp_path, phase):
    from test_busy_transitions import Barrier
    w = make_demo_wizard()
    w.preview = False
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(w, "_write_evidence", lambda **kw: None)
    w.runner._clock = lambda: 0
    w.skip_splash()
    w.accept_what()
    w.set_owner(True)
    w.continue_owner()
    w.select_disk(w.selectable[0].path)
    w.continue_pick()
    w.set_confirm_input(w.confirm.token)
    w.continue_confirm()
    w.continue_method()
    w._erase_until = 0
    barrier = Barrier()
    if phase == "stopping":
        w.confirm_erase()
    app = ui(w)
    if phase == "checking":
        original = w.runner.start
        def slow(request):
            barrier.wait()
            original(request)
        monkeypatch.setattr(w.runner, "start", slow)
        stale = app.actions["Erase now"]
        stale.clicked()
    else:
        original = w.runner.cancel
        def slow():
            barrier.wait()
            original()
        monkeypatch.setattr(w.runner, "cancel", slow)
        stale = app.actions["Cancel erase"]
        stale.clicked()
    try:
        assert barrier.entered.wait(2)
        beats = []
        GLib.idle_add(lambda: beats.append(True) or False)
        drain()
        app.tick()
        assert beats
        title = "Checking disk" if phase == "checking" else "Stopping erase"
        assert title in text(app)
        assert title in [v.get_accessible().get_name() for v in widgets(app.window)]
        assert not app.actions
        stale.emit("clicked")
        app._close()
        assert not app.closed and not w.wants_shutdown
    finally:
        barrier.join(w)
    wait_transition(app)


def test_accessible_progress_has_shared_text_without_duplicate_announcements(ui):
    from unittest.mock import PropertyMock, patch
    from beamo_wipe.progress import ProgressView
    from beamo_wipe.wizard import Wizard

    wizard = make_demo_wizard()
    wizard.screen = Screen.WORKING
    view = ProgressView("Verifying", 82, 90061, 7200)
    with patch.object(Wizard, "progress_view", new_callable=PropertyMock, return_value=view):
        app = ui(wizard)
        label = app.progress_label
        changes = []
        label.connect("notify::label", lambda *_: changes.append(True))
        app.update_status()
        baseline = len(changes)
        for _ in range(20):
            app.update_status()
        assert len(changes) == baseline
        assert label.get_text() == view.status_text
        assert label.get_accessible().get_name() == view.status_text
        assert "Estimated time remaining: about 2 hours" in text(app)
