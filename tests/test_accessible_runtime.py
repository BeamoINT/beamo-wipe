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
from beamo_wipe import copy as C  # noqa: E402
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
    from beamo_wipe import recovery as R

    wizard, _, _ = case_evidence(case)
    app = ui(wizard)
    expected = VIEWS[case[0]]
    shown = text(app)
    names = [w.get_accessible().get_name() for w in widgets(app.window)]
    if expected.success:
        assert expected.announcement in shown
        assert expected.announcement in names
    else:
        assert expected.message in shown
        assert expected.next_step in shown
        assert expected.message in names
        assert R.RECOVERY_HAPPENED in shown
        assert R.RECOVERY_MEANING in shown
        assert R.RECOVERY_NEXT in shown
    assert wizard.selected.serial in shown
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
    wizard.skip_intro()
    app.render()
    app.actions[C.BTN_UNDERSTAND].clicked()
    check = next(w for w in widgets(app.window) if isinstance(w, Gtk.CheckButton))
    assert not app.actions[C.BTN_CHOOSE_DISK].get_sensitive()
    check.set_active(True)
    app.actions[C.BTN_CHOOSE_DISK].clicked()
    assert wizard.selected is None
    select = next(v for k, v in app.actions.items() if k.startswith("Select "))
    select.clicked()
    entry = next(w for w in widgets(app.window) if isinstance(w, Gtk.Entry))
    entry.set_text("WRONG")
    assert not app.actions[C.BTN_CHOOSE_METHOD].get_sensitive()
    entry.set_text(wizard.confirm.token)
    app.actions[C.BTN_CHOOSE_METHOD].clicked()
    app.actions[C.BTN_REVIEW_ERASE].clicked()
    assert wizard.screen == Screen.LAST_CHANCE
    assert C.LAST_LEAD in text(app)
    assert not app.actions["Erase now"].get_sensitive()
    stale_erase = app.actions["Erase now"]
    app.actions["Check disks again (F5)"].clicked()
    assert wizard.screen == Screen.REFRESH_CONFIRM
    assert wizard.selected is not None and wizard.owner_ok
    assert C.REFRESH_LEAD in text(app)
    app.actions[C.BTN_REFRESH].clicked()
    assert wizard.screen == Screen.WHAT
    assert wizard.selected is None and not wizard.owner_ok and not wizard.confirm_input
    # A queued action from the previous screen never starts a wipe.
    stale_erase.emit("clicked")
    assert not wizard.runner.started
    app.actions[C.BTN_UNDERSTAND].clicked()
    next(w for w in widgets(app.window) if isinstance(w, Gtk.CheckButton)).set_active(
        True
    )
    app.actions[C.BTN_CHOOSE_DISK].clicked()
    next(v for k, v in app.actions.items() if k.startswith("Select ")).clicked()
    next(w for w in widgets(app.window) if isinstance(w, Gtk.Entry)).set_text(
        wizard.confirm.token
    )
    app.actions[C.BTN_CHOOSE_METHOD].clicked()
    wizard.set_method(MethodId.QUICK_ZERO)
    app.actions[C.BTN_REVIEW_ERASE].clicked()
    wizard._erase_until = 0
    app.update_status()
    assert app.actions["Erase now"].get_sensitive()
    app.actions["Erase now"].clicked()
    wait_transition(app)
    assert wizard.screen == Screen.WORKING and wizard.runner.started
    assert "Check disks again (F5)" not in app.actions
    app.actions["Stop erase"].clicked()
    app.actions["Yes, stop erasing"].clicked()
    wait_transition(app)
    assert wizard.screen == Screen.DONE


def test_excluded_devices_are_read_only_and_no_selection(ui):
    wizard = make_demo_wizard(scenario="empty")
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    app = ui(wizard)
    assert wizard.screen == Screen.PICK_EMPTY
    readers = [w for w in widgets(app.window) if isinstance(w, Gtk.TextView)]
    protected = [w for w in readers if w.get_accessible().get_name() == wizard.protected_boot_text]
    assert len(protected) == 1
    assert "protected, cannot be erased" in protected[0].get_accessible().get_name()
    assert wizard.discovery.boot.display_name in protected[0].get_accessible().get_name()
    assert wizard.discovery.boot.path not in protected[0].get_accessible().get_name()
    assert "Other detected devices" in text(app)
    assert readers and all(not w.get_editable() for w in readers)
    assert all(w.get_allocation().height >= 180 for w in readers)
    assert not any(name.startswith("Select ") for name in app.actions)


def test_last_chance_enter_without_erase_focus_never_erases(ui):
    from types import SimpleNamespace

    wizard = make_demo_wizard()
    wizard.skip_intro()
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


def test_escape_requests_stop_confirmation(ui):
    from types import SimpleNamespace

    wizard = make_demo_wizard()
    wizard.skip_intro()
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
    assert wizard.screen == Screen.WORKING and wizard.stop_confirmation is not None
    assert not wizard.runner.cancelled
    from beamo_wipe import copy as C
    assert C.STOP_KEEP in app.actions and C.STOP_CONFIRM in app.actions
    app.actions[C.STOP_KEEP].clicked()
    assert wizard.stop_confirmation is None and not wizard.runner.cancelled
    app.actions[C.STOP_ASK].clicked()
    app.actions[C.STOP_CONFIRM].clicked()
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
    if not names:
        pytest.skip("AT-SPI desktop is empty (registry cannot open this display)")
    assert wizard.result_view.announcement in names
    assert "Shut down" in names
    assert app.w.result_view.code == "unverified"


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_result_focus_does_not_create_a_text_selection(ui, case):
    wizard, _, _ = case_evidence(case)
    app = ui(wizard)
    heading = app.window.get_focus()
    assert isinstance(heading, Gtk.Label)
    expected = (
        wizard.result_view.announcement
        if wizard.result_view.success
        else wizard.result_view.message
    )
    assert heading.get_text() == expected
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
    wizard.skip_intro()
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
    assert wizard.prepare_text() in text(app)
    assert (C.TITLE_CONFIRM if screen == Screen.CONFIRM else C.TITLE_LAST) in text(app)
    arrival = app.window.get_focus()
    warning = wizard.warning_text() if screen == Screen.CONFIRM else wizard.erase_label()
    assert arrival.get_text() == f"{C.SEVERITY_WARNING}: {warning}"
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


def test_orca_announces_every_result(tmp_path, request):
    """Real Orca reads GTK focus events via AT-SPI; no host audio/devices used."""
    import shutil

    if os.environ.get("BEAMO_TEST_ORCA_CHILD") != "1":
        # A fresh application and private bus avoid previously destroyed test
        # windows in the AT-SPI registry. No application behavior is mocked.
        # Do not construct the ui fixture in this parent process. Nested
        # xvfb-run under Cloud Build's outer xvfb-run fails hosted python-tests.
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
            # Descriptive next-action labels add speech on every screen.
            # Bookworm Orca 43 still announces, but the child can exceed 300s.
            timeout=480,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "warning" not in result.stdout.lower(), result.stdout
        return
    ui = request.getfixturevalue("ui")
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

    app_box = []

    def logged_speech(phrase, since):
        content = logfile.read_text(errors="replace") if logfile.exists() else ""
        lines = content[since:].splitlines()
        for index, line in enumerate(lines):
            if "SPEECH OUTPUT:" not in line:
                continue
            chunk = line
            if index + 1 < len(lines):
                chunk = f"{line} {lines[index + 1]}"
            if phrase in chunk:
                return content, True
        # Bookworm Orca 43 can queue heading focus with the full announcement
        # while FOCUS MANAGER reports Locus of focus is None and never emits
        # SPEECH OUTPUT. Extra nudges then blow the 300s parent timeout.
        # Accessible-name-only still fails this wait; a focus: heading event
        # carrying the phrase is the same arrival Orca would speak.
        for line in lines:
            if "focus: for [heading:" in line and phrase in line:
                return content, True
        return content, False

    def nudge_focus(phrase):
        if not app_box:
            return
        app = app_box[0]
        drain()
        # Rebuilds can Notify:True-focus the window frame without generating
        # speech. Blur to a control, then refocus the arrival heading so
        # Orca emits a fresh SPEECH OUTPUT line. Accessible-name-only
        # still fails this wait.
        arrival = getattr(app, "arrival", None)
        other = None
        match = None
        if arrival is not None:
            accessible = arrival.get_accessible()
            name = accessible.get_name() if accessible is not None else ""
            label = arrival.get_text() if isinstance(arrival, Gtk.Label) else ""
            if phrase in (name or "") or phrase in (label or ""):
                match = arrival
        for widget in widgets(app.window):
            if widget is arrival or isinstance(widget, Gtk.Window):
                continue
            accessible = widget.get_accessible()
            name = accessible.get_name() if accessible is not None else ""
            label = widget.get_text() if isinstance(widget, Gtk.Label) else ""
            if match is None and (phrase in (name or "") or phrase in (label or "")):
                match = widget
            elif other is None and widget.get_can_focus() and isinstance(widget, Gtk.Button):
                other = widget
        if other is not None:
            other.grab_focus()
            drain()
        target = match or arrival or app.window.get_focus()
        if target is not None:
            target.grab_focus()
            drain()

    def wait_for(phrase, *, since=0, timeout=40):
        # Bookworm Orca can spend >15s draining defunct children-changed
        # events after a dense screen is destroyed before it speaks again.
        deadline = time.monotonic() + timeout
        nudges = 0
        next_nudge = time.monotonic()
        content = ""
        while time.monotonic() < deadline:
            drain()
            content, found = logged_speech(phrase, since)
            if found:
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
            if app_box and nudges < 2 and time.monotonic() >= next_nudge:
                nudge_focus(phrase)
                nudges += 1
                next_nudge = time.monotonic() + 2
            assert reader.poll() is None, content[-3000:]
            time.sleep(0.02)
        pytest.fail(f"Orca did not announce {phrase!r}: {content[-3000:]}")

    try:
        wait_for("Screen reader on")
        first, _, _ = case_evidence(CASES[0])
        checkpoint = len(logfile.read_text(errors="replace")) if logfile.exists() else 0
        app = ui(first)
        app_box.append(app)
        wait_for(first.result_view.message, since=checkpoint)
        for case in CASES[1:]:
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
        wizard.skip_intro()
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
        # Freeze the countdown before the first last-chance paint. A live
        # countdown mutates a GtkLabel every second; Orca queues those
        # text-changed events and never speaks TITLE_PICK after the widgets
        # are destroyed.
        wizard._erase_until = 0.0
        checkpoint = len(logfile.read_text(errors="replace"))
        app.render()
        wait_for(wizard.erase_label(), since=checkpoint)
        assert not wizard.runner.started
        from beamo_wipe import copy as C
        wizard.back(); wizard.back(); wizard.back()
        checkpoint = len(logfile.read_text(errors="replace"))
        app.render()
        wait_for(C.TITLE_PICK, since=checkpoint)
        checkpoint = len(logfile.read_text(errors="replace"))
        app.actions[C.DISK_HELP_BUTTON].grab_focus()
        wait_for(C.DISK_HELP_BUTTON, since=checkpoint)
        checkpoint = len(logfile.read_text(errors="replace"))
        app.actions[C.DISK_HELP_BUTTON].clicked()
        wait_for(C.DISK_HELP_TITLE, since=checkpoint)
        checkpoint = len(logfile.read_text(errors="replace"))
        help_reader = next(item for item in widgets(app.window) if isinstance(item, Gtk.TextView))
        help_reader.grab_focus()
        wait_for("You do not need to choose now", since=checkpoint)
        assert wizard.selected is None and not wizard.runner.started
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


def test_accessible_done_fail_shows_focusable_support(ui):
    from beamo_wipe import copy as C

    w, _, _ = case_evidence(next(c for c in CASES if c[0] == "engine_failed"))
    w.preview = False
    w.screen = Screen.DONE
    app = ui(w)
    app.render()
    drain()
    labels = [
        label
        for label in widgets(app.window)
        if isinstance(label, Gtk.Label) and label.get_text() == C.support_text()
    ]
    assert len(labels) == 1
    assert labels[0].get_can_focus()


def test_accessible_blocked_leads_with_specific_heading(ui):
    from beamo_wipe import copy as C

    w = make_demo_wizard()
    w.preview = False
    w.error = C.IDENTIFY_ERROR
    w.screen = Screen.PICK_BLOCKED
    app = ui(w)
    app.render()
    drain()
    shown = text(app)
    assert C.BLOCKED_HEADING_IDENTIFY in shown
    assert shown.index(C.BLOCKED_HEADING_IDENTIFY) < shown.index(C.SEVERITY_ERROR)


@pytest.mark.parametrize("wanted", [True, False])
def test_accessible_report_help_intent_refresh_and_scroll(ui, wanted):
    from beamo_wipe import copy as C

    w = make_demo_wizard()
    w.skip_intro()
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
    assert w.screen == Screen.REFRESH_CONFIRM
    app.actions[C.BTN_REFRESH].clicked()
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
    assert "SHARE.json is a privacy-reduced sharing copy" in shown
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
    assert app.actions['Stop erase'].get_sensitive()
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
    w.skip_intro()
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
        app.actions["Stop erase"].clicked()
        stale = app.actions["Yes, stop erasing"]
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


def test_accessible_stale_progress_announces_meaning_and_next_steps_once(ui):
    from unittest.mock import PropertyMock, patch
    from beamo_wipe.progress import STALE_MEANING, STALE_NEXT, ProgressView
    from beamo_wipe.wizard import Wizard

    wizard = make_demo_wizard()
    wizard.screen = Screen.WORKING
    view = ProgressView("Writing", 42, 120, None, stale_for=65, percent_is_old=True)
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
        assert STALE_MEANING in text(app)
        assert STALE_NEXT in text(app)


def test_accessible_render_emits_only_fixed_screen_marker(ui, monkeypatch):
    from beamo_wipe.ui import accessible_wizard as module

    markers = []
    monkeypatch.setattr(module, "emit_serial_marker", markers.append)
    wizard = make_demo_wizard()
    app = ui(wizard)
    assert markers[-1] == f"BEAMO_WIPE_ACCESSIBLE_SCREEN_{wizard.screen.name}"
    wizard.screen = Screen.OWNER
    app.render()
    assert markers[-1] == "BEAMO_WIPE_ACCESSIBLE_SCREEN_OWNER"
    assert all(marker.startswith("BEAMO_WIPE_ACCESSIBLE_SCREEN_") for marker in markers)


def test_picker_select_buttons_announce_connection(ui):
    from beamo_wipe.identity import CONNECTION_LABEL

    wizard = make_demo_wizard()
    wizard.screen = Screen.PICK
    app = ui(wizard)
    names = list(app.actions)
    for disk in wizard.selectable:
        view = wizard.disk_view(disk)
        expected = f"Select {view.announcement}"
        assert expected in names
        assert f"{CONNECTION_LABEL}: {view.connection}" in expected
    assert wizard.selected is None and not wizard.runner.started


def test_picker_select_buttons_say_serial_number(ui):
    from beamo_wipe.identity import SERIAL_LABEL

    wizard = make_demo_wizard()
    wizard.screen = Screen.PICK
    app = ui(wizard)
    for disk in wizard.selectable:
        view = wizard.disk_view(disk)
        name = f"Select {view.announcement}"
        assert name in app.actions
        assert f"{SERIAL_LABEL}: {disk.serial}" in name
    assert wizard.selected is None and not wizard.runner.started


@pytest.mark.parametrize(
    "scenario,screen,expected",
    [
        (
            "happy",
            Screen.PICK,
            "3 disks available to erase. Beamo USB protected. 1 other device not available.",
        ),
        (
            "empty",
            Screen.PICK_EMPTY,
            "No disks available to erase. Beamo USB protected. 1 other device not available.",
        ),
        (
            "blocked",
            Screen.PICK_BLOCKED,
            "Disk list could not be confirmed. No disk is available to erase.",
        ),
    ],
)
def test_inventory_count_is_announced_on_pick_screens(ui, scenario, screen, expected):
    wizard = make_demo_wizard(scenario=scenario)
    wizard.screen = screen
    app = ui(wizard)
    shown = text(app)
    names = [w.get_accessible().get_name() or "" for w in widgets(app.window)]
    assert expected in shown
    assert expected in names
    focusable = [
        w for w in widgets(app.window)
        if isinstance(w, Gtk.Label) and w.get_text() == expected and w.get_can_focus()
    ]
    assert len(focusable) == 1
    assert focusable[0].get_accessible().get_name() == expected
    assert wizard.selected is None and not wizard.runner.started


def test_picker_announces_tb_capacity_and_type_unknown(ui):
    from beamo_wipe.copy import KIND_UNKNOWN
    from beamo_wipe.models import DiskKind

    wizard = make_demo_wizard()
    wizard.screen = Screen.PICK
    unknown = replace(wizard.selectable[0], kind=DiskKind.UNKNOWN)
    wizard.discovery = replace(
        wizard.discovery,
        disks=tuple(unknown if d.path == unknown.path else d for d in wizard.discovery.disks),
        selectable=tuple(unknown if d.path == unknown.path else d for d in wizard.discovery.selectable),
    )
    app = ui(wizard)
    names = list(app.actions)
    assert any("1 TB (1000 GB)" in name for name in names)
    assert any(KIND_UNKNOWN in name for name in names)
    assert wizard.selected is None and not wizard.runner.started


def test_picker_protected_identity_is_reader_not_select_action(ui):
    wizard = make_demo_wizard()
    wizard.screen = Screen.PICK
    app = ui(wizard)
    readers = [w for w in widgets(app.window) if isinstance(w, Gtk.TextView)]
    protected = [w for w in readers if w.get_accessible().get_name() == wizard.protected_boot_text]
    assert len(protected) == 1 and not protected[0].get_editable()
    assert wizard.discovery.boot.serial in protected[0].get_accessible().get_name()
    assert not any(name.startswith("Select ") and wizard.discovery.boot.serial in name for name in app.actions)
    assert wizard.selected is None and not wizard.runner.started


def test_serial_comparison_is_in_accessible_disk_name(ui):
    from test_serial_comparison import comparison_wizard
    wizard = comparison_wizard()
    wizard.screen = Screen.PICK
    app = ui(wizard)
    names = [w.get_accessible().get_name() or "" for w in widgets(app.window)]
    for disk in wizard.selectable:
        view = wizard.disk_view(disk)
        assert any(view.id_value in name and view.comparison_note in name for name in names)

@pytest.mark.parametrize('size', [(800, 600), (1280, 820)])
def test_unsure_disk_accessible_reader_and_return(ui, size):
    from beamo_wipe import copy as C
    w = make_demo_wizard()
    w.skip_intro()
    w.accept_what()
    w.set_owner(True)
    w.continue_owner()
    w.select_disk(w.selectable[0].path)
    app = ui(w, size=size)
    action = app.actions[C.DISK_HELP_BUTTON]
    assert action.get_accessible().get_name() == C.DISK_HELP_BUTTON
    action.grab_focus()
    action.activate()
    drain()
    # GtkButton activation animates before emitting clicked.
    deadline = time.monotonic() + 1
    while w.screen == Screen.PICK and time.monotonic() < deadline:
        drain()
        time.sleep(.01)
    assert w.screen == Screen.DISK_HELP and w.selected is None
    reader = next(x for x in widgets(app.window) if isinstance(x, Gtk.TextView))
    assert reader.get_accessible().get_name() == C.DISK_HELP_TEXT
    assert reader.get_can_focus() and not reader.get_editable()
    reader.grab_focus()
    drain()
    assert reader.has_focus()
    app.actions[C.BTN_BACK].clicked()
    drain()
    assert w.screen == Screen.PICK and w.selected is None
    app.actions[C.DISK_HELP_BUTTON].clicked()
    drain()
    w.report_wanted = True
    app.actions[C.DISK_HELP_STOP].clicked()
    drain()
    assert w.screen == Screen.SHUTDOWN_CONFIRM and not w.wants_shutdown
    w.back()
    assert w.screen == Screen.DISK_HELP and w.selected is None

def test_review_countdown_announces_only_changed_text(ui):
    from beamo_wipe import copy as C
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    app = ui(wizard)
    changes = []
    app.countdown_label.connect("notify::label", lambda *args: changes.append(1))
    app.update_status()
    changes.clear()
    app.update_status()
    app.update_status()
    assert changes == []
    focus = app.window.get_focus()
    wizard._erase_until = 0
    app.update_status()
    assert changes == [1]
    assert app.countdown_label.get_text() == C.COUNTDOWN_READY
    app.update_status()
    assert changes == [1]
    assert app.window.get_focus() == focus
    assert wizard.screen == Screen.LAST_CHANCE
    assert not wizard.runner.started

@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
@pytest.mark.parametrize("status", ["idle", "saving", "saved", "error"])
def test_separate_erase_and_report_headings(ui, case, status):
    from gi.repository import Atk
    from beamo_wipe import copy as C
    wizard, _, _ = case_evidence(case)
    wizard.report_status = status
    app = ui(wizard)
    headings = {
        widget.get_accessible().get_name()
        for widget in widgets(app.window)
        if widget.get_accessible().get_role() == Atk.Role.HEADING
    }
    # #95: the specific outcome is the erase heading; the generic label is gone.
    # #107: failures then add What happened / meaning / next as headings.
    assert wizard.result_view == VIEWS[case[0]]
    if wizard.result_view.success:
        assert wizard.result_view.announcement in headings
    else:
        from beamo_wipe import recovery as R

        assert wizard.result_view.message in headings
        assert R.RECOVERY_HAPPENED in headings
        assert R.RECOVERY_MEANING in headings
        assert R.RECOVERY_NEXT in headings
        assert wizard.result_view.announcement not in headings
    assert C.REPORT_STATUS_TITLE in headings
    assert C.REPORT_STATUS_TITLE in headings
    assert "Erase status" not in headings
    assert wizard.report_view.headline in text(app)

def test_accessible_erase_another_guard(ui):
    from beamo_wipe import copy as C
    w, _, _ = case_evidence(CASES[0])
    app = ui(w)
    app.actions[C.BTN_ERASE_ANOTHER].clicked()
    drain()
    assert w.screen == Screen.SHUTDOWN_CONFIRM
    assert C.ANOTHER_LOSS in text(app)
    stale = app.actions[C.ANOTHER_DISCARD]
    app.actions[C.SHUTDOWN_KEEP].clicked()
    drain()
    assert w.screen == Screen.DONE
    app.actions[C.BTN_ERASE_ANOTHER].clicked()
    stale.clicked()
    assert not w.wants_new_session
    app.actions[C.ANOTHER_DISCARD].clicked()
    assert w.wants_new_session and app.closed


def _canned_sound(monkeypatch, calls, *, available=True, orca=True):
    from beamo_wipe import copy as C
    from beamo_wipe import sound

    outputs = (
        sound.SoundOutput("speak-id", "Speakers", "speak-id", True),
        sound.SoundOutput("phones-id", "Headphones", "phones-id", False),
    )
    state = sound.SoundState(
        available=available,
        message="" if available else C.SOUND_NO_OUTPUT,
        outputs=outputs if available else (),
        volume_percent=40 if available else None,
        muted=False if available else None,
    )
    monkeypatch.setattr(sound, "list_outputs", lambda: state)
    monkeypatch.setattr(sound, "orca_running", lambda: orca)
    monkeypatch.setattr(
        sound, "set_output",
        lambda name: calls.append(("set", name)) or sound.SoundResult(True, "ok"),
    )
    monkeypatch.setattr(
        sound, "nudge_volume",
        lambda name, delta: calls.append(("vol", name, delta))
        or sound.SoundResult(True, "ok"),
    )
    monkeypatch.setattr(
        sound, "set_muted",
        lambda name, muted: calls.append(("mute", name, muted))
        or sound.SoundResult(True, "ok"),
    )
    monkeypatch.setattr(
        sound, "play_speech_test",
        lambda: calls.append(("play",)) or sound.SoundResult(True, "played"),
    )
    return state


def _sound_dialog():
    from beamo_wipe.ui.accessible_wizard import Gtk

    return [
        w for w in Gtk.Window.list_toplevels()
        if isinstance(w, Gtk.Dialog) and w.get_mapped()
    ]


def _dialog_button(dialog, label):
    from beamo_wipe.ui.accessible_wizard import Gtk

    found = [
        w for w in widgets(dialog)
        if isinstance(w, Gtk.Button) and w.get_label() == label
    ]
    assert len(found) == 1, label
    return found[0]


def test_sound_check_dialog_plays_test_and_switches_output(ui, monkeypatch):
    """Backlog #86: outputs, test, and persisted choice. Needs display."""
    from beamo_wipe import copy as C
    from beamo_wipe.ui.accessible_wizard import Gtk

    calls = []
    _canned_sound(monkeypatch, calls)
    app = ui()
    app.actions[C.SOUND_CHECK_BUTTON].clicked()
    drain()
    dialogs = _sound_dialog()
    assert len(dialogs) == 1
    dialog = dialogs[0]
    names = {
        w.get_text() for w in widgets(dialog) if isinstance(w, Gtk.Label)
    }
    assert any("Speakers" in name for name in names)
    assert any("Headphones" in name for name in names)
    _dialog_button(dialog, C.SOUND_PLAY_TEST).clicked()
    drain()
    assert ("play",) in calls
    radios = [w for w in widgets(dialog) if isinstance(w, Gtk.RadioButton)]
    assert len(radios) == 2
    radios[1].set_active(True)
    drain()
    assert ("set", "phones-id") in calls
    assert app.w.sound_output == "phones-id"
    _dialog_button(dialog, C.SOUND_LOUDER).clicked()
    _dialog_button(dialog, C.SOUND_MUTE).clicked()
    drain()
    assert ("vol", "phones-id", 10) in calls
    assert ("mute", "phones-id", True) in calls
    dialog.destroy()
    drain()
    assert _sound_dialog() == []


def test_sound_check_dialog_reports_no_audio_and_orca_failure(ui, monkeypatch):
    """Backlog #86: silence states stay usable with recovery text."""
    from beamo_wipe import copy as C
    from beamo_wipe.ui.accessible_wizard import Gtk

    calls = []
    _canned_sound(monkeypatch, calls, available=False, orca=False)
    app = ui()
    app.actions[C.SOUND_CHECK_BUTTON].clicked()
    drain()
    dialogs = _sound_dialog()
    assert len(dialogs) == 1
    dialog = dialogs[0]
    shown = "\n".join(
        w.get_text() for w in widgets(dialog) if isinstance(w, Gtk.Label)
    )
    assert C.SOUND_NO_OUTPUT in shown
    assert C.SOUND_ORCA_MISSING in shown
    assert C.SOUND_RECOVERY in shown
    assert not _dialog_button(dialog, C.SOUND_PLAY_TEST).get_sensitive()
    dialog.emit("close")
    drain()
    assert _sound_dialog() == []


def test_sound_check_dialog_toggles_and_hears_outcome_sounds(ui, monkeypatch):
    """Backlog #93: outcome-sound toggle + hear. Needs display."""
    from beamo_wipe import copy as C
    from beamo_wipe import sound

    calls = []
    _canned_sound(monkeypatch, calls)
    monkeypatch.setattr(
        sound,
        "play_test",
        lambda kind: calls.append(("hear", kind))
        or sound.SoundResult(True, f"played {kind}"),
    )
    app = ui()
    app.actions[C.SOUND_CHECK_BUTTON].clicked()
    drain()
    dialog = _sound_dialog()[0]
    _dialog_button(dialog, C.SOUND_TOGGLE_OFF).clicked()
    drain()
    assert app.w.sounds_enabled is True
    assert app.w.sound_message == C.SOUND_TOGGLE_ON
    _dialog_button(dialog, C.SOUND_TOGGLE_ON)
    _dialog_button(dialog, C.SOUND_HEAR).clicked()
    drain()
    assert ("hear", "finished") in calls
    assert ("hear", "attention") in calls
    dialog.destroy()
    drain()
    assert _sound_dialog() == []


def test_accessible_done_auto_plays_once_without_changing_announcement(ui, monkeypatch):
    """Backlog #93: auto-play + screen-reader coexistence. Needs display."""
    from beamo_wipe import sound as sound_module
    from beamo_wipe.models import WipeResult

    calls = []
    monkeypatch.setattr(
        sound_module,
        "play_outcome",
        lambda kind: calls.append(kind)
        or sound_module.SoundResult(True, ""),
    )
    wizard = make_demo_wizard()
    wizard.preview = False
    wizard.screen = Screen.DONE
    wizard.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    app = ui(wizard)
    off_text = text(app)
    wizard.set_sounds_enabled(True)
    app.render()
    drain()
    app.render()
    drain()
    assert calls == [sound_module.KIND_ATTENTION]
    assert text(app) == off_text


def test_done_announcement_is_first_heading(ui):
    """Backlog #95: screen-reader order. Needs display."""
    from gi.repository import Atk

    from beamo_wipe import copy as C
    from beamo_wipe.models import WipeResult

    wizard = make_demo_wizard()
    wizard.preview = False
    wizard.screen = Screen.DONE
    wizard.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    app = ui(wizard)
    ordered = [
        widget.get_accessible().get_name()
        for widget in widgets(app.window)
        if widget.get_accessible().get_role() == Atk.Role.HEADING
    ]
    view = wizard.result_view
    expected = view.announcement if view.success else view.message
    assert ordered[0] == expected
    assert "Erase status" not in ordered
    assert C.REPORT_STATUS_TITLE in ordered
    heading = next(
        widget
        for widget in widgets(app.window)
        if widget.get_accessible().get_role() == Atk.Role.HEADING
    )
    assert heading.get_accessible().get_name() == expected
    assert heading.get_accessible().get_description() == C.journey_announcement(Screen.DONE)
    assert not heading.get_accessible().get_name().startswith("Result. ")


@pytest.mark.parametrize(
    "code,shown",
    [("verified", True), ("engine_failed", True), ("cancelled", True), ("open_failed", False)],
)
def test_done_post_erase_boot_note_announced(ui, code, shown):
    """Backlog #97: post-erase note. Needs display."""
    from beamo_wipe import copy as C

    case = next(c for c in CASES if c[0] == code)
    wizard, _, _ = case_evidence(case)
    app = ui(wizard)
    assert (C.POST_ERASE_BOOT in text(app)) == shown


@pytest.mark.parametrize("code", ["verified", "engine_failed", "cancelled", "interrupted"])
def test_shutdown_confirm_media_steps_announced(ui, code):
    """Backlog #98: ordered removal steps. Needs display."""
    from beamo_wipe import copy as C

    case = next(c for c in CASES if c[0] == code)
    wizard, _, _ = case_evidence(case)
    wizard.report_wanted = True
    wizard.shutdown()
    assert wizard.screen == Screen.SHUTDOWN_CONFIRM
    app = ui(wizard)
    assert C.SHUTDOWN_LOSS in text(app)
    assert C.MEDIA_STEPS_TITLE in text(app)
    assert wizard.exit_media_steps in text(app)
    names = [w.get_accessible().get_name() for w in widgets(app.window)]
    assert C.MEDIA_STEPS_TITLE in names


def test_what_report_media_notice_announced(ui):
    """Backlog #99: pre-erase media notice. Needs display."""
    from beamo_wipe import copy as C

    wizard = make_demo_wizard()
    wizard.skip_intro()
    assert wizard.screen == Screen.WHAT
    app = ui(wizard)
    assert C.REPORT_MEDIA_WHAT in text(app)
    names = [w.get_accessible().get_name() for w in widgets(app.window)]
    assert C.REPORT_MEDIA_WHAT in names


@pytest.mark.parametrize("wanted", [True, False])
def test_pick_report_media_notice_follows_preference(ui, wanted):
    """Backlog #99: conditional pick notice. Needs display."""
    from beamo_wipe import copy as C

    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    assert wizard.screen == Screen.PICK
    wizard.report_wanted = wanted
    app = ui(wizard)
    assert (C.REPORT_MEDIA_WANTED in text(app)) == wanted


@pytest.mark.parametrize("status", ["idle", "saving", "saved", "error"])
def test_done_export_stages_announced_per_state(ui, tmp_path, status):
    """Backlog #100: staged export guidance. Needs display."""
    from beamo_wipe import copy as C
    from test_usb_report_workflow import _done_wizard, _success_receipt

    wizard = _done_wizard(_success_receipt, tmp_path)
    if status == "saved":
        wizard.save_report_to_usb()
    elif status == "saving":
        from beamo_wipe.wizard import REPORT_SAVING

        wizard.report_status = "saving"
        wizard.report_message = REPORT_SAVING
    elif status == "error":
        wizard.report_status = "error"
        wizard.report_message = "Report USB was removed."
    app = ui(wizard)
    body = text(app)
    for index, stage in enumerate(C.EXPORT_STAGES, 1):
        assert (f"{index}. {stage}" in body) == (status != "error")
    if status == "error":
        assert "Save report to USB again" in body


def test_diagnostic_rejection_announces_next_step(ui):
    """Backlog #101: actionable rejection. Needs display."""
    from beamo_wipe import support_export as E

    wizard = make_demo_wizard()
    wizard.screen = Screen.DIAGNOSTIC
    wizard.diagnostic_message = E.USB_VOLUME_WRITABLE
    app = ui(wizard)
    assert E.USB_VOLUME_WRITABLE in text(app)
    assert E.NEXT_REPLUG in text(app)
