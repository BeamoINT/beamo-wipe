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
gi.require_version("Atk", "1.0")
from gi.repository import Atk, Gdk, GLib, Gtk, Pango  # noqa: E402

from beamo_wipe import copy as C  # noqa: E402
from beamo_wipe import diagnostic_report as D, inventory, sound, storage_limits  # noqa: E402
from beamo_wipe.outcomes import may_have_erased  # noqa: E402
from beamo_wipe.recovery import (  # noqa: E402
    recovery_for_blocked,
    recovery_for_diagnostic,
    recovery_for_empty,
    recovery_for_view,
    recovery_for_wizard_error,
)
from beamo_wipe import keyboard as _keyboard  # noqa: E402
from beamo_wipe.keyboard import LAYOUT_ORDER  # noqa: E402
from beamo_wipe.lang import LANGUAGE_NAMES, LANGUAGE_ORDER  # noqa: E402
from beamo_wipe.methods import METHODS  # noqa: E402
from beamo_wipe.models import Screen  # noqa: E402
from beamo_wipe.diagnostics import emit_serial_marker  # noqa: E402
from beamo_wipe.safety import same_size_conflict  # noqa: E402
from beamo_wipe.wizard import Wizard, error_needs_support  # noqa: E402


def _error_text(wizard: Wizard) -> str:
    """Error severity in words. Shared by render and tick updates so the
    live refresh never drops the label."""
    if not wizard.error:
        return ""
    text = f"{C.SEVERITY_ERROR}: {wizard.error}"
    if error_needs_support(wizard.error):
        text += " " + C.support_text()
    return text


class AccessibleWizard:
    def __init__(self, wizard: Wizard, fullscreen: bool = False):
        self.w = wizard
        self.failed = False
        self.closed = False
        self.window = Gtk.Window(title=C.ACCESSIBLE_TITLE)
        # GtkLabel needs selectable text to accept keyboard focus, but its
        # default select-all-on-focus emits text-selection-changed first.
        # Orca can consume that event and suppress the real focus announcement.
        # Keep manual selection available without selecting text on arrival.
        self.window.get_settings().set_property("gtk-label-select-on-focus", False)
        self.window.set_name("beamo-accessible")
        self._style = Gtk.CssProvider()
        self._apply_type_css()
        # Size before the first show: a low-resolution live session may have
        # no window manager to constrain an oversized default for us.
        width, height = 900, 700
        display = self.window.get_display()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor is not None:
            workarea = monitor.get_workarea()
            width = min(width, workarea.width)
            height = min(height, workarea.height)
        self.window.set_default_size(width, height)
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

    def _apply_type_css(self) -> None:
        scale = getattr(self.w, "text_scale", 1.0)
        body = max(12, int(round(16 * scale)))
        heading = max(18, int(round(26 * scale)))
        css = f"""
            #beamo-accessible {{ background: #FFFFFF; color: #12202E; }}
            #beamo-accessible label {{ font-size: {body}px; }}
            #beamo-accessible .screen-heading {{ font-size: {heading}px; font-weight: bold; color: #12202E; }}
            #beamo-accessible .preview-notice {{ background: #E6A817; color: #0A1B34; padding: 8px; }}
            #beamo-accessible .disk-identity {{ background: #F0F5FA; color: #12202E; padding: 16px 20px; border: 1px solid #1C4A73; border-radius: 12px; }}
            #beamo-accessible button {{ padding: 10px 20px; border-radius: 999px; }}
            #beamo-accessible button.primary-action {{ background-image: none; background-color: #1C4A73; color: #FFFFFF; }}
            #beamo-accessible button.primary-action:hover {{ background-color: #163A5C; }}
            #beamo-accessible button.primary-action:active {{ background-color: #102A44; }}
            #beamo-accessible button.destructive-action {{ background-image: none; background-color: #B3261E; color: #FFFFFF; }}
            #beamo-accessible button.destructive-action:hover {{ background-color: #8E1D16; }}
            #beamo-accessible button.destructive-action:active {{ background-color: #6E1510; }}
            #beamo-accessible button:disabled {{ background-image: none; background-color: #E8ECF1; color: #6E7989; }}
            #beamo-accessible button:focus {{ outline: 3px solid #2563EB; outline-offset: 2px; }}
            #beamo-accessible checkbutton {{ padding: 8px 10px; border-radius: 12px; }}
            #beamo-accessible checkbutton:hover {{ background-color: #F4F6F8; }}
            #beamo-accessible checkbutton:checked {{ background-color: #F0F5FA; }}
            #beamo-accessible checkbutton:focus {{ outline: 3px solid #2563EB; outline-offset: 2px; }}
            #beamo-accessible entry {{ padding: 8px 12px; border-radius: 12px; }}
            #beamo-accessible button.utility-action {{ background-image: none; background-color: #FFFFFF; color: #1C4A73; box-shadow: none; }}
            #beamo-accessible button.utility-action:hover {{ background-color: #F0F5FA; }}
            #beamo-accessible button.utility-action:active {{ background-color: #D7E4F2; }}
            #beamo-accessible .erase-warning {{ background: #FBF1D5; color: #7A5200; padding: 12px 16px; border-radius: 12px; }}
            #beamo-accessible .screen-actions {{ border-top: 1px solid #E3E8EE; padding-top: 12px; }}
            #beamo-accessible .report-warning {{ background: #FBF1D5; color: #7A5200; padding: 10px 14px; border-radius: 12px; }}
            #beamo-accessible .report-saved {{ background: #E7F2EB; color: #17703F; padding: 10px 14px; border-radius: 12px; }}
            #beamo-accessible .error-message {{ color: #B3261E; font-weight: bold; }}
        """
        self._style.load_from_data(css.encode())

    def label(self, text: str, *, focusable: bool = False):
        widget = Gtk.Label(label=text)
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_xalign(0)
        widget.set_max_width_chars(70)
        widget.set_can_focus(focusable)
        widget.set_selectable(focusable)
        self.body.pack_start(widget, False, False, 4)
        return widget

    def support_identity_labels(self) -> None:
        ident = self.w.support_identity
        if ident is None:
            return
        self.label(C.support_identity_text(ident), focusable=True)

    def recovery(self, sections) -> None:
        """Screen-reader order: happened, meaning, next, then technical."""
        for label, body in sections.labeled_pairs():
            heading = self.label(label, focusable=True)
            heading.get_accessible().set_role(Atk.Role.HEADING)
            heading.get_style_context().add_class("recovery-heading")
            self.label(body, focusable=True)
        if sections.technical:
            from beamo_wipe import recovery as Rec

            expander = Gtk.Expander.new(Rec.RECOVERY_TECHNICAL)
            reader = Gtk.Label(label=sections.technical)
            reader.set_line_wrap(True)
            reader.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            reader.set_max_width_chars(65)
            reader.set_selectable(True)
            reader.set_can_focus(True)
            expander.add(reader)
            self.body.pack_start(expander, False, False, 4)

    def button(self, text: str, action: Callable, *, enabled: bool = True,
               utility: bool = False, in_body: bool = False):
        widget = Gtk.Button.new_with_label(text)
        widget.set_sensitive(enabled)
        widget.set_can_default(False)
        widget.set_receives_default(False)
        widget.get_child().set_line_wrap(True)
        # Footer actions contain short words. Character wrapping would reduce
        # their minimum width to one glyph and inflate GTK's height request.
        widget.get_child().set_line_wrap_mode(
            Pango.WrapMode.WORD_CHAR if in_body else Pango.WrapMode.WORD
        )
        widget.get_child().set_max_width_chars(65 if in_body else 24)
        context = widget.get_style_context()
        if text in {C.BTN_ERASE, C.SHUTDOWN_DISCARD}:
            context.add_class("destructive-action")
        elif text in C.PRIMARY_ACTION_LABELS or text in {C.SHUTDOWN_KEEP, C.BTN_SAVE_REPORT}:
            context.add_class("primary-action")
        elif utility:
            context.add_class("utility-action")
        generation = self.generation

        def clicked(_button):
            # A queued AT-SPI or key action from a replaced screen is stale.
            if generation != self.generation or not widget.get_sensitive():
                return
            action()
            if self.w.wants_shutdown or self.w.wants_new_session:
                self.close()
            else:
                self.render()

        widget.connect("clicked", clicked)
        if in_body:
            self.body.pack_start(widget, False, False, 3)
        elif utility:
            self.utilities.attach(widget, self._utility_count % 3, self._utility_count // 3, 1, 1)
            self._utility_count += 1
        elif text == C.BTN_BACK:
            self.navigation.pack_start(widget, False, False, 0)
            self.navigation.reorder_child(widget, 0)
        else:
            self.navigation.pack_end(widget, False, False, 0)
        self.actions[text] = widget
        return widget

    def _style_tree(self, widget):
        # Widget-scoped providers cannot recolor other apps or later windows.
        widget.get_style_context().add_provider(self._style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                self._style_tree(child)

    def identity(self):
        disk = self.w.operation_disk
        if disk is not None:
            self.label(self.w.disk_view(disk).announcement).get_style_context().add_class(
                "disk-identity"
            )
        elif self.w.operation_identity_text:
            self.label(self.w.operation_identity_text).get_style_context().add_class(
                "disk-identity"
            )

    def reader(self, text: str):
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(text)
        view.get_accessible().set_name(text)
        view.set_can_focus(True)
        scroll = Gtk.ScrolledWindow()
        # A TextView can initially request the width of its longest paragraph
        # even with wrapping enabled. NEVER propagates that request through
        # the outer viewport and widens the window (Advanced exceeded 800px).
        # AUTOMATIC constrains the reader; normal text still wraps in place.
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(180)
        scroll.add(view)
        self.body.pack_start(scroll, False, False, 4)
        return view

    def render(self):
        self.generation += 1
        self._apply_type_css()
        self.actions = {}
        self.primary = self.progress_label = self.countdown_label = None
        self.power_label = None
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
        self.footer.get_style_context().add_class("screen-actions")
        shell.pack_start(self.footer, False, False, 0)
        # Utilities wrap independently of navigation. Keep the action footer
        # outside the scrolling body without six full-width button rows at
        # 800x600. No fixed content height or minimum window size is imposed.
        self.utilities = Gtk.Grid()
        self.utilities.set_column_homogeneous(True)
        self.utilities.set_column_spacing(6)
        self.utilities.set_row_spacing(4)
        # Grouping names must not rewrite action or result heading ATK names.
        self.utilities.get_accessible().set_role(Atk.Role.PANEL)
        self.utilities.get_accessible().set_name(C.ASSIST_LABEL)
        self._utility_count = 0
        self.footer.pack_start(self.utilities, False, False, 0)
        self.navigation = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.navigation.get_accessible().set_role(Atk.Role.PANEL)
        self.navigation.get_accessible().set_name(C.NAV_LABEL)
        self.footer.pack_start(self.navigation, False, False, 4)
        if self.w.preview:
            self.label(C.PREVIEW_BANNER).get_style_context().add_class("preview-notice")
        screen = self.w.screen
        generation = self.generation
        heading = self.label("Beamo Wipe", focusable=True)
        heading.get_style_context().add_class("screen-heading")
        arrival = heading
        if screen == Screen.SPLASH:
            heading.set_text(C.SPLASH_TAGLINE)
            self.button(C.primary_action(Screen.SPLASH), self.w.skip_splash)
        elif screen == Screen.KEYBOARD:
            heading.set_text(C.TITLE_KEYBOARD)
            self.label(C.KEYBOARD_LEAD)
            self.label(C.KEYBOARD_LIMITS)
            self.label(C.TEXT_SIZE_LEAD)
            for size_id, label in C.TEXT_SIZE_LABELS.items():
                state = "selected" if self.w.text_size == size_id else C.ACCESSIBLE_NOT_SELECTED
                self.button(
                    f"{label} ({state})",
                    lambda sid=size_id: self.w.set_text_size(sid),
                    in_body=True,
                )
            for index, layout_id in enumerate(LAYOUT_ORDER, 1):
                spec = _keyboard.LAYOUTS[layout_id]
                state = "selected" if self.w.keyboard_layout == layout_id else C.ACCESSIBLE_NOT_SELECTED
                self.button(
                    f"{index} {spec.title} ({state})",
                    lambda lid=layout_id: self.w.set_keyboard_layout(lid),
                    in_body=True,
                )
                self.label(spec.note)
            self.label(C.TITLE_LANGUAGE)
            self.label(C.LANGUAGE_LEAD)
            for code in LANGUAGE_ORDER:
                state = "selected" if self.w.language == code else C.ACCESSIBLE_NOT_SELECTED
                self.button(
                    f"{LANGUAGE_NAMES[code]} ({state})",
                    lambda lang_code=code: self.w.set_language(lang_code),
                    in_body=True,
                )
            if self.w.error:
                sections = recovery_for_wizard_error(self.w.error)
                if sections:
                    self.recovery(sections)
                else:
                    self.label(f"{C.SEVERITY_ERROR}: {self.w.error}")
            elif self.w.keyboard_message:
                self.label(f"{C.SEVERITY_WARNING}: {self.w.keyboard_message}")
            self.label(C.KEYBOARD_CHECK_LABEL)
            entry = Gtk.Entry()
            entry.set_visibility(True)
            purpose = getattr(Gtk, "InputPurpose", None)
            if purpose is not None:
                entry.set_input_purpose(purpose.FREE_FORM)
            entry.set_text(self.w.typing_check)
            entry.set_placeholder_text(C.KEYBOARD_CHECK_HINT)
            generation = self.generation
            entry.connect(
                "changed",
                lambda widget: self._typing(widget.get_text(), generation),
            )
            self.body.pack_start(entry, False, False, 4)
            arrival = entry
            self.button(C.primary_action(Screen.KEYBOARD), self.w.accept_keyboard)
        elif screen in (Screen.WHAT, Screen.OWNER):
            heading.set_text(C.TITLE_OWNER)
            self.label(C.WHAT_LEAD)
            self.label(C.TITLE_WHAT)
            self.label("\n".join(C.WHAT_BULLETS))
            self.label(C.this_usb_line())
            self.label(C.REPORT_MEDIA_WHAT, focusable=True)
            self.label(C.POWER_REMINDER)
            self.label(C.POWER_BLANKING)
            self.label(C.POWER_EVENTS, focusable=True)
            self.support_identity_labels()
            self.label(C.OWNER_LEAD)
            check = Gtk.CheckButton.new_with_label(C.OWNER_CHECKBOX)
            check.get_child().set_line_wrap(True)
            check.get_child().set_max_width_chars(65)
            check.set_active(self.w.owner_ok)
            self.body.pack_start(check, False, False, 4)
            self.primary = self.button(
                C.primary_action(Screen.OWNER), self.w.continue_owner, enabled=self.w.owner_ok
            )
            check.connect(
                "toggled", lambda widget: self._owner(widget.get_active(), generation)
            )
        elif screen == Screen.PICK:
            heading.set_text(C.TITLE_PICK)
            self.label(C.pick_subtitle())
            self.button(C.DISK_HELP_BUTTON, self.w.open_disk_help, in_body=True)
            if same_size_conflict(self.w.listed_disks):
                self.label(f"{C.SEVERITY_WARNING}: {C.SAME_SIZE_HINT}")
            if self.w.error:
                sections = recovery_for_wizard_error(self.w.error)
                if sections:
                    self.recovery(sections)
                else:
                    self.label(f"{C.SEVERITY_ERROR}: {self.w.error}")
            if self.w.report_wanted:
                self.label(C.REPORT_MEDIA_WANTED, focusable=True)
            self._inventory_count()
            self._protected_boot()
            for disk in sorted(self.w.selectable, key=lambda d: d.path):
                text = f"Select {self.w.disk_view(disk).announcement}"
                self.button(text, lambda path=disk.path: self._select(path), in_body=True)
                nested = inventory.card_nesting_text(self.w.nested_components(disk))
                if nested:
                    self.label(nested, focusable=True)
            if len(self.w.selectable) > 1:
                expander = Gtk.Expander.new(inventory.COMPARE_TITLE)
                reader = Gtk.Label(label=inventory.comparison_text(self.w.selectable, peers=self.w.listed_disks))
                reader.set_line_wrap(True)
                reader.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                reader.set_max_width_chars(65)
                reader.set_selectable(True)
                reader.set_can_focus(True)
                expander.add(reader)
                self.body.pack_start(expander, False, False, 4)
            self._inventory()
        elif screen in (Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            heading.set_text(
                C.TITLE_EMPTY if screen == Screen.PICK_EMPTY else C.blocked_title(self.w.error, recovered=self.w._recovered)
            )
            self._inventory_count()
            if screen == Screen.PICK_EMPTY:
                self.recovery(recovery_for_empty())
                self.label(C.support_text(), focusable=True)
                self._protected_boot()
            else:
                self.recovery(
                    recovery_for_blocked(self.w.error, recovered=self.w._recovered)
                )
            self.support_identity_labels()
            self._inventory()
            self.button(C.BTN_SHUTDOWN, self.w.shutdown)
        elif screen == Screen.CONFIRM:
            heading.set_text(C.TITLE_CONFIRM)
            self.identity()
            arrival = self.label(f"{C.SEVERITY_WARNING}: {self.w.warning_text()}", focusable=True)
            arrival.get_style_context().add_class("erase-warning")
            arrival.get_accessible().set_role(Atk.Role.ALERT)
            self.label(C.CONFIRM_KEYBOARD_LINE.format(
                layout=_keyboard.LAYOUTS[self.w.keyboard_layout].title,
                language=LANGUAGE_NAMES[self.w.language],
            ))
            prompt = self.w.confirm.prompt if self.w.confirm else C.ACCESSIBLE_NO_TARGET
            self.label(prompt)
            entry = Gtk.Entry()
            entry.get_accessible().set_name(prompt)
            entry.set_text(self.w.confirm_input)
            self.body.pack_start(entry, False, False, 4)
            self.primary = self.button(
                C.primary_action(Screen.CONFIRM), self.w.continue_confirm, enabled=self.w.token_ok
            )
            entry.connect(
                "changed", lambda widget: self._token(widget.get_text(), generation)
            )
        elif screen == Screen.METHOD:
            heading.set_text(C.TITLE_METHOD)
            self.identity()
            self.label(f"{C.SEVERITY_LIMITS}: {self.w.storage_notice}", focusable=True)
            group = None
            for method, spec in METHODS.items():
                card = C.METHOD_CARDS[method]
                # Keep the radio ATK name as the method summary. Plain lead
                # and everyday limits stay off the radio so 800x600 choices
                # remain above the footer (same pattern as #51 headings).
                label = spec.summary
                if card["mark"]:
                    label = f"{label} [{card['mark']}]"
                if card["extra"]:
                    label = f"{label} {card['extra']}"
                choice = Gtk.RadioButton.new_with_label_from_widget(group, label)
                choice.get_child().set_line_wrap(True)
                choice.get_child().set_max_width_chars(65)
                group = choice
                choice.set_active(self.w.method == method)
                if spec.plain_lead:
                    choice.get_accessible().set_description(spec.plain_lead)
                self.body.pack_start(choice, False, False, 3)
                choice.connect(
                    "toggled",
                    lambda widget, mid=method: self.w.set_method(mid)
                    if widget.get_active() and generation == self.generation
                    else None,
                )
            for spec in METHODS.values():
                self.label(spec.plain_lead)
            for spec_method in METHODS:
                note = str(C.METHOD_CARDS[spec_method]["limits"] or "")
                if note:
                    self.label(note, focusable=True)
            self.button(storage_limits.BUTTON, self.w.open_limits, utility=True)
            self.button(C.BTN_ADVANCED, self.w.open_advanced, utility=True)
            self.button(C.primary_action(Screen.METHOD), self.w.continue_method)
        elif screen == Screen.DISK_HELP:
            heading.set_text(C.DISK_HELP_TITLE)
            self.reader(C.DISK_HELP_TEXT)
            self.button(C.DISK_HELP_STOP, self.w.shutdown)
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
            choice.get_child().set_line_wrap(True)
            choice.get_child().set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            choice.get_child().set_max_width_chars(65)
            choice.set_active(self.w.report_wanted)
            choice.connect(
                "toggled",
                set_preference,
            )
            self.body.pack_start(choice, False, False, 4)
            share = Gtk.CheckButton.new_with_label(C.REPORT_SHARE_REDACTED)
            share.get_child().set_line_wrap(True)
            share.get_child().set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            share.get_child().set_max_width_chars(65)
            share.set_active(self.w.report_share_redacted)
            share.connect(
                "toggled",
                lambda widget: self.w.set_report_share_redacted(widget.get_active())
                if generation == self.generation
                else None,
            )
            self.body.pack_start(share, False, False, 4)
        elif screen == Screen.LIMITS:
            heading.set_text(storage_limits.TITLE)
            self.reader(storage_limits.full_text())
        elif screen == Screen.ADVANCED:
            heading.set_text(C.TITLE_ADVANCED)
            self.reader(C.ADVANCED_LEAD + "\n" + C.ADVANCED_LOG_NOTE)
        elif screen == Screen.LAST_CHANCE:
            heading.set_text(C.TITLE_LAST)
            self.label(C.LAST_LEAD)
            self.identity()
            self.label(self.w.prepare_text())
            self.label(self.w.operation_summary)
            # Orca reads a label's actual text, even when its accessible name
            # differs. Focus the full warning notice so arrival still speaks
            # the destructive consequence, without an oversized heading.
            arrival = self.label(f"{C.SEVERITY_WARNING}: {self.w.erase_label()}", focusable=True)
            arrival.get_style_context().add_class("erase-warning")
            arrival.get_accessible().set_role(Atk.Role.ALERT)
            self.label(self.w.method_summary)
            if self.w.error:
                sections = recovery_for_wizard_error(self.w.error)
                if sections:
                    self.recovery(sections)
                else:
                    self.label(f"{C.SEVERITY_ERROR}: {self.w.error}", focusable=True)
            self.support_identity_labels()
            self.countdown_label = self.label("")
            self.primary = self.button(
                C.BTN_ERASE, self.w.begin_erase, enabled=self.w.erase_enabled
            )
        elif screen == Screen.CHECKING:
            heading.set_text(C.BUSY_CHECKING_TITLE)
            self.identity()
            self.label(C.BUSY_CHECKING_MESSAGE)
        elif screen == Screen.STOPPING:
            heading.set_text(C.BUSY_STOPPING_TITLE)
            self.identity()
            self.label(self.w.operation_method_text)
            self.label(C.STOPPING_TEXT)
            self.progress_label = self.label("")
        elif screen == Screen.WORKING:
            heading.set_text(C.VIEWS["stop_unconfirmed"].message
                             if self.w.error == C.VIEWS["stop_unconfirmed"].announcement
                             else C.WORKING_PULSE)
            self.identity()
            self.label(self.w.method_summary)
            self.progress_label = self.label("")
            if self.w.error:
                sections = recovery_for_wizard_error(self.w.error)
                if sections:
                    self.recovery(sections)
            if self.w.evidence_warning:
                self.label(f"{C.SEVERITY_WARNING}: {self.w.evidence_warning}")
            if self.w.stop_confirmation is not None:
                confirmation = self.w.stop_confirmation
                heading.set_text(C.STOP_TITLE)
                arrival = self.label(f"{C.SEVERITY_WARNING}: {C.STOP_LEAD}", focusable=True)
                arrival.get_style_context().add_class("erase-warning")
                arrival.get_accessible().set_role(Atk.Role.ALERT)
                self.button(C.STOP_KEEP, self.w.keep_erasing)
                self.button(C.STOP_CONFIRM, lambda: self.w.confirm_stop(confirmation))
            else:
                self.button(C.STOP_ASK, self.w.request_stop)
        elif screen == Screen.DONE:
            self.w.maybe_play_outcome_sound()
            result = self.w.result_view
            sections = recovery_for_view(result)
            heading.set_text(result.message if sections else result.announcement)
            heading.get_accessible().set_role(Atk.Role.HEADING)
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
                "ok": "#17703F",
                "warn": "#7A5200",
                "danger": "#B3261E",
                "info": "#1C4A73",
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
            self.label(self.w.elapsed_text)
            if sections:
                self.recovery(sections)
            else:
                self.label(self.w.result_view.next_step)
            if self.w.done_support_needed:
                self.label(C.support_text(), focusable=True)
            self.support_identity_labels()
            if may_have_erased(result.code):
                self.label(C.POST_ERASE_BOOT)
            for alert in self.w.check_alerts:
                self.label(f"{C.SEVERITY_WARNING}: {alert}")
            report = self.w.report_view
            report_heading = self.label(C.REPORT_STATUS_TITLE, focusable=True)
            report_heading.get_accessible().set_role(Atk.Role.HEADING)
            report_heading.get_style_context().add_class("screen-heading")
            if self.w.preview:
                report_summary = self.label(C.REPORT_PREVIEW, focusable=True)
            elif report.tone == "ok":
                report_summary = self.label(f"{C.SEVERITY_SAVED}: {report.headline}", focusable=True)
                report_summary.get_style_context().add_class("report-saved")
            elif report.tone == "warn":
                report_summary = self.label(f"{C.SEVERITY_WARNING}: {report.headline}", focusable=True)
                report_summary.get_style_context().add_class("report-warning")
                report_summary.get_accessible().set_role(Atk.Role.ALERT)
            else:
                report_summary = self.label(report.headline, focusable=True)
            self.label(C.REPORT_STATUS_NOTICE)
            if report.evidence_error:
                self.label(f"{C.SEVERITY_WARNING}: {self.w.evidence_warning}")
            if not self.w.preview and not report.evidence_error:
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
                if report.evidence_error:
                    self.button(C.RETRY_SAVE, self.w.begin_evidence_retry,
                                enabled=report.can_retry_evidence)
                self.button(
                    C.BTN_SAVE_REPORT,
                    self.w.begin_report_export,
                    enabled=report.can_save,
                )
            if not self.w.preview:
                self.label(C.ANOTHER_HINT)
                self.button(C.BTN_ERASE_ANOTHER, self.w.erase_another_disk,
                            enabled=self.w.can_erase_another)
            self.button(
                C.BTN_CLOSE_PREVIEW if self.w.preview else C.BTN_SHUTDOWN, self.w.shutdown,
                enabled=not report.exporting and not report.saving_evidence,
            )
        elif screen == Screen.REFRESH_CONFIRM:
            heading.set_text(C.TITLE_REFRESH)
            self.label(C.REFRESH_LEAD, focusable=True)
            self.button(C.BTN_REFRESH, self.w.confirm_refresh)
            self.button(C.BTN_BACK, self.w.back)
        elif screen == Screen.SHUTDOWN_CONFIRM:
            heading.set_text(self.w.exit_confirmation_title)
            self.label(self.w.exit_confirmation_loss)
            self.label(C.SHUTDOWN_HINT)
            if self.w.report_recovery_warning:
                self.label(self.w.report_recovery_warning)
            self.label(C.MEDIA_STEPS_TITLE, focusable=True)
            self.label(self.w.exit_media_steps, focusable=True)
            self.button(C.SHUTDOWN_KEEP, self.w.keep_report_session)
            generation = self.w.shutdown_generation
            self.button(
                self.w.exit_confirmation_discard,
                lambda: self.w.confirm_shutdown_without_saving(generation),
            )
        elif screen == Screen.DIAGNOSTIC:
            view = self.w.diagnostic_view
            heading.set_text(D.report_title(self.w.startup_error_code))
            self.recovery(
                recovery_for_diagnostic(
                    self.w.startup_error_code,
                    view.message,
                    self.w.diagnostic_step,
                )
            )
            self.support_identity_labels()
            self.button(
                C.SAVE_DIAGNOSTIC_REPORT if view.ready else C.BTN_PREPARE,
                lambda: self.w.diagnostic_action(background=True),
                enabled=not view.busy,
            )
            self.button(C.BTN_BACK, self.w.close_diagnostic, enabled=not view.busy)
            self.button(C.BTN_SHUTDOWN, self.w.shutdown, enabled=not view.busy)
        elif screen == Screen.REFRESHING:
            heading.set_text(
                C.ACCESSIBLE_REFRESHED
            )
        else:
            heading.set_text(
                C.ACCESSIBLE_UNCONFIRMED
            )
            self.label(C.support_text(), focusable=True)
        self.error_label = self.label(_error_text(self.w), focusable=True)
        self.error_label.get_style_context().add_class("error-message")
        if self.w.error:
            self.error_label.get_accessible().set_role(Atk.Role.ALERT)
        if screen not in {
            Screen.CHECKING,
            Screen.STOPPING,
            Screen.REFRESHING,
            Screen.SHUTDOWN_CONFIRM,
        }:
            self.button(C.SOUND_CHECK_BUTTON, self.open_sound_check, utility=True)
        if self.w.can_open_diagnostic:
            self.button(C.DIAGNOSTIC_TITLE, self.w.open_diagnostic, utility=True)
        if self.w.can_open_report_help:
            self.button(C.REPORT_HELP_TITLE, self.w.open_report_help, utility=True)
        if self.w.can_refresh and screen != Screen.REFRESH_CONFIRM:
            self.button(C.BTN_REFRESH_UTILITY, self.w.open_refresh_confirm, utility=True)
        if self.w.can_open_keyboard and screen != Screen.KEYBOARD:
            self.button(C.KEYBOARD_UTILITY, self.w.open_keyboard, utility=True)
        if screen not in {
            Screen.SPLASH, Screen.KEYBOARD, Screen.WORKING, Screen.STOPPING,
            Screen.CHECKING, Screen.REFRESHING, Screen.DONE, Screen.SHUTDOWN_CONFIRM,
            Screen.METHOD, Screen.LAST_CHANCE, Screen.ADVANCED, Screen.LIMITS,
            Screen.DISK_HELP, Screen.REPORT_HELP,
        }:
            self.button(
                f"{C.TEXT_SIZE_UTILITY}: {C.TEXT_SIZE_LABELS.get(self.w.text_size, C.TEXT_SIZE_STANDARD)}",
                self.w.cycle_text_size,
                utility=True,
            )
        if screen in {
            Screen.WHAT,
            Screen.OWNER,
            Screen.PICK,
            Screen.PICK_EMPTY,
            Screen.PICK_BLOCKED,
            Screen.CONFIRM,
            Screen.METHOD,
            Screen.LAST_CHANCE,
            Screen.LIMITS,
            Screen.REPORT_HELP,
            Screen.DISK_HELP,
            Screen.ADVANCED,
        } or (screen == Screen.KEYBOARD and self.w._keyboard_from):
            self.button(C.BTN_BACK, self.w.back)
        if screen in {Screen.WHAT, Screen.OWNER, Screen.LAST_CHANCE, Screen.CHECKING, Screen.WORKING, Screen.STOPPING}:
            if screen not in {Screen.WHAT, Screen.OWNER}:
                self.label(C.POWER_KEEP)
            self.power_label = self.label(self.w.power_text, focusable=True)
        self._style_tree(self.window)
        self.window.show_all()
        if not self.utilities.get_children():
            self.footer.remove(self.utilities)
            self.utilities.destroy()
        self.window.present()
        if self.window.get_window():
            self.window.get_window().focus(Gdk.CURRENT_TIME)
        self.arrival = arrival
        arrival.grab_focus()
        self.update_status()
        # Stage is ATK description, not a prefix on the heading name.
        # Result/busy tests match the canonical announcement exactly;
        # "Result. Erase completed…" hid that title from heading names.
        spoken_stage = C.journey_announcement(screen)
        if spoken_stage:
            heading.get_accessible().set_description(spoken_stage)
        emit_serial_marker(f"BEAMO_WIPE_ACCESSIBLE_SCREEN_{screen.name}")

    def _protected_boot(self):
        if self.w.protected_boot_text:
            self.reader(self.w.protected_boot_text)

    def _inventory_count(self):
        text = self.w.inventory_count_announcement
        widget = self.label(text, focusable=True)
        widget.get_accessible().set_name(text)
        return widget

    def _inventory(self):
        if self.w.other_devices:
            self.label(inventory.TITLE)
            self.reader(inventory.full_text(self.w.other_devices))

    def open_sound_check(self):
        """Modal output controls and speech test. Native controls only:
        Tab moves, Enter activates, Esc closes. Shown, never run(), so the
        main loop keeps flowing while it is open."""
        state = sound.list_outputs()
        if state.available:
            applied = sound.apply_remembered_output(self.w)
            if applied is not None and applied.ok:
                state = sound.list_outputs()
        chosen: dict = {"output": sound.resolve_output(self.w.sound_output, state)}
        muted = {"value": bool(state.muted)}
        dialog = Gtk.Dialog(title=C.SOUND_CHECK_TITLE)
        dialog.set_transient_for(self.window)
        dialog.set_modal(True)
        dialog.set_destroy_with_parent(True)
        dialog.set_default_size(560, 480)
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_border_width(16)
        status = Gtk.Label(
            label=C.SOUND_DIALOG_LEAD if state.available else state.message
        )
        status.set_line_wrap(True)
        status.set_xalign(0)
        status.set_max_width_chars(65)
        status.set_can_focus(True)
        status.set_selectable(True)
        box.pack_start(status, False, False, 4)

        def announce(text):
            status.set_text(text)
            status.grab_focus()

        if sound.orca_running() is False:
            notice = Gtk.Label(label=C.SOUND_ORCA_MISSING)
            notice.set_line_wrap(True)
            notice.set_xalign(0)
            notice.set_max_width_chars(65)
            box.pack_start(notice, False, False, 4)
        volume_label = Gtk.Label(label="")
        volume_label.set_line_wrap(True)
        volume_label.set_xalign(0)
        volume_label.set_max_width_chars(65)
        mute_button = Gtk.Button.new_with_label(
            C.SOUND_UNMUTE if muted["value"] else C.SOUND_MUTE
        )

        def refresh_volume():
            fresh = sound.list_outputs()
            if fresh.available and fresh.volume_percent is not None:
                text = f"{C.SOUND_VOLUME}: {fresh.volume_percent}%"
                if fresh.muted:
                    text += f", {C.SOUND_MUTED_STATE}"
                elif fresh.volume_percent < 20:
                    text += f" {C.SOUND_VOLUME_LOW}"
                muted["value"] = bool(fresh.muted)
            else:
                text = C.SOUND_VOLUME_UNKNOWN
            volume_label.set_text(text)
            mute_button.set_label(
                C.SOUND_UNMUTE if muted["value"] else C.SOUND_MUTE
            )

        def on_output_toggled(choice, output):
            if not choice.get_active():
                return
            result = sound.set_output(output.id)
            if result.ok:
                self.w.set_sound_output(output.id)
                chosen["output"] = output
                refresh_volume()
                announce(f"{output.label} {C.SOUND_SELECTED}")
            else:
                announce(result.message)

        group = None
        for output in state.outputs:
            choice = Gtk.RadioButton.new_with_label_from_widget(group, output.label)
            choice.get_accessible().set_description(output.detail)
            choice.get_child().set_line_wrap(True)
            choice.get_child().set_max_width_chars(65)
            group = choice
            box.pack_start(choice, False, False, 3)
            if chosen["output"] is not None and output.id == chosen["output"].id:
                choice.set_active(True)
            choice.connect("toggled", on_output_toggled, output)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(controls, False, False, 4)
        controls.pack_start(volume_label, True, True, 0)
        louder = Gtk.Button.new_with_label(C.SOUND_LOUDER)
        quieter = Gtk.Button.new_with_label(C.SOUND_QUIETER)
        controls.pack_start(louder, False, False, 0)
        controls.pack_start(quieter, False, False, 0)
        controls.pack_start(mute_button, False, False, 0)

        def on_nudge(_button, delta):
            current = chosen["output"]
            if current is None:
                return
            result = sound.nudge_volume(current.id, delta)
            if result.ok:
                refresh_volume()
            else:
                announce(result.message)

        louder.connect("clicked", on_nudge, sound.VOLUME_STEP)
        quieter.connect("clicked", on_nudge, -sound.VOLUME_STEP)

        def on_mute(_button):
            current = chosen["output"]
            if current is None:
                return
            result = sound.set_muted(current.id, not muted["value"])
            if result.ok:
                muted["value"] = not muted["value"]
                refresh_volume()
            else:
                announce(result.message)

        mute_button.connect("clicked", on_mute)
        play = Gtk.Button.new_with_label(C.SOUND_PLAY_TEST)
        box.pack_start(play, False, False, 4)

        def on_play(_button):
            current = chosen["output"]
            if current is None:
                return
            applied = sound.set_output(current.id)
            if not applied.ok:
                announce(applied.message)
                return
            self.w.set_sound_output(current.id)
            announce(sound.play_speech_test().message)

        play.connect("clicked", on_play)
        outcome_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(outcome_row, False, False, 4)
        sounds_toggle = Gtk.Button.new_with_label(self.w.sound_toggle_text)
        hear_outcomes = Gtk.Button.new_with_label(C.SOUND_HEAR)
        outcome_row.pack_start(sounds_toggle, False, False, 0)
        outcome_row.pack_start(hear_outcomes, False, False, 0)

        def on_sounds_toggle(_button):
            self.w.toggle_sounds()
            sounds_toggle.set_label(self.w.sound_toggle_text)
            announce(self.w.sound_message)

        def on_hear_outcomes(_button):
            current = chosen["output"]
            if current is None:
                return
            applied = sound.set_output(current.id)
            if not applied.ok:
                announce(applied.message)
                return
            self.w.set_sound_output(current.id)
            announce(self.w.hear_both_sounds().message)

        sounds_toggle.connect("clicked", on_sounds_toggle)
        hear_outcomes.connect("clicked", on_hear_outcomes)
        controls.set_sensitive(chosen["output"] is not None)
        play.set_sensitive(chosen["output"] is not None)
        hear_outcomes.set_sensitive(chosen["output"] is not None)
        refresh_volume()
        recovery = Gtk.Label(label=C.SOUND_RECOVERY)
        recovery.set_line_wrap(True)
        recovery.set_xalign(0)
        recovery.set_max_width_chars(65)
        box.pack_start(recovery, False, False, 4)
        dialog.add_button(C.SOUND_CLOSE, Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda *args: dialog.destroy())
        dialog.connect("close", lambda *args: dialog.destroy())
        dialog.show_all()
        status.grab_focus()

    def _select(self, path):
        self.w.select_disk(path)
        self.w.continue_pick()

    def _owner(self, checked, generation):
        if generation != self.generation or self.w.screen not in {Screen.WHAT, Screen.OWNER}:
            return
        self.w.set_owner(checked)
        self.primary.set_sensitive(self.w.owner_ok)

    def _token(self, text, generation):
        if generation != self.generation or self.w.screen != Screen.CONFIRM:
            return
        self.w.set_confirm_input(text)
        self.primary.set_sensitive(self.w.token_ok)

    def _typing(self, text, generation):
        if generation != self.generation or self.w.screen != Screen.KEYBOARD:
            return
        self.w.set_typing_check(text)

    def update_status(self):
        if self.power_label and self.power_label.get_text() != self.w.power_text:
            self.power_label.set_text(self.w.power_text)
        if self.countdown_label:
            text = (
                f"{self.w.countdown_display} {C.COUNTDOWN_CAPTION}"
                if not self.w.erase_enabled
                else C.COUNTDOWN_READY
            )
            if self.countdown_label.get_text() != text:
                self.countdown_label.set_text(text)
            self.primary.set_sensitive(self.w.erase_enabled)
        if self.progress_label:
            text = self.w.progress_view.status_text
            # Integer percentage, minute elapsed, coarse ETA; no 100 ms
            # duplicate ATK text-change events or focus theft.
            if self.progress_label.get_text() != text:
                self.progress_label.set_text(text)
        if self.error_label:
            message = _error_text(self.w)
            changed = self.error_label.get_text() != message
            self.error_label.set_text(message)
            if changed and message:
                self.error_label.grab_focus()

    def tick(self):
        self.w.tick()
        if self.w.wants_shutdown or self.w.wants_new_session:
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
            Gdk.KEY_F5,
        }:
            return True
        self.held.add(key)
        if key in (Gdk.KEY_l, Gdk.KEY_L) and self.w.screen == Screen.METHOD:
            self.w.open_limits()
            self.render()
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.w.screen == Screen.LAST_CHANCE:
            # Enter must not activate a default Erase button while focus is
            # on the warning label. Match Tk: only the focused enabled control.
            focused = self.window.get_focus()
            erase = self.actions.get(C.BTN_ERASE)
            back = self.actions.get(C.BTN_BACK)
            if erase is not None and focused is erase and erase.get_sensitive():
                erase.clicked()
            elif back is not None and focused is back and back.get_sensitive():
                back.clicked()
            return True
        if key == Gdk.KEY_F5 and self.w.can_refresh:
            if self.w.screen == Screen.REFRESH_CONFIRM:
                self.w.confirm_refresh()
            else:
                self.w.open_refresh_confirm()
            self.render()
            return True
        if key == Gdk.KEY_Escape:
            if self.w.screen == Screen.WORKING:
                if self.w.stop_confirmation is not None:
                    self.w.keep_erasing()
                else:
                    self.w.request_stop()
                self.render()
                return True
            self.w.back()
            self.render()
            return True
        return False

    def _key_release(self, _window, event):
        self.held.discard(event.keyval)
        return False

    def _close(self, *_args):
        if self.w.screen == Screen.WORKING:
            self.w.request_stop()
            self.render()
        else:
            self.w.shutdown()
            if self.w.wants_shutdown or self.w.wants_new_session:
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
            if self.w.screen in {Screen.CHECKING, Screen.WORKING, Screen.STOPPING}:
                self.w.interface_failed()
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


def start_live_reader():
    """Start PulseAudio and Orca on the live USB. Returns the Orca Popen or None.

    Off the live USB (preview) nothing is started. Audio or reader failures
    never raise: the view stays usable without speech and the failure is logged.
    """
    from beamo_wipe.safety import running_on_live_usb, session_exec_env

    if not running_on_live_usb():
        return None
    session_env = session_exec_env()
    try:
        subprocess.run(
            ["/usr/bin/pulseaudio", "--start", "--exit-idle-time=60"],
            check=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            env=session_env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("accessible", "pulseaudio_failed", type(exc).__name__)
        except Exception:
            pass
    try:
        return subprocess.Popen(
            ["/usr/bin/orca"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            env=session_env,
        )
    except OSError as exc:
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("accessible", "orca_failed", type(exc).__name__)
        except Exception:
            pass
        return None


def stop_live_reader(reader) -> None:
    if reader is None:
        return
    if reader.poll() is None:
        reader.terminate()
        try:
            reader.wait(timeout=5)
        except subprocess.TimeoutExpired:
            reader.kill()
            reader.wait(timeout=5)


def run_accessible(wizard: Wizard, fullscreen: bool = False, reader=None) -> int:
    owned = start_live_reader() if reader is None else None
    try:
        return AccessibleWizard(wizard, fullscreen).run()
    finally:
        stop_live_reader(owned)


def _ensure_gtk_display() -> None:
    """Raise RuntimeError when no display is reachable for the splash.

    Same fail-safe idea as the Tk probe: a child process attempts the
    display connection, so a headless host becomes a catchable error and
    app.py keeps its existing graphical-failure path.
    """
    from beamo_wipe.safety import session_exec_env

    try:
        probe = subprocess.run(
            [sys.executable, "-c",
             "from gi.repository import Gtk as _G; "
             "_w = _G.Window(); _w.destroy()"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
            shell=False,
            env=session_exec_env(),
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("no accessible display for startup stages")
    if probe.returncode != 0:
        raise RuntimeError("no accessible display for startup stages")


def run_accessible_startup(build, *, fullscreen: bool = False,
                           stall_after_s: float | None = None) -> tuple:
    """Show startup stages in the screen-reader view while ``build()`` runs.

    Same worker discipline and return protocol as ``run_tk_startup``:
    ("wizard", wizard), ("failed", exc), or ("abandoned", None) on window
    close or Escape. Stage rows are plain labels; the status line takes
    keyboard focus and is selectable so a screen reader announces it.
    Raises RuntimeError (never aborts) when no display is reachable.
    """
    _ensure_gtk_display()
    from beamo_wipe.startup_stages import STALL_AFTER_S, StartupRun

    run = StartupRun(
        build,
        stall_after_s=STALL_AFTER_S if stall_after_s is None else stall_after_s,
    )
    outcome: list = []
    try:
        window = Gtk.Window(title=C.STARTING_TITLE)
    except Exception as exc:
        raise RuntimeError(f"no accessible display for startup stages: {exc}")
    window.set_name("beamo-accessible")
    window.set_default_size(640, 420)
    if fullscreen:
        window.fullscreen()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_border_width(24)
    window.add(box)
    rows = []
    for _i in range(3):
        status = Gtk.Label()
        title = Gtk.Label()
        title.get_style_context().add_class("screen-heading")
        hint = Gtk.Label()
        hint.set_line_wrap(True)
        hint.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        box.pack_start(status, False, False, 0)
        box.pack_start(title, False, False, 0)
        box.pack_start(hint, False, False, 6)
        rows.append((status, title, hint))
    stall = Gtk.Label()
    stall.set_line_wrap(True)
    box.pack_start(stall, False, False, 6)
    status_line = Gtk.Label(label="")
    status_line.set_can_focus(True)
    status_line.set_selectable(True)
    box.pack_start(status_line, False, False, 6)

    _STATUS_WORDS = {"pending": C.STARTUP_STATE_WAITING, "active": C.STARTUP_STATE_WORKING, "done": C.STARTUP_STATE_DONE}

    def render() -> None:
        snap = run.drain()
        for (status, title, hint), row in zip(rows, snap):
            status.set_text(_STATUS_WORDS[row["state"]])
            title.set_text(row["title"])
            hint.set_text(row["hint"])
        note = run.stalled_note()
        stall.set_text(note or "")
        active = [row for row in snap if row["state"] == "active"]
        if active:
            status_line.set_text(f"{active[0]['title']} — working.")

    def finish(result) -> bool:
        outcome.append(result)
        window.destroy()
        if Gtk.main_level():
            Gtk.main_quit()
        return False

    def close(*_args):
        if not outcome:
            outcome.append(("abandoned", None))
        window.destroy()
        if Gtk.main_level():
            Gtk.main_quit()
        return False

    def poll() -> bool:
        if outcome:
            return False
        render()
        result = run.poll()
        if result is None:
            return True
        # run.poll() applied the final report; announce it before closing.
        render()
        return finish(result)

    window.connect("delete-event", close)
    window.connect("key-press-event", lambda _w, event: close()
                   if event.keyval in (Gdk.KEY_Escape,) else None)
    window.show_all()
    status_line.grab_focus()
    render()
    run.start()
    GLib.timeout_add(100, poll)
    Gtk.main()
    if outcome:
        return outcome[0]
    return ("abandoned", None)
