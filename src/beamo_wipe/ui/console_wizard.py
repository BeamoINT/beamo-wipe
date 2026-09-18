# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard console fallback when X/Tk is unavailable. Same wizard, larger text."""

from __future__ import annotations

import curses
import select
import sys
import time
import unicodedata

from beamo_wipe import copy as C
from beamo_wipe import diagnostic_report as D
from beamo_wipe.outcomes import may_have_erased
from beamo_wipe.recovery import (
    format_recovery_text,
    recovery_for_blocked,
    recovery_for_diagnostic,
    recovery_for_empty,
    recovery_for_view,
    recovery_for_wizard_error,
)
from beamo_wipe import storage_limits as limits
from beamo_wipe import inventory
from beamo_wipe import keyboard as _keyboard
from beamo_wipe.keyboard import LAYOUT_ORDER
from beamo_wipe.lang import LANGUAGE_NAMES, LANGUAGE_ORDER


def _print_recovery(sections) -> None:
    print(format_recovery_text(sections, include_technical=True))


def _print_error_recovery(error, *, recovered: bool = False) -> None:
    sections = recovery_for_wizard_error(error)
    if sections is None:
        if error:
            print(f"{C.SEVERITY_ERROR}: {error}")
        return
    print(C.SEVERITY_ERROR)
    _print_recovery(sections)


def _error_recovery_text(error, *, recovered: bool = False) -> str:
    sections = (
        recovery_for_blocked(error, recovered=True)
        if recovered
        else recovery_for_wizard_error(error)
    )
    if sections is None:
        return f"{C.SEVERITY_ERROR}: {error}" if error else ""
    return (
        f"{C.SEVERITY_ERROR}\n"
        f"{format_recovery_text(sections, include_technical=True, compact=True)}"
    )


def _next_language(wizard: Wizard) -> str:
    try:
        index = LANGUAGE_ORDER.index(wizard.language)
    except ValueError:
        index = -1
    return LANGUAGE_ORDER[(index + 1) % len(LANGUAGE_ORDER)]
from beamo_wipe import identity as _identity
from beamo_wipe.methods import METHODS, MethodId
from beamo_wipe.models import Screen
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.wizard import Wizard, error_needs_support


ENTER_RELEASE_QUIET_S = 1.0
KEY_RESIZE = getattr(curses, "KEY_RESIZE", 410)


def _curses_opt(name: str, *args) -> None:
    """Best-effort curses control. Missing initscr or capabilities must not abort."""
    fn = getattr(curses, name, None)
    if fn is None:
        return
    try:
        fn(*args)
    except curses.error:
        pass


def _char_cols(ch: str) -> int:
    """Terminal columns for one Unicode character. Combining marks take none."""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1


def _display_cols(text: str) -> int:
    return sum(_char_cols(ch) for ch in text or "")


def _fit_cols(text: str, cols: int) -> str:
    """Prefix that fits in ``cols`` display columns. Last-resort curses clip."""
    if cols <= 0:
        return ""
    out: list[str] = []
    used = 0
    for ch in text or "":
        width = _char_cols(ch)
        if used + width > cols:
            break
        out.append(ch)
        used += width
    return "".join(out)


def _hard_break(token: str, cols: int) -> list[str]:
    lines: list[str] = []
    current = ""
    used = 0
    for ch in token:
        width = _char_cols(ch)
        if current and used + width > cols:
            lines.append(current)
            current = ch
            used = width
        else:
            current += ch
            used += width
    if current or not lines:
        lines.append(current)
    return lines


def _lines(text: str, width: int) -> list[str]:
    """Wrap including long identifiers. Never leaves a token unwrapped."""
    col = max(8, int(width) - 2)
    out: list[str] = []
    for para in (text or "").split("\n"):
        if para == "":
            out.append("")
            continue
        current = ""
        for word in para.split(" "):
            piece = word if current == "" else f" {word}"
            if _display_cols(current + piece) <= col:
                current += piece
                continue
            if current:
                out.append(current)
                current = ""
            if _display_cols(word) <= col:
                current = word
            else:
                out.extend(_hard_break(word, col))
        if current:
            out.append(current)
    return out or [""]


def _screen_title(wizard: Wizard) -> str:
    """Customer heading for the current screen. Never the Screen enum name."""
    screen = wizard.screen
    if screen == Screen.SPLASH:
        return C.APP_NAME
    if screen == Screen.KEYBOARD:
        return C.TITLE_KEYBOARD
    if screen == Screen.WHAT:
        return C.TITLE_WHAT
    if screen == Screen.OWNER:
        return C.TITLE_OWNER
    if screen == Screen.PICK:
        return C.TITLE_PICK
    if screen == Screen.PICK_EMPTY:
        return C.TITLE_EMPTY
    if screen == Screen.PICK_BLOCKED:
        return C.blocked_title(wizard.error, recovered=wizard._recovered)
    if screen == Screen.DISK_HELP:
        return C.DISK_HELP_TITLE
    if screen == Screen.CONFIRM:
        return C.TITLE_CONFIRM
    if screen == Screen.METHOD:
        return C.TITLE_METHOD
    if screen == Screen.LIMITS:
        return limits.TITLE
    if screen == Screen.REPORT_HELP:
        return C.REPORT_HELP_TITLE
    if screen == Screen.ADVANCED:
        return C.TITLE_ADVANCED
    if screen == Screen.LAST_CHANCE:
        return C.TITLE_LAST
    if screen == Screen.WORKING:
        return C.TITLE_WORKING
    if screen == Screen.CHECKING:
        return C.BUSY_CHECKING_TITLE
    if screen == Screen.STOPPING:
        return C.BUSY_STOPPING_TITLE
    if screen == Screen.REFRESHING:
        return C.BUSY_REFRESHING_TITLE
    if screen == Screen.REFRESH_CONFIRM:
        return C.TITLE_REFRESH
    if screen == Screen.SHUTDOWN_CONFIRM:
        return wizard.exit_confirmation_title
    if screen == Screen.DIAGNOSTIC:
        return D.report_title(wizard.startup_error_code)
    if screen == Screen.DONE:
        return wizard.result_view.message or C.TITLE_DONE_OK
    return C.APP_NAME


def _chrome_lines(wizard: Wizard, width: int) -> list[str]:
    """One-line brand plus title when they fit. Preview stays visible."""
    title = _screen_title(wizard)
    if title and title != C.APP_NAME:
        combined = f"{C.APP_NAME} — {title}"
        lines = _lines(combined, width) if _display_cols(combined) <= max(8, width - 2) else (
            _lines(C.APP_NAME, width) + _lines(title, width)
        )
    else:
        lines = _lines(C.APP_NAME, width)
    if wizard.preview:
        lines.extend(_lines(C.PREVIEW_BANNER, width))
    return lines


def _identity_field_lines(view, width: int, *, include_path: bool = False, indent: str = "") -> list[str]:
    """Wrapped identity fields. Capacity, type, and connection share a line."""
    lines: list[str] = []
    if view.title:
        lines.extend(_lines(f"{indent}{view.title}", width))
    meta = "  ".join(part for part in (view.capacity, view.kind_chip, view.connection) if part)
    if meta:
        lines.extend(_lines(f"{indent}{meta}", width))
    ident = view.id_value
    lines.extend(_lines(f"{indent}{view.id_label}: {ident}", width))
    for note in view.notes:
        lines.extend(_lines(f"{indent}{note}", width))
    if include_path and view.system_path:
        lines.extend(_lines(f"{indent}{_identity.SYSTEM_PATH_NOTE}: {view.system_path}", width))
    return lines


def _nested_lines(wizard: Wizard, disk, width: int, indent: str = "  ") -> list[str]:
    nested = inventory.card_nesting_text(wizard.nested_components(disk))
    if not nested:
        return []
    lines: list[str] = []
    for line in nested.split("\n"):
        lines.extend(_lines(f"{indent}{line}", width))
    return lines


def _support_identity_text(wizard: Wizard) -> str:
    ident = wizard.support_identity
    if ident is None:
        return ""
    return C.support_identity_text(ident)


def _pick_blocks(wizard: Wizard, width: int) -> list[tuple[object, list[str]]]:
    """Wrapped identity blocks. Protected boot is listed first and is not selectable."""
    blocks: list[tuple[object, list[str]]] = []
    if wizard.protected_boot:
        view = wizard.disk_view(wizard.protected_boot)
        block = _lines(C.CON_PROTECTED_BOOT_MEDIA, width)
        block.extend(_identity_field_lines(view, width, indent="  "))
        block.extend(_nested_lines(wizard, wizard.protected_boot, width))
        blocks.append((None, block))
    for disk in sorted(wizard.selectable, key=lambda d: d.path):
        view = wizard.disk_view(disk)
        star = ">" if wizard.selected and disk.path == wizard.selected.path else " "
        block = _lines(f"{star} {view.title}", width)
        meta = "  ".join(part for part in (view.capacity, view.kind_chip, view.connection) if part)
        if meta:
            block.extend(_lines(f"  {meta}", width))
        block.extend(_lines(f"  {view.id_label}: {view.id_value}", width))
        for note in view.notes:
            block.extend(_lines("  " + note, width))
        block.extend(_nested_lines(wizard, disk, width))
        blocks.append((disk, block))
    return blocks


def _paint_paged(stdscr, y: int, lines: list[str], offset: int, y_max: int, width: int) -> int:
    """Page wrapped body lines. Hints never overwrite the only visible rows."""
    if y >= y_max:
        return offset
    avail = max(1, y_max - y)
    if len(lines) <= avail:
        for i, line in enumerate(lines):
            if y + i >= y_max:
                break
            _add(stdscr, y + i, 0, line)
        return 0
    page = max(1, avail - 2)
    offset = min(max(0, offset), max(0, len(lines) - page))
    need_above = offset > 0
    need_below = offset + page < len(lines)
    inner = y_max - (1 if need_below else 0)
    if need_above:
        y = _wrap(stdscr, y, C.CON_MORE_ABOVE, width, inner)
    for line in lines[offset:]:
        if y >= inner:
            break
        _add(stdscr, y, 0, line)
        y += 1
    if need_below:
        _add(stdscr, y_max - 1, 0, C.CON_MORE_BELOW)
    return offset


def _keep_selected_visible(
    blocks, pick_offset: int, page: int, selected_path: str | None, *, follow: bool = True
) -> tuple[int, int]:
    """Keep the selected disk reachable. Tall identity can be paged through."""
    starts: list[int] = []
    total = 0
    for _disk, block in blocks:
        starts.append(total)
        total += len(block)
    if follow and selected_path:
        try:
            idx = next(
                i for i, (d, _) in enumerate(blocks) if d is not None and d.path == selected_path
            )
            start = starts[idx]
            end = start + len(blocks[idx][1])
            height = end - start
            if height >= page:
                pick_offset = min(max(pick_offset, start), max(start, end - page))
            elif start < pick_offset:
                pick_offset = start
            elif end > pick_offset + page:
                pick_offset = max(0, end - page)
        except StopIteration:
            pass
    pick_offset = min(max(0, pick_offset), max(0, total - page))
    return pick_offset, total


def _chrome_extra(wizard: Wizard) -> list[str]:
    bits = []
    if wizard.can_open_diagnostic:
        bits.append(C.CON_DIAGNOSTIC)
    if wizard.can_open_report_help:
        bits.append(C.CON_REPORT_HELP)
    if wizard.can_refresh and wizard.screen not in {Screen.REPORT_HELP, Screen.REFRESH_CONFIRM}:
        bits.append(C.CON_REFRESH.format(note=C.REFRESH_UTILITY_NOTE))
    if wizard.can_open_keyboard and wizard.screen != Screen.KEYBOARD:
        bits.append(C.CON_KEYBOARD)
    return bits


def _sounds_footer(wizard: Wizard, hear: str) -> str:
    state = C.CON_SOUND_ON if wizard.sounds_enabled else C.CON_SOUND_OFF
    return f"{state}  {hear}"


def _primary_footer(wizard: Wizard, inventory_open: bool) -> list[str]:
    if inventory_open:
        return [C.CON_READ_ONLY]
    screen = wizard.screen
    if screen == Screen.SPLASH:
        return [C.CON_PRESS_ANY_KEY]
    if screen == Screen.KEYBOARD:
        return [
            C.CON_KEYBOARD_FOOTER,
            C.CON_INPUT_PREFIX + wizard.typing_check,
        ]
    if screen == Screen.WHAT:
        return [C.CON_WHAT_FOOTER, C.CON_READ_MORE]
    if screen == Screen.OWNER:
        return [C.CON_OWNER_FOOTER]
    if screen == Screen.PICK:
        return [C.CON_PICK_NAV, C.CON_DISK_HELP.format(label=C.DISK_HELP_BUTTON)]
    if screen == Screen.PICK_EMPTY:
        return [C.CON_SHUTDOWN_BACK]
    if screen == Screen.PICK_BLOCKED:
        return [C.CON_SHUTDOWN_BACK]
    if screen == Screen.CONFIRM:
        return [
            C.CON_CONFIRM_FOOTER.format(note=C.REFRESH_UTILITY_NOTE),
            C.CON_INPUT_PREFIX + wizard.confirm_input,
        ]
    if screen == Screen.METHOD:
        return [C.CON_METHOD_FOOTER, C.CON_READ_MORE]
    if screen == Screen.DISK_HELP:
        return [C.CON_DISK_HELP_STOP.format(label=C.DISK_HELP_STOP)]
    if screen == Screen.LIMITS:
        return [C.CON_READ_BACK]
    if screen == Screen.REPORT_HELP:
        return [C.CON_REPORT_HELP_FOOTER]
    if screen == Screen.ADVANCED:
        return [C.CON_READ_BACK]
    if screen == Screen.LAST_CHANCE:
        return [
            C.CON_LAST_WAIT.format(seconds=wizard.countdown_display)
            if not wizard.erase_enabled else C.CON_LAST_ERASE,
            C.CON_BACK_READ_MORE,
        ]
    if screen == Screen.WORKING:
        lines = ([C.CON_WORKING_STOP]
                 if wizard.stop_confirmation is not None else [C.CON_WORKING_IDLE])
        lines.append(_sounds_footer(wizard, C.CON_SOUND_HEAR))
        if wizard.sound_message:
            lines.append(wizard.sound_message)
        return lines
    if screen == Screen.CHECKING:
        return [C.CON_CHECKING]
    if screen == Screen.STOPPING:
        return [C.CON_STOPPING]
    if screen == Screen.REFRESHING:
        return [C.CON_REFRESHING]
    if screen == Screen.REFRESH_CONFIRM:
        return [
            C.CON_REFRESH_ENTER,
            C.CON_REFRESH_ESC,
        ]
    if screen == Screen.SHUTDOWN_CONFIRM:
        return [
            C.CON_SHUTDOWN_KEEP,
            C.CON_SHUTDOWN_DISCARD.format(action=wizard.exit_confirmation_discard),
        ]
    if screen == Screen.DIAGNOSTIC:
        action = C.CON_DIAG_SAVE if wizard._diagnostic_baseline else C.CON_DIAG_PREPARE
        return [C.CON_DIAG_LINE.format(action=action)]
    if screen == Screen.DONE:
        report = wizard.report_view
        if wizard.preview:
            action = C.CON_DONE_PREVIEW
        elif report.can_save:
            action = C.CON_DONE_SAVE
        elif report.can_retry_evidence:
            action = C.CON_DONE_RETRY
        else:
            action = C.CON_DONE_SHUTDOWN
        if wizard.can_erase_another:
            lines = [C.CON_DONE_READ, C.ANOTHER_HINT,
                     C.CON_DONE_ANOTHER.format(action=action)]
        else:
            lines = [C.CON_DONE_READ, action]
        lines.append(_sounds_footer(wizard, C.CON_SOUND_HEAR_AGAIN))
        if wizard.sound_message:
            lines.append(wizard.sound_message)
        return lines
    return [C.CON_BACK]


def _assist_footer(wizard: Wizard, inventory_open: bool) -> list[str]:
    """Inventory and read-more keys. Shown when body space remains."""
    if inventory_open:
        return []
    screen = wizard.screen
    if screen in (Screen.PICK, Screen.PICK_EMPTY):
        lines = []
        if wizard.other_devices:
            lines.append(C.CON_OTHER_DEVICES)
        if wizard.protected_boot:
            lines.append(C.CON_BOOT_IDENTITY.format(line=C.CON_PROTECTED_BOOT_MEDIA))
        if screen == Screen.PICK and len(wizard.selectable) > 1:
            lines.append(C.CON_COMPARE)
        return lines
    return []


def _footer_lines(wizard: Wizard, inventory_open: bool, width: int, height: int) -> list[str]:
    """Pin next-step actions. Assist and extra chrome drop before actions."""
    actions: list[str] = []
    for line in _primary_footer(wizard, inventory_open):
        actions.extend(_lines(line, width) or [""])
    assist: list[str] = []
    for line in _assist_footer(wizard, inventory_open):
        assist.extend(_lines(line, width) or [""])
    extra: list[str] = []
    if not inventory_open and wizard.screen not in {
        Screen.WORKING,
        Screen.CHECKING,
        Screen.STOPPING,
        Screen.REFRESHING,
        Screen.REFRESH_CONFIRM,
        Screen.SHUTDOWN_CONFIRM,
        Screen.CONFIRM,
        Screen.KEYBOARD,
    }:
        joined = "    ".join(_chrome_extra(wizard))
        if joined:
            extra.extend(_lines(joined, width))
    reserved_body = 2
    if len(actions) > height - 1:
        actions = actions[-(height - 1):]
    room = max(0, height - reserved_body - len(actions))
    assist_shown = assist[:room]
    room -= len(assist_shown)
    extra_shown = extra[:room]
    return extra_shown + assist_shown + actions


def _paint_footer(stdscr, lines: list[str]) -> int:
    h, w = stdscr.getmaxyx()
    if h < 2 or not lines:
        return 0
    shown = lines[: min(len(lines), h - 1)]
    start = h - len(shown)
    for i, line in enumerate(shown):
        _add(stdscr, start + i, 0, line)
    return len(shown)



def run_console(wizard: Wizard) -> int:
    try:
        return curses.wrapper(lambda stdscr: _loop(stdscr, wizard))
    except (curses.error, KeyboardInterrupt):
        return _plain_loop(wizard)


class _InventoryRefreshed(Exception):
    pass


def _request_or_confirm_refresh(wizard: Wizard) -> None:
    if wizard.screen == Screen.REFRESH_CONFIRM:
        wizard.confirm_refresh()
    else:
        wizard.open_refresh_confirm()


def _emit(text: str, width: int = 76) -> None:
    for line in _lines(text, width):
        print(line)


def _print_view(view, width: int = 76, *, include_path: bool = False) -> None:
    for line in _identity_field_lines(view, width, include_path=include_path):
        print(line)


def _print_operation_identity(wizard, width: int = 76) -> None:
    """Request-bound disk + method for operation screens. Never substituted."""
    disk = wizard.operation_disk
    if disk is not None:
        _print_view(wizard.disk_view(disk), width)
    elif wizard.operation_identity_text:
        _emit(wizard.operation_identity_text, width)
    _emit(wizard.operation_method_text, width)


def _answer(wizard: Wizard, prompt: str) -> str:
    if wizard.can_refresh:
        if wizard.screen == Screen.REFRESH_CONFIRM:
            print(C.CON_REFRESH_HINT_CONFIRM)
        else:
            print(C.CON_REFRESH_HINT)
    if wizard.can_open_diagnostic:
        print(C.CON_DIAGNOSTIC_HINT)
    if wizard.can_open_report_help:
        print(C.CON_REPORT_HINT)
    answer = input(prompt)
    if wizard.can_open_report_help and answer.strip().upper() == "REPORT":
        wizard.open_report_help()
        raise _InventoryRefreshed
    if wizard.can_open_diagnostic and answer.strip().upper() == "DIAGNOSTIC":
        wizard.open_diagnostic()
        raise _InventoryRefreshed
    if wizard.can_refresh and answer.strip().upper() == "CHECK DISKS AGAIN":
        _request_or_confirm_refresh(wizard)
        raise _InventoryRefreshed
    if wizard.screen == Screen.REFRESH_CONFIRM and answer.strip().upper() == "BACK":
        wizard.back()
        raise _InventoryRefreshed
    return answer


def _report_headline(wizard: Wizard, report) -> str:
    """Report copy state in words. Saved copies say Saved; report and
    evidence problems stay warnings, never errors: report transport must
    not reuse the red erase-failure severity."""
    if wizard.preview:
        return C.REPORT_PREVIEW
    if report.tone == "ok":
        return f"{C.SEVERITY_SAVED}: {report.headline}"
    if report.tone == "warn":
        return f"{C.SEVERITY_WARNING}: {report.headline}"
    return report.headline


def _plain_loop(wizard: Wizard) -> int:
    """Last-resort TTY with input(). Still requires confirms; never auto-wipes."""
    while True:
        try:
            return _plain_loop_body(wizard)
        except _InventoryRefreshed:
            continue
        except EOFError:
            if wizard.screen == Screen.WORKING:
                wizard.cancel_wipe(origin="system")
            wizard.shutdown()
            if not wizard.wants_shutdown:
                if wizard.screen == Screen.SHUTDOWN_CONFIRM:
                    print(wizard.exit_confirmation_title)
                    print(wizard.exit_confirmation_loss)
                    print(C.MEDIA_STEPS_TITLE)
                    print(wizard.exit_media_steps)
                print(C.CON_INPUT_UNAVAILABLE)
                return 3
            return 0
        except KeyboardInterrupt:
            # Ctrl-C opens consent while polling continues. Terminal loss
            # above still requests a system stop rather than abandoning nwipe.
            if wizard.screen == Screen.WORKING:
                try:
                    wizard.request_stop()
                except Exception:
                    pass
                if wizard.wants_shutdown or wizard.wants_new_session:
                    return 0
                continue
            if wizard.screen == Screen.SHUTDOWN_CONFIRM:
                wizard.keep_report_session()
            else:
                wizard.shutdown()
            if wizard.wants_shutdown or wizard.wants_new_session:
                return 0


def _plain_loop_body(wizard: Wizard) -> int:
    last_working = None
    while not wizard.wants_shutdown and not wizard.wants_new_session:
        wizard.tick()
        screen = wizard.screen
        if screen != Screen.WORKING:
            print("\n" + "=" * 60)
            print(C.APP_NAME)
            print(_screen_title(wizard))
            last_working = None
            if wizard.preview:
                print(C.PREVIEW_BANNER)
            print("=" * 60)
        if screen == Screen.REFRESH_CONFIRM:
            print(_screen_title(wizard))
            _emit(C.REFRESH_LEAD)
            _answer(wizard, C.CON_REFRESH_PROMPT)
            continue
        if screen == Screen.SHUTDOWN_CONFIRM:
            print(_screen_title(wizard))
            _emit(wizard.exit_confirmation_loss)
            print(wizard.report_recovery_warning)
            print(C.MEDIA_STEPS_TITLE)
            print(wizard.exit_media_steps)
            generation = wizard.shutdown_generation
            answer = input(
                C.CON_SHUTDOWN_TYPE.format(word=wizard.exit_confirmation_discard.upper())
            )
            if answer == wizard.exit_confirmation_discard.upper():
                wizard.confirm_shutdown_without_saving(generation)
            else:
                wizard.keep_report_session()
            continue
        if screen == Screen.DIAGNOSTIC:
            print(D.report_title(wizard.startup_error_code))
            _print_recovery(
                recovery_for_diagnostic(
                    wizard.startup_error_code,
                    wizard.diagnostic_message,
                    wizard.diagnostic_step,
                )
            )
            ident = _support_identity_text(wizard)
            if ident:
                print(ident)
            action = "SAVE" if wizard._diagnostic_baseline else "PREPARE"
            answer = input(C.CON_DIAG_TYPE.format(action=action)).strip().upper()
            if answer == action:
                wizard.diagnostic_action()
            elif answer == "BACK":
                wizard.close_diagnostic()
            elif answer == "SHUTDOWN":
                wizard.shutdown()
            continue
        if screen == Screen.SPLASH:
            print(C.SPLASH_TAGLINE)
            _answer(wizard, C.CON_PRESS_ENTER)
            wizard.skip_splash()
            continue
        if screen == Screen.KEYBOARD:
            print(C.TITLE_KEYBOARD)
            print(C.KEYBOARD_LEAD)
            print(C.KEYBOARD_LIMITS)
            print(_keyboard.CONSOLE_DEAD_KEYS)
            for i, layout_id in enumerate(LAYOUT_ORDER, 1):
                layout_spec = _keyboard.LAYOUTS[layout_id]
                mark = ">" if wizard.keyboard_layout == layout_id else " "
                print(f"{mark} {i} {layout_spec.title}")
                print(layout_spec.note)
            print(C.TITLE_LANGUAGE)
            print(C.LANGUAGE_LEAD)
            for code in LANGUAGE_ORDER:
                mark = ">" if wizard.language == code else " "
                print(f"{mark} {LANGUAGE_NAMES[code]}")
            if wizard.error:
                _print_error_recovery(wizard.error)
                if error_needs_support(wizard.error):
                    print(C.support_text())
            elif wizard.keyboard_message:
                print(f"{C.SEVERITY_WARNING}: {wizard.keyboard_message}")
            print(C.KEYBOARD_CHECK_LABEL)
            typed = input(C.CON_INPUT_PREFIX)
            key = typed.strip()
            keyboard_mapping = {"1": "us", "2": "fr", "3": "de"}
            if key in keyboard_mapping:
                wizard.set_keyboard_layout(keyboard_mapping[key])
            elif key.upper() == "K":
                pass
            elif key.upper() == "LANG":
                wizard.set_language(_next_language(wizard))
            elif key == "":
                wizard.accept_keyboard()
            else:
                wizard.set_typing_check(typed)
            continue
        if screen == Screen.WHAT:
            for b in C.WHAT_BULLETS:
                print(" -", b)
            print(C.REPORT_MEDIA_WHAT)
            print(C.POWER_REMINDER)
            print(C.POWER_BLANKING)
            print(C.POWER_EVENTS)
            print(wizard.power_text)
            ident = _support_identity_text(wizard)
            if ident:
                print(ident)
            _answer(wizard, C.CON_PRESS_ENTER_CONTINUE)
            wizard.accept_what()
            continue
        if screen == Screen.OWNER:
            print(C.OWNER_CHECKBOX)
            ans = _answer(wizard, C.CON_OWNER_PROMPT).strip()
            wizard.set_owner(ans.upper() == "YES")
            if wizard.owner_ok:
                wizard.continue_owner()
            continue
        if screen == Screen.PICK_BLOCKED:
            print(C.blocked_title(wizard.error, recovered=wizard._recovered))
            print(f"{C.SEVERITY_ERROR}")
            _print_recovery(
                recovery_for_blocked(wizard.error, recovered=wizard._recovered)
            )
            if error_needs_support(wizard.error):
                print(C.support_text())
            ident = _support_identity_text(wizard)
            if ident:
                print(ident)
            _answer(wizard, C.CON_PRESS_ENTER_SHUTDOWN)
            wizard.shutdown()
            continue
        if screen == Screen.PICK_EMPTY:
            print(C.TITLE_EMPTY)
            _print_recovery(recovery_for_empty())
            print(C.support_text())
            ident = _support_identity_text(wizard)
            if ident:
                print(ident)
            if wizard.protected_boot_text:
                print(wizard.protected_boot_text)
            if wizard.other_devices:
                print(inventory.TITLE)
                print(inventory.full_text(wizard.other_devices))
            _answer(wizard, C.CON_PRESS_ENTER_SHUTDOWN)
            wizard.shutdown()
            continue
        if screen == Screen.PICK:
            if wizard.protected_boot_text:
                print(wizard.protected_boot_text)
            if len(wizard.selectable) > 1:
                print(inventory.COMPARE_TITLE)
                print(inventory.comparison_text(wizard.selectable, peers=wizard.listed_disks))
            if wizard.other_devices:
                print(inventory.TITLE)
                print(inventory.full_text(wizard.other_devices))
            print(C.CON_ELIGIBLE_DISKS)
            if same_size_conflict(wizard.listed_disks):
                print(f"{C.SEVERITY_WARNING}: {C.SAME_SIZE_HINT}")
            if wizard.report_wanted:
                print(C.REPORT_MEDIA_WANTED)
            numbered = sorted(wizard.selectable, key=lambda d: d.path)
            for i, disk in enumerate(numbered, 1):
                view = wizard.disk_view(disk)
                _emit(f"[{i}] {view.title}")
                for part in (view.capacity, view.kind_chip, view.connection):
                    if part:
                        _emit(f"    {part}")
                _emit(f"    {view.id_label}: {view.id_value}")
                for note in view.notes:
                    _emit("    " + note)
                nested = inventory.card_nesting_text(wizard.nested_components(disk))
                if nested:
                    for line in nested.split("\n"):
                        _emit("    " + line)
            print(C.CON_DISK_HELP.format(label=C.DISK_HELP_BUTTON))
            choice = _answer(wizard, C.CON_PICK_PROMPT).strip()
            if choice.upper() == "U":
                wizard.open_disk_help()
                continue
            try:
                idx = int(choice) - 1
                if idx < 0:
                    raise IndexError
                wizard.select_disk(numbered[idx].path)
                wizard.continue_pick()
            except (ValueError, IndexError):
                pass
            continue
        if screen == Screen.DISK_HELP:
            print(C.DISK_HELP_TITLE)
            print(C.DISK_HELP_TEXT)
            answer = _answer(wizard, C.CON_DISK_HELP_PROMPT.format(label=C.DISK_HELP_STOP))
            if answer.strip().upper() == "BACK":
                wizard.back()
            elif answer.strip().upper() == "STOP":
                wizard.shutdown()
            continue
        if screen == Screen.CONFIRM:
            disk = wizard.selected
            confirm_spec = wizard.confirm
            if disk:
                _print_view(wizard.disk_view(disk))
            _emit(f"{C.SEVERITY_WARNING}: {wizard.warning_text()}")
            print(confirm_spec.prompt if confirm_spec else "")
            print(C.CONFIRM_KEYBOARD_LINE.format(
                layout=_keyboard.LAYOUTS[wizard.keyboard_layout].title,
                language=LANGUAGE_NAMES[wizard.language],
            ))
            typed = _answer(wizard, C.CON_INPUT_PREFIX)
            wizard.set_confirm_input(typed)
            if wizard.token_ok:
                wizard.continue_confirm()
            continue
        if screen == Screen.METHOD:
            print(C.TITLE_METHOD)
            if wizard.selected:
                print(C.SELECTED_DISK)
                _print_view(wizard.disk_view(wizard.selected))
                print(f"{_identity.SYSTEM_PATH_NOTE}: {wizard.selected.path}")
            print(f"{C.SEVERITY_LIMITS}: {wizard.storage_notice}")
            print(limits.BUTTON)
            for method, spec in METHODS.items():
                card = C.METHOD_CARDS[method]
                # One logical line so overwrite + verification stay a contiguous description.
                # The TTY wraps at its own width; pre-fill would split spec.description.
                print(
                    f"{card['key']} {spec.title}: "
                    f"{spec.overwrite_description} {spec.verification_description}"
                )
            choice = _answer(wizard, C.CON_METHOD_PROMPT).strip()
            if choice.lower() == "a":
                wizard.open_advanced()
                continue
            if choice.lower() == "l":
                wizard.open_limits()
                continue
            mapping = {"1": MethodId.EVERYDAY, "2": MethodId.EXTRA, "3": MethodId.QUICK_ZERO}
            if not choice:
                wizard.continue_method()
                continue
            if choice not in mapping:
                continue
            wizard.set_method(mapping[choice])
            wizard.continue_method()
            continue
        if screen in {Screen.CHECKING, Screen.STOPPING, Screen.REFRESHING}:
            titles = {
                Screen.CHECKING: C.BUSY_CHECKING_TITLE,
                Screen.STOPPING: C.BUSY_STOPPING_TITLE,
                Screen.REFRESHING: C.BUSY_REFRESHING_TITLE,
            }
            messages = {
                Screen.CHECKING: C.BUSY_CHECKING_MESSAGE,
                Screen.STOPPING: C.STOPPING_TEXT,
                Screen.REFRESHING: C.BUSY_REFRESHING_MESSAGE,
            }
            print(titles[screen])
            if screen != Screen.REFRESHING:
                print(C.POWER_KEEP)
                print(wizard.power_text)
            if screen == Screen.STOPPING:
                _print_operation_identity(wizard)
            elif wizard.selected is not None:
                _print_view(wizard.disk_view(wizard.selected))
            _emit(messages[screen])
            time.sleep(0.2)
            continue
        if screen == Screen.LAST_CHANCE:
            print(C.LAST_LEAD)
            if wizard.selected:
                _print_view(wizard.disk_view(wizard.selected))
            print(C.POWER_KEEP)
            print(wizard.power_text)
            print(wizard.prepare_text())
            print(wizard.operation_summary)
            print(f"{C.SEVERITY_WARNING}: {wizard.erase_label()}")
            print(wizard.method_summary)
            if wizard.error:
                _print_error_recovery(wizard.error)
                if error_needs_support(wizard.error):
                    print(C.support_text())
            ident = _support_identity_text(wizard)
            if ident:
                print(ident)
            while wizard.countdown_left > 0:
                wizard.tick()
                print(C.CON_COUNTDOWN.format(seconds=wizard.countdown_display))
                time.sleep(0.4)
            ans = _answer(wizard, C.CON_ERASE_PROMPT).strip()
            if ans.upper() == "ERASE":
                wizard.confirm_erase()
            else:
                wizard.back()
            continue
        if screen == Screen.WORKING:
            status = (wizard.progress_view.status_text, wizard.error, wizard.evidence_warning, C.POWER_KEEP, wizard.power_text, wizard.stop_confirmation, wizard.sound_toggle_text, wizard.sound_message)
            if status != last_working:
                print(status[0])
                _print_operation_identity(wizard)
                if wizard.stop_confirmation is not None:
                    print(f"{C.SEVERITY_WARNING}: {C.STOP_TITLE} {C.STOP_LEAD}")
                    print(C.CON_STOP_CONFIRM)
                else:
                    print(f"{C.SEVERITY_WARNING}: {C.STOP_WARNING}")
                    print(C.CON_STOP_REVIEW)
                print(wizard.sound_toggle_text)
                print(C.CON_SOUND_WORDS_WORKING)
                if wizard.sound_message:
                    print(wizard.sound_message)

                if wizard.error:
                    _print_error_recovery(wizard.error)
                    if error_needs_support(wizard.error):
                        print(C.support_text())
                if wizard.evidence_warning:
                    print(f"{C.SEVERITY_WARNING}: {wizard.evidence_warning}")
                for notice in (C.POWER_KEEP, wizard.power_text):
                    if notice:
                        print(notice)
                last_working = status
            # Poll canonical TTY input without blocking progress updates.
            # This remains usable when the hardened kiosk disables INTR.
            try:
                ready, _w, _x = select.select([sys.stdin], [], [], 0.3)
                if ready:
                    typed = sys.stdin.readline()
                    if typed == "":
                        raise EOFError
                    command = typed.strip().casefold()
                    if command == "sounds":
                        wizard.toggle_sounds()
                    elif command == "hear":
                        wizard.hear_both_sounds()
                    elif wizard.stop_confirmation is not None:
                        if command == "stop":
                            print(C.CON_STOPPING_NOW + C.STOPPING_TEXT)
                            wizard.confirm_stop(wizard.stop_confirmation)
                        elif command != "cancel":
                            wizard.keep_erasing()
                    elif command == "cancel":
                        wizard.request_stop()
            except InterruptedError:
                time.sleep(0.3)
            except (OSError, ValueError) as exc:
                # A closed/failed terminal cannot accept the advertised
                # CANCEL command. Use the same stop-and-report recovery as
                # EOF instead of silently polling an inaccessible erase.
                raise EOFError from exc
            continue
        if screen == Screen.DONE:
            wizard.maybe_play_outcome_sound()
            print(wizard.method_result)
            print(wizard.elapsed_text)
            report = wizard.report_view
            print(wizard.method_summary)
            if wizard.selected:
                _print_view(wizard.disk_view(wizard.selected))
            sections = recovery_for_view(wizard.result_view)
            if sections:
                _print_recovery(sections)
            else:
                print(wizard.result_view.next_step)
            if wizard.done_support_needed:
                print(C.support_text())
            ident = _support_identity_text(wizard)
            if ident:
                print(ident)
            if may_have_erased(wizard.result_view.code):
                print(C.POST_ERASE_BOOT)
            print(wizard.sound_toggle_text)
            print(C.CON_SOUND_WORDS_DONE)
            if wizard.sound_message:
                print(wizard.sound_message)
            for alert in wizard.check_alerts:
                print(f"{C.SEVERITY_WARNING}: {alert}")
            print(C.REPORT_STATUS_TITLE)
            print(_report_headline(wizard, report))
            print(C.REPORT_STATUS_NOTICE)
            if report.evidence_error:
                print(f"{C.SEVERITY_WARNING}: {wizard.evidence_warning}")
            if wizard.preview:
                ans = _answer(wizard, C.CON_RUN_AGAIN).strip().lower()
                if ans in ("q", "quit", "close"):
                    wizard.shutdown()
                elif ans == "sounds":
                    wizard.toggle_sounds()
                elif ans == "hear":
                    wizard.hear_outcome_sound()
                else:
                    wizard.reset_for_preview()
            else:
                if not report.evidence_error:
                    print(C.report_aftercare(can_save=report.can_save, status=report.status, message=report.message))
                if report.can_retry_evidence:
                    prompt = C.CON_DONE_RETRY_PROMPT
                elif report.can_save:
                    prompt = C.CON_DONE_SAVE_PROMPT
                else:
                    prompt = C.CON_DONE_SHUTDOWN_PROMPT
                if wizard.can_erase_another:
                    print(C.ANOTHER_HINT)
                    prompt += C.CON_DONE_ANOTHER_PROMPT
                action = _answer(wizard, prompt).strip().upper()
                if action == "SOUNDS":
                    wizard.toggle_sounds()
                elif action == "HEAR":
                    wizard.hear_outcome_sound()
                elif action == "RETRY" and report.can_retry_evidence:
                    wizard.retry_evidence_save()
                elif action == "SAVE" and report.can_save:
                    wizard.save_report_to_usb()
                elif action == "ANOTHER":
                    wizard.erase_another_disk()
                elif action == "SHUTDOWN":
                    wizard.shutdown()
            continue
        if screen == Screen.REPORT_HELP:
            print(C.REPORT_HELP_TITLE)
            print(wizard.report_recovery_warning)
            for paragraph in C.REPORT_HELP_SECTIONS:
                heading, _, body = paragraph.partition("\n")
                _emit(heading)
                if body:
                    _emit(body)
                _answer(wizard, C.CON_MORE_ENTER)
            print(f"{C.REPORT_WANTED}: {C.CON_YES if wizard.report_wanted else C.CON_NO}")
            print(f"{C.REPORT_SHARE_REDACTED}: {C.CON_YES if wizard.report_share_redacted else C.CON_NO}")
            action = _answer(wizard, C.CON_REPORT_CHOICE).strip().upper()
            if action in {"YES", "NO"}:
                wizard.set_report_wanted(action == "YES")
                if wizard.report_recovery_warning:
                    print(wizard.report_recovery_warning)
                wizard.close_report_help()
            elif action == "SHARE":
                wizard.set_report_share_redacted(not wizard.report_share_redacted)
            elif action == "BACK":
                wizard.close_report_help()
            continue
        if screen == Screen.LIMITS:
            print(limits.TITLE)
            for title, body in limits.SECTIONS:
                print(title)
                _emit(body)
                _answer(wizard, C.CON_MORE_ENTER)
            wizard.close_limits()
            continue
        if screen == Screen.ADVANCED:
            print(C.ADVANCED_LEAD)
            _emit(C.ADVANCED_LOG_NOTE)
            _answer(wizard, C.CON_PRESS_ENTER_BACK)
            wizard.close_advanced()
            continue
    return 0


def _loop(stdscr, wizard: Wizard) -> int:
    _curses_opt("curs_set", 0)
    stdscr.keypad(True)
    stdscr.nodelay(True)
    _curses_opt("use_default_colors")
    enter_held = False
    enter_quiet_since = None
    limits_offset = 0
    inventory_open = False
    comparison_open = False
    inventory_boot = False
    inventory_offset = 0
    pick_offset = 0
    pick_follow = True
    pick_page = 1
    while not wizard.wants_shutdown and not wizard.wants_new_session:
        wizard.tick()
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        h, w = max(2, h), max(20, w)
        footer = _footer_lines(wizard, inventory_open, w, h)
        y_max = max(1, h - len(footer))
        chrome = _chrome_lines(wizard, w)
        y = 0
        for i, line in enumerate(chrome):
            if y >= y_max:
                break
            _add(stdscr, y, 0, line, curses.A_BOLD if i == 0 else curses.A_NORMAL)
            y += 1
        if y + 2 < y_max:
            y += 1
        if inventory_open:
            if comparison_open:
                overlay_title = inventory.COMPARE_TITLE
                overlay_text = inventory.comparison_text(
                    wizard.selectable, peers=wizard.listed_disks
                )
            elif inventory_boot:
                overlay_title = C.CON_PROTECTED_BOOT_MEDIA
                overlay_text = wizard.protected_boot_text
            else:
                overlay_title = inventory.TITLE
                overlay_text = inventory.full_text(wizard.other_devices)
            _add(stdscr, y, 0, overlay_title)
            y += 1
            lines = [line for paragraph in overlay_text.split("\n")
                     for line in _lines(paragraph, w)]
            page_size = max(1, y_max - y)
            inventory_offset = min(inventory_offset, max(0, len(lines) - page_size))
            for line in lines[inventory_offset:inventory_offset + page_size]:
                if y >= y_max:
                    break
                _add(stdscr, y, 0, line)
                y += 1
        elif wizard.screen == Screen.SPLASH:
            y = _wrap(stdscr, y, C.SPLASH_TAGLINE, w, y_max)
        elif wizard.screen == Screen.KEYBOARD:
            y = _wrap(stdscr, y, C.KEYBOARD_LEAD, w, y_max)
            y = _wrap(stdscr, y, C.KEYBOARD_LIMITS, w, y_max)
            y = _wrap(stdscr, y, _keyboard.CONSOLE_DEAD_KEYS, w, y_max) + 1
            lines = []
            for i, layout_id in enumerate(LAYOUT_ORDER, 1):
                layout_spec = _keyboard.LAYOUTS[layout_id]
                star = ">" if wizard.keyboard_layout == layout_id else " "
                lines.extend(_lines(f"{star} {i} {layout_spec.title}: {layout_spec.note}", w))
                lines.append("")
            lines.extend(_lines(C.TITLE_LANGUAGE, w))
            lines.extend(_lines(C.LANGUAGE_LEAD, w))
            for code in LANGUAGE_ORDER:
                star = ">" if wizard.language == code else " "
                lines.extend(_lines(f"{star} {LANGUAGE_NAMES[code]}", w))
            lines.append("")
            if wizard.error:
                lines.extend(_lines(_error_recovery_text(wizard.error), w))
                if error_needs_support(wizard.error):
                    lines.extend(_lines(C.support_text(), w))
            elif wizard.keyboard_message:
                lines.extend(_lines(f"{C.SEVERITY_WARNING}: {wizard.keyboard_message}", w))
            lines.extend(_lines(C.KEYBOARD_CHECK_LABEL, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen == Screen.WHAT:
            lines = []
            for bullet in C.WHAT_BULLETS:
                lines.extend(_lines(" * " + bullet, w))
                lines.append("")
            lines.extend(_lines(C.REPORT_MEDIA_WHAT, w))
            lines.extend(_lines(C.POWER_REMINDER, w))
            lines.extend(_lines(C.POWER_BLANKING, w))
            lines.extend(_lines(wizard.power_text, w))
            lines.extend(_lines(C.POWER_EVENTS, w))
            ident = _support_identity_text(wizard)
            if ident:
                lines.extend(_lines(ident, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen == Screen.OWNER:
            y = _wrap(stdscr, y, C.OWNER_CHECKBOX, w, y_max)
            mark = "[X]" if wizard.owner_ok else "[ ]"
            _wrap(stdscr, min(y + 1, y_max - 1), C.CON_OWNER_CHECK.format(mark=mark), w, y_max)
        elif wizard.screen == Screen.PICK:
            y = _wrap(stdscr, y, C.pick_subtitle(), w, y_max) + 1
            if same_size_conflict(wizard.listed_disks):
                y = _wrap(stdscr, y, f"{C.SEVERITY_WARNING}: {C.SAME_SIZE_HINT}", w, y_max) + 1
            if wizard.error:
                y = _wrap(stdscr, y, _error_recovery_text(wizard.error), w, y_max) + 1
                if error_needs_support(wizard.error):
                    y = _wrap(stdscr, y, C.support_text(), w, y_max) + 1
            if wizard.report_wanted:
                y = _wrap(stdscr, y, C.REPORT_MEDIA_WANTED, w, y_max) + 1
            blocks = _pick_blocks(wizard, w)
            avail = max(1, y_max - y)
            page = max(1, avail - 2)
            pick_page = page
            selected_path = wizard.selected.path if wizard.selected is not None else None
            pick_offset, total = _keep_selected_visible(
                blocks, pick_offset, page, selected_path, follow=pick_follow
            )
            need_above = pick_offset > 0
            need_below = pick_offset + page < total
            inner_max = y_max - (1 if need_below else 0)
            if need_above:
                y = _wrap(stdscr, y, C.CON_MORE_DISKS_ABOVE, w, inner_max)
            shown = 0
            line_no = 0
            for _disk, block in blocks:
                for line in block:
                    if line_no < pick_offset:
                        line_no += 1
                        continue
                    if y >= inner_max:
                        break
                    _add(stdscr, y, 0, line)
                    y += 1
                    shown += 1
                    line_no += 1
                if y >= inner_max:
                    break
            if need_below:
                _add(stdscr, y_max - 1, 0, C.CON_MORE_DISKS_BELOW)
        elif wizard.screen == Screen.REFRESH_CONFIRM:
            _wrap(stdscr, y, C.REFRESH_LEAD, w, y_max)
        elif wizard.screen == Screen.SHUTDOWN_CONFIRM:
            y = _wrap(stdscr, y, wizard.exit_confirmation_loss, w, y_max)
            rest = (
                _lines(wizard.report_recovery_warning, w)
                + _lines(C.MEDIA_STEPS_TITLE, w)
                + _lines(wizard.exit_media_steps, w)
            )
            limits_offset = _paint_paged(stdscr, y, rest, limits_offset, y_max, w)
        elif wizard.screen == Screen.DIAGNOSTIC:
            lines = _lines(
                format_recovery_text(
                    recovery_for_diagnostic(
                        wizard.startup_error_code,
                        wizard.diagnostic_message,
                        wizard.diagnostic_step,
                    ),
                    include_technical=True,
                    compact=True,
                ),
                w,
            )
            ident = _support_identity_text(wizard)
            if ident:
                lines.extend(_lines(ident, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen == Screen.PICK_BLOCKED:
            lines = _lines(
                C.blocked_title(wizard.error, recovered=wizard._recovered),
                w,
            )
            lines.extend(
                _lines(_error_recovery_text(wizard.error, recovered=wizard._recovered), w)
            )
            if error_needs_support(wizard.error):
                lines.extend(_lines(C.support_text(), w))
            ident = _support_identity_text(wizard)
            if ident:
                lines.extend(_lines(ident, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen == Screen.PICK_EMPTY:
            lines = _lines(
                format_recovery_text(
                    recovery_for_empty(), include_technical=True, compact=True
                ),
                w,
            )
            if wizard.empty_detail:
                lines.append("")
                lines.extend(_lines(wizard.empty_detail, w))
            if wizard.protected_boot:
                lines.append("")
                lines.extend(_lines(C.CON_PROTECTED_BOOT_MEDIA, w))
                lines.extend(
                    _identity_field_lines(
                        wizard.disk_view(wizard.protected_boot), w, indent="  "
                    )
                )
            lines.append("")
            lines.extend(_lines(C.support_text(), w))
            ident = _support_identity_text(wizard)
            if ident:
                lines.extend(_lines(ident, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen == Screen.CONFIRM and wizard.selected:
            view = wizard.disk_view(wizard.selected)
            rest = _identity_field_lines(view, w)
            rest.extend(_lines(f"{C.SEVERITY_WARNING}: {wizard.warning_text()}", w))
            confirm_spec = wizard.confirm
            if confirm_spec:
                rest.extend(_lines(confirm_spec.prompt, w))
            rest.extend(_lines(C.CONFIRM_KEYBOARD_LINE.format(
                layout=_keyboard.LAYOUTS[wizard.keyboard_layout].title,
                language=LANGUAGE_NAMES[wizard.language],
            ), w))
            limits_offset = _paint_paged(stdscr, y, rest, limits_offset, y_max, w)
            _paint_footer(stdscr, footer)
            _curses_opt("echo")
            _curses_opt("curs_set", 1)
            stdscr.nodelay(False)
            stdscr.refresh()
            ch = stdscr.getch()
            _curses_opt("noecho")
            _curses_opt("curs_set", 0)
            stdscr.nodelay(True)
            if ch == KEY_RESIZE:
                continue
            if ch == curses.KEY_F5 and wizard.can_refresh:
                wizard.open_refresh_confirm()
                continue
            if ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
                delta = {
                    curses.KEY_UP: -1,
                    curses.KEY_DOWN: 1,
                    curses.KEY_PPAGE: -(h - 5),
                    curses.KEY_NPAGE: h - 5,
                }[ch]
                limits_offset = max(0, limits_offset + delta)
                continue
            if ch in (curses.KEY_ENTER, 10, 13) and wizard.token_ok:
                wizard.continue_confirm()
                # Same physical Enter must not also fire Method → Last chance.
                enter_held = True
                enter_quiet_since = None
            elif ch in (27,):
                wizard.back()
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                wizard.set_confirm_input(wizard.confirm_input[:-1])
            elif 32 <= ch < 127:
                wizard.set_confirm_input(wizard.confirm_input + chr(ch))
            continue
        elif wizard.screen == Screen.METHOD:
            lines = []
            if wizard.selected:
                lines.extend(_lines(C.SELECTED_DISK, w))
                lines.extend(_identity_field_lines(wizard.disk_view(wizard.selected), w))
            lines.extend(_lines(f"{C.SEVERITY_LIMITS}: {wizard.storage_notice}", w))
            lines.append("")
            for i, method in enumerate((MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO), 1):
                star = ">" if wizard.method == method else " "
                spec = METHODS[method]
                lines.extend(
                    _lines(
                        f"{star} {i} {spec.title}: {spec.overwrite_description} {spec.verification_description}",
                        w,
                    )
                )
                lines.append("")
            if wizard.selected:
                lines.extend(
                    _lines(f"{_identity.SYSTEM_PATH_NOTE}: {wizard.selected.path}", w)
                )
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen in {Screen.LIMITS, Screen.REPORT_HELP, Screen.ADVANCED, Screen.DISK_HELP}:
            content = limits.full_text() if wizard.screen == Screen.LIMITS else C.ADVANCED_LOG_NOTE
            if wizard.screen == Screen.DISK_HELP:
                content = C.DISK_HELP_TITLE + "\n\n" + C.DISK_HELP_TEXT
            if wizard.screen == Screen.REPORT_HELP:
                if y < y_max:
                    _add(stdscr, y, 0, f"[{'X' if wizard.report_wanted else ' '}] {C.REPORT_WANTED}")
                    y += 1
                y = _wrap(stdscr, y, f"[{'X' if wizard.report_share_redacted else ' '}] {C.REPORT_SHARE_REDACTED}", w, y_max)
                content = (
                    C.REPORT_HELP_TITLE
                    + "\n\n"
                    + C.REPORT_HELP_TEXT
                    + "\n\n"
                    + wizard.report_recovery_warning
                )
            lines = [line for paragraph in content.split("\n") for line in _lines(paragraph, w)]
            page_size = max(1, y_max - y)
            limits_offset = min(limits_offset, max(0, len(lines) - page_size))
            for line in lines[limits_offset:limits_offset + page_size]:
                if y >= y_max:
                    break
                _add(stdscr, y, 0, line)
                y += 1
        elif wizard.screen == Screen.LAST_CHANCE:
            rest = _lines(C.LAST_LEAD, w)
            if wizard.selected:
                rest.extend(_identity_field_lines(wizard.disk_view(wizard.selected), w))
            rest.extend(_lines(C.POWER_KEEP, w))
            rest.extend(_lines(wizard.power_text, w))
            rest.extend(_lines(wizard.prepare_text(), w))
            rest.extend(_lines(wizard.operation_summary, w))
            rest.extend(_lines(f"{C.SEVERITY_WARNING}: {wizard.erase_label()}", w))
            rest.extend(_lines(wizard.method_summary, w))
            if wizard.error:
                rest.extend(_lines(_error_recovery_text(wizard.error), w))
                if error_needs_support(wizard.error):
                    rest.extend(_lines(C.support_text(), w))
            ident = _support_identity_text(wizard)
            if ident:
                rest.extend(_lines(ident, w))
            limits_offset = _paint_paged(stdscr, y, rest, limits_offset, y_max, w)
        elif wizard.screen == Screen.WORKING:
            lines = []
            if wizard.stop_confirmation is not None:
                lines.extend(_lines(f"{C.SEVERITY_WARNING}: {C.STOP_TITLE} {C.STOP_LEAD}", w))
            if wizard.error:
                lines.extend(_lines(_error_recovery_text(wizard.error), w))
                if error_needs_support(wizard.error):
                    lines.extend(_lines(C.support_text(), w))
            lines.extend(_lines(wizard.progress_view.status_text, w))
            disk = wizard.operation_disk
            if disk is not None:
                lines.extend(_identity_field_lines(wizard.disk_view(disk), w))
            elif wizard.operation_identity_text:
                lines.extend(_lines(wizard.operation_identity_text, w))
            lines.extend(_lines(wizard.operation_method_text, w))
            if wizard.evidence_warning:
                lines.extend(_lines(f"{C.SEVERITY_WARNING}: {wizard.evidence_warning}", w))
            for text in (C.POWER_KEEP, wizard.power_text):
                if text:
                    lines.extend(_lines(text, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen in {Screen.CHECKING, Screen.STOPPING, Screen.REFRESHING}:
            messages = {
                Screen.CHECKING: C.BUSY_CHECKING_MESSAGE,
                Screen.STOPPING: C.STOPPING_TEXT,
                Screen.REFRESHING: C.BUSY_REFRESHING_MESSAGE,
            }
            lines = []
            if wizard.screen == Screen.STOPPING:
                disk = wizard.operation_disk
                if disk is not None:
                    lines.extend(_identity_field_lines(wizard.disk_view(disk), w))
                elif wizard.operation_identity_text:
                    lines.extend(_lines(wizard.operation_identity_text, w))
                lines.extend(_lines(wizard.operation_method_text, w))
            elif wizard.selected is not None:
                lines.extend(_identity_field_lines(wizard.disk_view(wizard.selected), w))
            lines.extend(_lines(messages[wizard.screen], w))
            if wizard.screen != Screen.REFRESHING:
                lines.extend(_lines(C.POWER_KEEP, w))
                lines.extend(_lines(wizard.power_text, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen == Screen.DONE:
            wizard.maybe_play_outcome_sound()
            report = wizard.report_view
            sections = recovery_for_view(wizard.result_view)
            # First 80x24 page keeps the pre-#107 landmarks: outcome, next
            # step, post-erase note, Report status, then paged aftercare.
            # Disk identity stays reachable; support/meaning follow in the tail.
            lines = []
            if wizard.selected:
                lines.extend(_identity_field_lines(wizard.disk_view(wizard.selected), w))
            lines.extend(_lines(wizard.method_result, w))
            lines.extend(_lines(wizard.method_summary, w))
            lines.extend(_lines(wizard.result_view.next_step, w))
            if may_have_erased(wizard.result_view.code):
                lines.extend(_lines(C.POST_ERASE_BOOT, w))
            lines.extend(_lines(C.REPORT_STATUS_TITLE, w))
            lines.extend(_lines(_report_headline(wizard, report), w))
            if not wizard.preview and not report.evidence_error:
                lines.extend(
                    _lines(
                        C.report_aftercare(
                            can_save=report.can_save, status=report.status, message=report.message
                        ),
                        w,
                    )
                )
            if report.evidence_error:
                lines.extend(_lines(f"{C.SEVERITY_WARNING}: {wizard.evidence_warning}", w))
            if wizard.done_support_needed:
                lines.extend(_lines(C.support_text(), w))
            ident = _support_identity_text(wizard)
            if ident:
                lines.extend(_lines(ident, w))
            if sections:
                from beamo_wipe import recovery as Rec

                lines.extend(_lines(f"{Rec.RECOVERY_MEANING}: {sections.meaning}", w))
                if sections.technical:
                    lines.extend(_lines(f"{Rec.RECOVERY_TECHNICAL}: {sections.technical}", w))
            lines.extend(_lines(wizard.elapsed_text, w))
            lines.extend(_lines(C.REPORT_STATUS_NOTICE, w))
            if wizard.check_alerts:
                for alert in wizard.check_alerts:
                    lines.extend(_lines(f"{C.SEVERITY_WARNING}: {alert}", w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        _paint_footer(stdscr, footer)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == KEY_RESIZE:
            continue
        if wizard.screen == Screen.SHUTDOWN_CONFIRM and ch in (ord("d"), ord("D")):
            _confirm_report_discard(stdscr, wizard)
            continue
        if wizard.can_open_diagnostic and ch in (ord("d"), ord("D")):
            wizard.open_diagnostic()
            continue
        if wizard.screen == Screen.DIAGNOSTIC and ch in (ord("r"), ord("R")):
            _confirm_diagnostic_action(stdscr, wizard)
            continue
        if ch == curses.KEY_F5 and wizard.can_refresh:
            wizard.open_refresh_confirm()
            inventory_open = False
            continue
        if inventory_open:
            if ch == 27:
                inventory_open = False
            elif ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
                delta = {curses.KEY_UP: -1, curses.KEY_DOWN: 1,
                         curses.KEY_PPAGE: -page_size, curses.KEY_NPAGE: page_size}[ch]
                inventory_offset = max(0, inventory_offset + delta)
            continue
        if wizard.screen == Screen.PICK and ch in (ord("c"), ord("C")) and len(wizard.selectable) > 1:
            inventory_open = True
            comparison_open = True
            inventory_boot = False
            inventory_offset = 0
            continue
        if wizard.screen in (Screen.PICK, Screen.PICK_EMPTY) and ch in (ord("b"), ord("B")) and wizard.protected_boot:
            inventory_open = True
            inventory_boot = True
            comparison_open = False
            inventory_offset = 0
            continue
        if wizard.screen in (Screen.PICK, Screen.PICK_EMPTY) and ch in (ord("o"), ord("O")) and wizard.other_devices:
            comparison_open = False
            inventory_boot = False
            inventory_open = True
            inventory_offset = 0
            continue
        if ch == -1:
            enter_held, enter_quiet_since, released = _advance_enter_quiet(
                enter_held, enter_quiet_since, time.monotonic()
            )
            if released and wizard.screen in (
                Screen.DONE,
                Screen.PICK_EMPTY,
                Screen.PICK_BLOCKED,
            ):
                wizard.arm_done_keyboard()
            time.sleep(0.08)
            continue
        if enter_held:
            # Any queued event breaks the quiet interval. A repeat Enter is
            # still part of the same physical hold and remains suppressed.
            enter_quiet_since = None
        if _is_enter_repeat(enter_held, ch):
            continue
        enter_held = ch in (curses.KEY_ENTER, 10, 13)
        if (
            wizard.screen == Screen.DONE
            and not wizard.preview
            and wizard.report_view.can_save
            and ch in (ord("r"), ord("R"))
        ):
            _confirm_report_save(stdscr, wizard)
            enter_held = True
            enter_quiet_since = None
            continue
        _paged = {
            Screen.WORKING, Screen.CHECKING, Screen.STOPPING, Screen.REFRESHING,
            Screen.LIMITS,
            Screen.DISK_HELP,
            Screen.REPORT_HELP,
            Screen.ADVANCED,
            Screen.DONE,
            Screen.WHAT,
            Screen.METHOD,
            Screen.LAST_CHANCE,
            Screen.CONFIRM,
            Screen.KEYBOARD,
            Screen.SHUTDOWN_CONFIRM,
            Screen.PICK_EMPTY,
            Screen.PICK_BLOCKED,
            Screen.DIAGNOSTIC,
            Screen.OWNER,
        }
        if (
            wizard.screen == Screen.PICK
            and not inventory_open
            and ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE)
        ):
            if ch in (curses.KEY_UP, curses.KEY_DOWN):
                wizard.move_selection(-1 if ch == curses.KEY_UP else 1)
                pick_follow = True
            else:
                delta = -pick_page if ch == curses.KEY_PPAGE else pick_page
                pick_offset = max(0, pick_offset + delta)
                pick_follow = False
            continue
        if wizard.screen in _paged and ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            delta = {curses.KEY_UP: -1, curses.KEY_DOWN: 1,
                     curses.KEY_PPAGE: -(h - 5), curses.KEY_NPAGE: h - 5}[ch]
            limits_offset = max(0, limits_offset + delta)
            continue
        if wizard.screen not in _paged:
            limits_offset = 0
        _handle(wizard, ch)
    return 0


def _is_enter_repeat(held: bool, ch: int) -> bool:
    """True for X/TTY auto-repeat Enter (extra KEY_ENTER with no gap)."""
    return held and ch in (curses.KEY_ENTER, 10, 13)


def _advance_enter_quiet(
    held: bool, quiet_since: float | None, now: float
) -> tuple[bool, float | None, bool]:
    """Require a full quiet interval before treating Enter as released."""
    if not held:
        return False, None, True
    if quiet_since is None:
        return True, now, False
    if now - quiet_since < ENTER_RELEASE_QUIET_S:
        return True, quiet_since, False
    return False, None, True


def _confirm_diagnostic_action(stdscr, wizard: Wizard) -> None:
    if wizard._diagnostic_busy:
        return
    h, _ = stdscr.getmaxyx()
    action = "SAVE" if wizard._diagnostic_baseline else "PREPARE"
    _add(stdscr, h - 2, 0, C.CON_DIAG_CONFIRM.format(action=action))
    stdscr.refresh()
    stdscr.timeout(-1)
    _curses_opt("echo")
    try:
        answer = stdscr.getstr(h - 1, 0, 16).decode("ascii", errors="replace").strip()
        if answer == action:
            wizard.diagnostic_action(background=True)
    finally:
        _curses_opt("noecho")
        stdscr.timeout(100)


def _confirm_report_discard(stdscr, wizard: Wizard) -> None:
    generation = wizard.shutdown_generation
    h, _ = stdscr.getmaxyx()
    stdscr.nodelay(False)
    _curses_opt("echo")
    _curses_opt("curs_set", 1)
    try:
        _add(stdscr, h - 2, 0, C.CON_TYPE_OR_RETURN.format(word=wizard.exit_confirmation_discard.upper()))
        _add(stdscr, h - 1, 0, " " * 55)
        stdscr.refresh()
        answer = stdscr.getstr(h - 1, 0, 32).decode("ascii", errors="replace")
        if answer == wizard.exit_confirmation_discard.upper():
            wizard.confirm_shutdown_without_saving(generation)
        else:
            wizard.keep_report_session()
    finally:
        _curses_opt("noecho")
        _curses_opt("curs_set", 0)
        stdscr.nodelay(True)


def _confirm_report_save(stdscr, wizard: Wizard) -> None:
    """A held R cannot confirm an export; the owner must type literal SAVE."""
    h, _w = stdscr.getmaxyx()
    _curses_opt("echo")
    _curses_opt("curs_set", 1)
    stdscr.nodelay(False)
    try:
        _add(stdscr, max(0, h - 2), 0, C.CON_SAVE_TYPE)
        stdscr.refresh()
        typed = stdscr.getstr(max(0, h - 2), len(C.CON_SAVE_TYPE), 8).decode("ascii", errors="ignore")
        if typed == "SAVE":
            wizard.save_report_to_usb()
    finally:
        _curses_opt("noecho")
        _curses_opt("curs_set", 0)
        stdscr.nodelay(True)


def _handle(wizard: Wizard, ch: int) -> None:
    if wizard.can_open_keyboard and wizard.screen != Screen.KEYBOARD and ch in (ord("k"), ord("K")):
        wizard.open_keyboard()
        return
    if wizard.screen == Screen.KEYBOARD:
        keyboard_mapping = {ord("1"): "us", ord("2"): "fr", ord("3"): "de"}
        if ch in keyboard_mapping:
            wizard.set_keyboard_layout(keyboard_mapping[ch])
            return
        if ch == curses.KEY_F2:
            wizard.set_language(_next_language(wizard))
            return
        if ch in (curses.KEY_ENTER, 10, 13):
            wizard.accept_keyboard()
            return
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            wizard.set_typing_check(wizard.typing_check[:-1])
            return
        if 32 <= ch < 127:
            wizard.set_typing_check(wizard.typing_check + chr(ch))
            return
        if ch == 27:
            wizard.back()
            return
        return
    if wizard.screen == Screen.DONE and ch in (ord("a"), ord("A")):
        wizard.erase_another_disk()
        return
    if wizard.screen == Screen.DONE and ch in (ord("e"), ord("E")):
        wizard.begin_evidence_retry()
        return
    if wizard.screen in (Screen.WORKING, Screen.DONE) and ch in (ord("o"), ord("O")):
        wizard.toggle_sounds()
        return
    if wizard.screen in (Screen.WORKING, Screen.DONE) and ch in (ord("h"), ord("H")):
        if wizard.screen == Screen.DONE:
            wizard.hear_outcome_sound()
        else:
            wizard.hear_both_sounds()
        return
    if wizard.screen == Screen.REFRESH_CONFIRM:
        if ch in (curses.KEY_ENTER, 10, 13):
            wizard.confirm_refresh()
        elif ch == 27:
            wizard.back()
        return
    if wizard.screen == Screen.SHUTDOWN_CONFIRM:
        if ch in (27, curses.KEY_ENTER, 10, 13):
            wizard.keep_report_session()
        return
    if wizard.can_open_report_help and ch in (ord("r"), ord("R")):
        wizard.open_report_help()
        return
    if wizard.screen == Screen.PICK and ch in (ord("u"), ord("U")):
        wizard.open_disk_help()
        return
    if wizard.screen == Screen.DISK_HELP:
        if ch == 27:
            wizard.back()
        elif ch in (ord("s"), ord("S")):
            wizard.shutdown()
        return
    if wizard.screen == Screen.REPORT_HELP:
        if ch == ord(" "):
            wizard.set_report_wanted(not wizard.report_wanted)
        elif ch in (ord("s"), ord("S")):
            wizard.set_report_share_redacted(not wizard.report_share_redacted)
        elif ch in (27, curses.KEY_ENTER, 10, 13):
            wizard.close_report_help()
        return
    if wizard.screen == Screen.ADVANCED and ch in (curses.KEY_ENTER, 10, 13):
        wizard.close_advanced()
        return
    if wizard.screen == Screen.METHOD and ch in (ord("a"), ord("A")):
        wizard.open_advanced()
        return
    if wizard.screen == Screen.METHOD and ch in (ord("l"), ord("L")):
        wizard.open_limits()
        return
    if wizard.screen == Screen.SPLASH:
        wizard.skip_splash()
        return
    if wizard.screen == Screen.WORKING:
        if wizard.stop_confirmation is not None:
            if ch in (ord("s"), ord("S")):
                wizard.confirm_stop(wizard.stop_confirmation)
            elif ch in (27, 10, 13, ord("k"), ord("K")):
                wizard.keep_erasing()
        elif ch == 27:
            wizard.request_stop()
        return
    if ch == 27:
        wizard.back()
        return
    if ch in (ord("s"), ord("S")) and wizard.screen in {Screen.WHAT, Screen.DIAGNOSTIC}:
        wizard.shutdown()
        return
    if ch in (curses.KEY_ENTER, 10, 13):
        if wizard.screen == Screen.WHAT:
            wizard.accept_what()
        elif wizard.screen == Screen.OWNER and wizard.owner_ok:
            wizard.continue_owner()
        elif wizard.screen == Screen.PICK:
            wizard.continue_pick()
        elif wizard.screen == Screen.METHOD:
            wizard.continue_method()
        elif wizard.screen == Screen.LAST_CHANCE and wizard.erase_enabled:
            wizard.confirm_erase()
        elif wizard.screen in (Screen.DONE, Screen.PICK_BLOCKED, Screen.PICK_EMPTY):
            wizard.accept_done_keyboard()
        return
    if wizard.preview and wizard.screen == Screen.DONE and ch in (ord("c"), ord("C")):
        wizard.shutdown()
        return
    if wizard.screen == Screen.OWNER and ch == ord(" "):
        wizard.set_owner(not wizard.owner_ok)
    if wizard.screen == Screen.PICK and ch in (
        curses.KEY_UP,
        curses.KEY_DOWN,
        curses.KEY_PPAGE,
        curses.KEY_NPAGE,
    ):
        step = 8 if ch in (curses.KEY_PPAGE, curses.KEY_NPAGE) else 1
        wizard.move_selection(-step if ch in (curses.KEY_UP, curses.KEY_PPAGE) else step)
    if wizard.screen == Screen.METHOD and ch in (ord("1"), ord("2"), ord("3")):
        mapping = {ord("1"): MethodId.EVERYDAY, ord("2"): MethodId.EXTRA, ord("3"): MethodId.QUICK_ZERO}
        wizard.set_method(mapping[ch])


def _add(stdscr, y, x, text, attr=curses.A_NORMAL) -> None:
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h:
        return
    fitted = _fit_cols(text or "", max(0, w - 1 - x))
    if not fitted:
        return
    try:
        stdscr.addstr(y, x, fitted, attr)
    except curses.error:
        pass


def _wrap(stdscr, y, text, width, y_max=None) -> int:
    h, w = stdscr.getmaxyx()
    if y_max is None:
        y_max = h
    for line in _lines(text, min(width, w)):
        if y >= y_max:
            return y
        _add(stdscr, y, 0, line)
        y += 1
    return y


def _wrap_view(stdscr, y, view, width, y_max, *, include_path: bool = False) -> int:
    for line in _identity_field_lines(view, width, include_path=include_path):
        if y >= y_max:
            return y
        _add(stdscr, y, 0, line)
        y += 1
    return y


def _wrap_operation_identity(stdscr, y, wizard, width, y_max) -> int:
    """Request-bound disk + method for operation screens. Never substituted."""
    disk = wizard.operation_disk
    if disk is not None:
        y = _wrap_view(stdscr, y, wizard.disk_view(disk), width, y_max)
    elif wizard.operation_identity_text:
        y = _wrap(stdscr, y, wizard.operation_identity_text, width, y_max)
    return _wrap(stdscr, y, wizard.operation_method_text, width, y_max)
