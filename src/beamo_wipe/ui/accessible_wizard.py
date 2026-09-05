# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK accessibility view. All authorization and operations belong to Wizard."""

from __future__ import annotations

from typing import Callable
import os
import subprocess
import sys

import gi

os.environ["GTK_MODULES"] = "gail:atk-bridge"
os.environ["NO_AT_BRIDGE"] = "0"
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from beamo_wipe import copy as C  # noqa: E402
from beamo_wipe import diagnostic_report as D, inventory, storage_limits  # noqa: E402
from beamo_wipe.methods import METHODS  # noqa: E402
from beamo_wipe.models import Screen  # noqa: E402
from beamo_wipe.wizard import Wizard, format_progress_percent  # noqa: E402


class AccessibleWizard:
    def __init__(self, wizard: Wizard, fullscreen: bool = False):
        self.w = wizard
        self.failed = False
        self.closed = False
        self.window = Gtk.Window(title="Beamo Wipe — screen-reader view")
        # GtkLabel needs selectable text to accept keyboard focus, but its
        # default select-all-on-focus emits text-selection-changed first.
        # Orca can consume that event and suppress the real focus announcement.
        # Keep manual selection available without selecting text on arrival.
        self.window.get_settings().set_property("gtk-label-select-on-focus", False)
        self.window.set_default_size(800, 600)
        if fullscreen:
            self.window.fullscreen()
        self.window.connect("delete-event", self._close)
        self.window.connect("key-press-event", self._key_press)
        self.window.connect("key-release-event", self._key_release)
        self.held: set[int] = set()
        self.generation = 0
        self.timer = 0
        self.primary = None
        self.progress_label = None
        self.countdown_label = None
        self.error_label = None
        self.shown = None
        self.report_revision = -1
        self.actions: dict[str, Gtk.Button] = {}
        self.render()
        self.timer = GLib.timeout_add(100, self.tick)

    def label(self, text: str, *, focusable: bool = False):
        widget = Gtk.Label(label=text)
        widget.set_line_wrap(True)
        widget.set_xalign(0)
        widget.set_max_width_chars(70)
        widget.set_can_focus(focusable)
        widget.set_selectable(focusable)
        self.body.pack_start(widget, False, False, 4)
        return widget

    def button(self, text: str, action: Callable, *, enabled: bool = True):
        widget = Gtk.Button.new_with_label(text)
        widget.set_sensitive(enabled)
        widget.get_child().set_line_wrap(True)
        widget.get_child().set_max_width_chars(65)
        generation = self.generation

        def clicked(_button):
            # A queued AT-SPI or key action from a replaced screen is stale.
            if generation != self.generation or not widget.get_sensitive():
                return
            action()
            if self.w.wants_shutdown:
                self.close()
            else:
                self.render()

        widget.connect("clicked", clicked)
        self.footer.pack_start(widget, False, False, 3)
        self.actions[text] = widget
        return widget

    def identity(self):
        disk = self.w.selected
        if disk:
            self.label(
                f"{disk.display_name}; {disk.size_phrase}; {disk.path}; Serial: {disk.serial or 'unavailable'}"
            )

    def reader(self, text: str):
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(text)
        view.get_accessible().set_name(text)
        view.set_can_focus(True)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(180)
        scroll.add(view)
        self.body.pack_start(scroll, False, False, 4)
        return view

    def render(self):
        self.generation += 1
        self.actions = {}
        self.primary = self.progress_label = self.countdown_label = None
        self.shown = self.w.screen
        self.report_revision = self.w.report_view.revision
        old = self.window.get_child()
        if old:
            self.window.remove(old)
            old.destroy()
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        shell.set_border_width(16)
        self.window.add(shell)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        shell.pack_start(scroll, True, True, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroll.add(self.body)
        self.footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        shell.pack_start(self.footer, False, False, 0)
        if self.w.preview:
            self.label(C.PREVIEW_BANNER)
        screen = self.w.screen
        generation = self.generation
        heading = self.label("Beamo Wipe", focusable=True)
        if screen == Screen.SPLASH:
            heading.set_text(C.SPLASH_TAGLINE)
            self.button(C.BTN_CONTINUE, self.w.skip_splash)
        elif screen == Screen.WHAT:
            heading.set_text(C.TITLE_WHAT)
            self.label(C.WHAT_LEAD)
            self.label("\n".join(C.WHAT_BULLETS))
            self.button(C.BTN_CONTINUE, self.w.accept_what)
        elif screen == Screen.OWNER:
            heading.set_text(C.TITLE_OWNER)
            self.label(C.OWNER_LEAD)
            check = Gtk.CheckButton.new_with_label(C.OWNER_CHECKBOX)
            check.get_child().set_line_wrap(True)
            check.get_child().set_max_width_chars(65)
            check.set_active(self.w.owner_ok)
            self.body.pack_start(check, False, False, 4)
            self.primary = self.button(
                C.BTN_CONTINUE, self.w.continue_owner, enabled=self.w.owner_ok
            )
            check.connect(
                "toggled", lambda widget: self._owner(widget.get_active(), generation)
            )
        elif screen == Screen.PICK:
            heading.set_text(C.TITLE_PICK)
            self.label("Eligible disks. Choose the exact disk you intend to erase.")
            for disk in sorted(self.w.selectable, key=lambda d: d.path):
                text = f"Select {disk.display_name}; {disk.size_phrase}; {disk.path}; Serial: {disk.serial or 'unavailable'}"
                button = self.button(text, lambda path=disk.path: self._select(path))
                self.footer.remove(button)
                self.body.pack_start(button, False, False, 3)
            self._inventory()
        elif screen in (Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            heading.set_text(
                C.TITLE_EMPTY if screen == Screen.PICK_EMPTY else C.IDENTIFY_ERROR
            )
            self.label(
                C.EMPTY_DISKS
                if screen == Screen.PICK_EMPTY
                else (self.w.error or C.IDENTIFY_ERROR)
            )
            self._inventory()
            self.button("Shut down", self.w.shutdown)
        elif screen == Screen.CONFIRM:
            heading.set_text(self.w.warning_text())
            self.identity()
            prompt = self.w.confirm.prompt if self.w.confirm else "No target selected"
            self.label(prompt)
            entry = Gtk.Entry()
            entry.get_accessible().set_name(prompt)
            entry.set_text(self.w.confirm_input)
            self.body.pack_start(entry, False, False, 4)
            self.primary = self.button(
                C.BTN_CONTINUE, self.w.continue_confirm, enabled=self.w.token_ok
            )
            entry.connect(
                "changed", lambda widget: self._token(widget.get_text(), generation)
            )
        elif screen == Screen.METHOD:
            heading.set_text(C.TITLE_METHOD)
            self.identity()
            self.label(self.w.storage_notice, focusable=True)
            group = None
            for method, spec in METHODS.items():
                choice = Gtk.RadioButton.new_with_label_from_widget(group, spec.summary)
                choice.get_child().set_line_wrap(True)
                choice.get_child().set_max_width_chars(65)
                group = choice
                choice.set_active(self.w.method == method)
                self.body.pack_start(choice, False, False, 3)
                choice.connect(
                    "toggled",
                    lambda widget, mid=method: self.w.set_method(mid)
                    if widget.get_active() and generation == self.generation
                    else None,
                )
            self.button(storage_limits.BUTTON, self.w.open_limits)
            self.button(C.BTN_ADVANCED, self.w.open_advanced)
            self.button(C.BTN_CONTINUE, self.w.continue_method)
        elif screen == Screen.REPORT_HELP:
            heading.set_text(C.REPORT_HELP_TITLE)
            reader = self.reader(
                C.REPORT_HELP_TEXT
                + (
                    "\n\n" + self.w.report_recovery_warning
                    if self.w.report_recovery_warning
                    else ""
                )
            )

            def set_preference(widget):
                if generation != self.generation:
                    return
                self.w.set_report_wanted(widget.get_active())
                content = C.REPORT_HELP_TEXT + (
                    "\n\n" + self.w.report_recovery_warning
                    if self.w.report_recovery_warning
                    else ""
                )
                reader.get_buffer().set_text(content)
                reader.get_accessible().set_name(content)

            choice = Gtk.CheckButton.new_with_label(C.REPORT_WANTED)
            choice.set_active(self.w.report_wanted)
            choice.connect(
                "toggled",
                set_preference,
            )
            self.body.pack_start(choice, False, False, 4)
        elif screen == Screen.LIMITS:
            heading.set_text(storage_limits.TITLE)
            self.reader(storage_limits.full_text())
        elif screen == Screen.ADVANCED:
            heading.set_text(C.TITLE_ADVANCED)
            self.reader(C.ADVANCED_LEAD + "\n" + C.ADVANCED_LOG_NOTE)
        elif screen == Screen.LAST_CHANCE:
            heading.set_text(f"{C.TITLE_LAST}. {self.w.erase_label()} {C.LAST_LEAD}")
            self.identity()
            self.label(self.w.method_summary)
            self.countdown_label = self.label("")
            self.primary = self.button(
                C.BTN_ERASE, self.w.confirm_erase, enabled=self.w.erase_enabled
            )
        elif screen == Screen.WORKING:
            heading.set_text(C.WORKING_PULSE)
            self.identity()
            self.label(self.w.method_summary)
            self.progress_label = self.label("")
            self.button("Cancel erase", self.w.cancel_wipe)
        elif screen == Screen.DONE:
            result = self.w.result_view
            heading.set_text(result.announcement)
            icon = Gtk.Image.new_from_icon_name(
                {
                    "check": "emblem-ok-symbolic",
                    "warn": "dialog-warning-symbolic",
                    "danger": "dialog-error-symbolic",
                    "info": "dialog-information-symbolic",
                }[result.icon],
                Gtk.IconSize.DIALOG,
            )
            icon.get_accessible().set_name(result.message)
            css = Gtk.CssProvider()
            color = {
                "ok": "#176b38",
                "warn": "#825600",
                "danger": "#ae2020",
                "info": "#245789",
            }[result.tone]
            css.load_from_data(f"image {{ color: {color}; }}".encode())
            icon.get_style_context().add_provider(
                css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            self.body.pack_start(icon, False, False, 0)
            heading.get_accessible().set_description(
                f"Result: {result.code}. Status: {result.tone}."
            )
            self.identity()
            self.label(self.w.method_summary)
            report = self.w.report_view
            if report.evidence_error:
                self.label(f"Evidence was not saved: {report.evidence_error}")
            self.label(self.w.result_view.next_step)
            if not self.w.preview:
                self.label(
                    C.report_aftercare(
                        can_save=report.can_save,
                        status=report.status,
                        message=report.message,
                    )
                )
            if self.w.preview:
                self.button(C.BTN_RUN_AGAIN, self.w.reset_for_preview)
            else:
                self.button(
                    C.BTN_SAVE_REPORT,
                    self.w.begin_report_export,
                    enabled=report.can_save,
                )
            self.button(
                "Close preview" if self.w.preview else "Shut down", self.w.shutdown
            )
        elif screen == Screen.SHUTDOWN_CONFIRM:
            heading.set_text(C.SHUTDOWN_TITLE)
            self.label(C.SHUTDOWN_LOSS)
            self.label(C.SHUTDOWN_HINT)
            if self.w.report_recovery_warning:
                self.label(self.w.report_recovery_warning)
            self.button(C.SHUTDOWN_KEEP, self.w.keep_report_session)
            generation = self.w.shutdown_generation
            self.button(
                C.SHUTDOWN_DISCARD,
                lambda: self.w.confirm_shutdown_without_saving(generation),
            )
        elif screen == Screen.DIAGNOSTIC:
            view = self.w.diagnostic_view
            heading.set_text(D.TITLE)
            self.label(D.NOTICE)
            self.label(D.PREPARE)
            self.label(view.message, focusable=True)
            self.button(
                "Save diagnostic report" if view.ready else "Prepare",
                lambda: self.w.diagnostic_action(background=True),
                enabled=not view.busy,
            )
            self.button("Back", self.w.close_diagnostic, enabled=not view.busy)
            self.button("Shut down", self.w.shutdown, enabled=not view.busy)
        elif screen == Screen.REFRESHING:
            heading.set_text(
                "Checking disks again. Previous confirmations have been cleared."
            )
        else:
            heading.set_text(
                "The current screen could not be confirmed. Contact support."
            )
        self.error_label = self.label(self.w.error or "", focusable=True)
        if self.w.can_open_diagnostic:
            self.button("Diagnostic report", self.w.open_diagnostic)
        if self.w.can_open_report_help:
            self.button(C.REPORT_HELP_TITLE, self.w.open_report_help)
        if self.w.can_refresh:
            self.button("Check disks again (F5)", self.w.refresh_disks)
        if screen in {
            Screen.OWNER,
            Screen.PICK,
            Screen.PICK_EMPTY,
            Screen.PICK_BLOCKED,
            Screen.CONFIRM,
            Screen.METHOD,
            Screen.LAST_CHANCE,
            Screen.LIMITS,
            Screen.REPORT_HELP,
            Screen.ADVANCED,
        }:
            self.button(C.BTN_BACK, self.w.back)
        self.window.show_all()
        self.window.present()
        if self.window.get_window():
            self.window.get_window().focus(Gdk.CURRENT_TIME)
        heading.grab_focus()
        self.update_status()

    def _inventory(self):
        if self.w.other_devices:
            self.label(inventory.TITLE)
            self.reader(inventory.full_text(self.w.other_devices))

    def _select(self, path):
        self.w.select_disk(path)
        self.w.continue_pick()

    def _owner(self, checked, generation):
        if generation != self.generation or self.w.screen != Screen.OWNER:
            return
        self.w.set_owner(checked)
        self.primary.set_sensitive(self.w.owner_ok)

    def _token(self, text, generation):
        if generation != self.generation or self.w.screen != Screen.CONFIRM:
            return
        self.w.set_confirm_input(text)
        self.primary.set_sensitive(self.w.token_ok)

    def update_status(self):
        if self.countdown_label:
            self.countdown_label.set_text(
                f"Wait {self.w.countdown_display} seconds."
                if not self.w.erase_enabled
                else "The countdown is complete. Erasure still requires Erase now."
            )
            self.primary.set_sensitive(self.w.erase_enabled)
        if self.progress_label:
            percent = (
                "Progress not reported"
                if self.w.progress is None
                else format_progress_percent(self.w.progress)
            )
            self.progress_label.set_text(f"{percent}. {C.WORKING_PULSE}")
        if self.error_label:
            message = self.w.error or ""
            changed = self.error_label.get_text() != message
            self.error_label.set_text(message)
            if changed and message:
                self.error_label.grab_focus()

    def tick(self):
        self.w.tick()
        if self.w.wants_shutdown:
            self.close()
            return False
        if (
            self.shown != self.w.screen
            or self.report_revision != self.w.report_view.revision
        ):
            self.render()
        else:
            self.update_status()
        return True

    def _key_press(self, _window, event):
        key = event.keyval
        if key in self.held and key in {
            Gdk.KEY_Return,
            Gdk.KEY_KP_Enter,
            Gdk.KEY_space,
        }:
            return True
        self.held.add(key)
        if key in (Gdk.KEY_l, Gdk.KEY_L) and self.w.screen == Screen.METHOD:
            self.w.open_limits()
            self.render()
            return True
        if key == Gdk.KEY_F5 and self.w.can_refresh:
            self.w.refresh_disks()
            self.render()
            return True
        if key == Gdk.KEY_Escape and self.w.screen != Screen.WORKING:
            self.w.back()
            self.render()
            return True
        return False

    def _key_release(self, _window, event):
        self.held.discard(event.keyval)
        return False

    def _close(self, *_args):
        if self.w.screen == Screen.WORKING:
            self.w.cancel_wipe()
            self.render()
        else:
            self.w.shutdown()
            if self.w.wants_shutdown:
                self.close()
            else:
                self.render()
        return True

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.window.destroy()
        if Gtk.main_level():
            Gtk.main_quit()

    def _runtime_failure(self, _kind, error, _traceback):
        from beamo_wipe.diagnostics import log_diag

        self.failed = True
        try:
            log_diag("ui", "accessible_runtime_failed", type(error).__name__)
        except Exception:
            pass
        try:
            if self.w.screen == Screen.WORKING:
                self.w.cancel_wipe(origin="system")
        finally:
            self.close()

    def run(self):
        previous = sys.excepthook
        sys.excepthook = self._runtime_failure
        try:
            Gtk.main()
        finally:
            sys.excepthook = previous
        return 3 if self.failed else 0


def run_accessible(wizard: Wizard, fullscreen: bool = False) -> int:
    from beamo_wipe.safety import running_on_live_usb

    reader = None
    if running_on_live_usb():
        subprocess.run(
            ["/usr/bin/pulseaudio", "--start", "--exit-idle-time=60"],
            check=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        reader = subprocess.Popen(
            ["/usr/bin/orca"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    try:
        return AccessibleWizard(wizard, fullscreen).run()
    finally:
        if reader is not None and reader.poll() is None:
            reader.terminate()
            try:
                reader.wait(timeout=5)
            except subprocess.TimeoutExpired:
                reader.kill()
                reader.wait(timeout=5)
