# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard console fallback when X/Tk is unavailable. Same wizard, larger text."""

from __future__ import annotations

import curses
import select
import sys
import time
import textwrap

from beamo_wipe import copy as C
from beamo_wipe import diagnostic_report as D
from beamo_wipe import storage_limits as limits
from beamo_wipe import inventory
from beamo_wipe.keyboard import CONSOLE_DEAD_KEYS, LAYOUT_ORDER, LAYOUTS
from beamo_wipe.methods import METHODS, MethodId
from beamo_wipe.models import Screen
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.wizard import Wizard


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


def _lines(text: str, width: int) -> list[str]:
    """Wrap including long identifiers. Never leaves a token unwrapped."""
    col = max(8, int(width) - 2)
    out: list[str] = []
    for para in (text or "").split("\n"):
        out.extend(
            textwrap.wrap(
                para,
                width=col,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return out


def _identity_text(view) -> str:
    return view.announcement


def _pick_blocks(wizard: Wizard, width: int) -> list[tuple[object, list[str]]]:
    """One wrapped block per eligible disk: heading, identifier, notes."""
    blocks = []
    for disk in sorted(wizard.selectable, key=lambda d: d.path):
        view = wizard.disk_view(disk)
        star = ">" if wizard.selected and disk.path == wizard.selected.path else " "
        heading = "  ".join(
            part
            for part in (view.title, view.capacity, view.kind_chip, view.connection)
            if part
        )
        block = _lines(f"{star} {heading}", width)
        block.extend(_lines(f"  {view.id_label}: {view.id_value}", width))
        for note in view.notes:
            block.extend(_lines("  " + note, width))
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
        y = _wrap(stdscr, y, "More above. Use Up and Down.", width, inner)
    for line in lines[offset:]:
        if y >= inner:
            break
        _add(stdscr, y, 0, line)
        y += 1
    if need_below:
        _add(stdscr, y_max - 1, 0, "More below. Use Up and Down.")
    return offset


def _keep_selected_visible(blocks, pick_offset: int, page: int, selected_path: str | None) -> tuple[int, int]:
    """Scroll so the selected disk's identity stays in the window."""
    starts: list[int] = []
    total = 0
    for _disk, block in blocks:
        starts.append(total)
        total += len(block)
    if selected_path:
        try:
            idx = next(i for i, (d, _) in enumerate(blocks) if d.path == selected_path)
            start = starts[idx]
            end = start + len(blocks[idx][1])
            if end - start >= page or start < pick_offset:
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
        bits.append("D: Diagnostic report (not erase evidence)")
    if wizard.can_open_report_help:
        bits.append("R: Need a report? (optional)")
    if wizard.can_refresh and wizard.screen != Screen.REPORT_HELP:
        bits.append("F5: Check disks again (clears all confirmations)")
    if wizard.can_open_keyboard and wizard.screen != Screen.KEYBOARD:
        bits.append("K: Keyboard layout")
    return bits


def _primary_footer(wizard: Wizard, inventory_open: bool) -> list[str]:
    if inventory_open:
        return ["Read only. Up/Down, PgUp/PgDn: read. Esc: back."]
    screen = wizard.screen
    if screen == Screen.SPLASH:
        return ["Press any key."]
    if screen == Screen.KEYBOARD:
        return [
            "1/2/3: layout. Type to check. Enter continues.",
            "> " + wizard.typing_check,
        ]
    if screen == Screen.WHAT:
        return ["Enter: I understand    S: shut down", "Up/Down: read more"]
    if screen == Screen.OWNER:
        return ["Space to check. Enter continues only when checked. Esc: back"]
    if screen == Screen.PICK:
        lines = ["Up/Down then Enter. PgUp/PgDn page. Esc back."]
        if wizard.other_devices:
            lines.insert(0, "Other detected devices (O): read reasons; not selectable.")
        return lines
    if screen == Screen.PICK_EMPTY:
        lines = ["Enter: shut down    Esc: back"]
        if wizard.other_devices:
            lines.insert(0, "Other detected devices (O): read reasons; not selectable.")
        return lines
    if screen == Screen.PICK_BLOCKED:
        return ["Enter: shut down    Esc: back"]
    if screen == Screen.CONFIRM:
        return [
            "Up/Down: read more    F5: Check disks again (clears all confirmations)",
            "> " + wizard.confirm_input,
        ]
    if screen == Screen.METHOD:
        return [
            "L: limits. A: Advanced. 1/2/3: choose. Enter: continue.",
            "Up/Down: read more",
        ]
    if screen == Screen.LIMITS:
        return ["Up/Down, PgUp/PgDn: read. Esc: back."]
    if screen == Screen.REPORT_HELP:
        return ["Arrows/Pg: read. Space: report preference. S: sharing copy. Esc: back."]
    if screen == Screen.ADVANCED:
        return ["Up/Down, PgUp/PgDn: read. Esc: back."]
    if screen == Screen.LAST_CHANCE:
        return [
            f"Wait {wizard.countdown_display}s" if not wizard.erase_enabled else "Enter to erase.",
            "Esc: back    Up/Down: read more",
        ]
    if screen == Screen.WORKING:
        return ["Esc: cancel erase (interrupted)"]
    if screen == Screen.CHECKING:
        return ["Please wait. Controls are unavailable during this check."]
    if screen == Screen.STOPPING:
        return ["The disk may still be erasing. Keep this USB connected."]
    if screen == Screen.REFRESHING:
        return ["Please wait. Previous selections have been cleared."]
    if screen == Screen.SHUTDOWN_CONFIRM:
        return [
            "Enter/Esc: keep session open",
            "D: shut down without saving (type confirmation)",
        ]
    if screen == Screen.DIAGNOSTIC:
        action = "save diagnostic report" if wizard._diagnostic_baseline else "prepare baseline"
        return ["R: " + action + "    Esc: back    S: shut down"]
    if screen == Screen.DONE:
        report = wizard.report_view
        if wizard.preview:
            action = "Enter: run again    C: close"
        elif report.can_save:
            action = "R: save report to one FAT32 USB    Enter: shut down"
        elif report.can_retry_evidence:
            action = "E: retry evidence save    Enter: shut down"
        else:
            action = "Enter: shut down"
        return ["Up/Down, PgUp/PgDn: read aftercare.", action]
    return ["Esc: back"]


def _footer_lines(wizard: Wizard, inventory_open: bool, width: int, height: int) -> list[str]:
    """Primary actions first. Extra chrome is dropped before an action is clipped."""
    primary: list[str] = []
    for line in _primary_footer(wizard, inventory_open):
        primary.extend(_lines(line, width) or [""])
    extra: list[str] = []
    if not inventory_open and wizard.screen not in {
        Screen.WORKING,
        Screen.CHECKING,
        Screen.STOPPING,
        Screen.REFRESHING,
        Screen.SHUTDOWN_CONFIRM,
        Screen.CONFIRM,
        Screen.KEYBOARD,
    }:
        joined = "    ".join(_chrome_extra(wizard))
        if joined:
            extra.extend(_lines(joined, width))
    # Keep at least two body rows (title plus one content line).
    max_footer = max(1, height - 2)
    if len(primary) >= max_footer:
        return primary[-max_footer:]
    return primary + extra[: max_footer - len(primary)]


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


def _print_view(view, width: int = 76) -> None:
    print(textwrap.fill(_identity_text(view), width, break_long_words=True, break_on_hyphens=False))


def _answer(wizard: Wizard, prompt: str) -> str:
    if wizard.can_refresh:
        print("Type CHECK DISKS AGAIN to refresh and clear all confirmations.")
    if wizard.can_open_diagnostic:
        print("Type DIAGNOSTIC for a diagnostic report (not erase evidence).")
    if wizard.can_open_report_help:
        print("Type REPORT for Need a report? (optional).")
    answer = input(prompt)
    if wizard.can_open_report_help and answer.strip().upper() == "REPORT":
        wizard.open_report_help()
        raise _InventoryRefreshed
    if wizard.can_open_diagnostic and answer.strip().upper() == "DIAGNOSTIC":
        wizard.open_diagnostic()
        raise _InventoryRefreshed
    if wizard.can_refresh and answer.strip().upper() == "CHECK DISKS AGAIN":
        wizard.refresh_disks()
        raise _InventoryRefreshed
    return answer


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
                    print(C.SHUTDOWN_TITLE)
                    print(C.SHUTDOWN_LOSS)
                print("Console input unavailable. Shutdown was not authorized.")
                return 3
            return 0
        except KeyboardInterrupt:
            # Ctrl-C when SIGINT is not ignored (desktop fallback). A running
            # wipe must be cancelled, never abandoned with nwipe still on disk;
            # anywhere else it shuts down cleanly instead of a traceback.
            if wizard.screen == Screen.WORKING:
                try:
                    wizard.cancel_wipe()
                except Exception:
                    pass
                if wizard.wants_shutdown:
                    return 0
                continue
            if wizard.screen == Screen.SHUTDOWN_CONFIRM:
                wizard.keep_report_session()
            else:
                wizard.shutdown()
            if wizard.wants_shutdown:
                return 0


def _plain_loop_body(wizard: Wizard) -> int:
    last_working = None
    while not wizard.wants_shutdown:
        wizard.tick()
        screen = wizard.screen
        if screen != Screen.WORKING:
            print("\n" + "=" * 60)
            print(C.APP_NAME, screen.value)
            last_working = None
            if wizard.preview:
                print(C.PREVIEW_BANNER)
            print("=" * 60)
        if screen == Screen.SHUTDOWN_CONFIRM:
            print(C.SHUTDOWN_TITLE)
            print(textwrap.fill(C.SHUTDOWN_LOSS, 76))
            print(wizard.report_recovery_warning)
            generation = wizard.shutdown_generation
            answer = input(
                "Type SHUT DOWN WITHOUT SAVING to discard; Enter keeps session open: "
            )
            if answer == "SHUT DOWN WITHOUT SAVING":
                wizard.confirm_shutdown_without_saving(generation)
            else:
                wizard.keep_report_session()
            continue
        if screen == Screen.DIAGNOSTIC:
            print(D.report_title(wizard.startup_error_code))
            print(D.NOTICE)
            print(D.PREPARE)
            print(wizard.diagnostic_message)
            action = "SAVE" if wizard._diagnostic_baseline else "PREPARE"
            answer = input(f"Type {action}, BACK, or SHUTDOWN: ").strip().upper()
            if answer == action:
                wizard.diagnostic_action()
            elif answer == "BACK":
                wizard.close_diagnostic()
            elif answer == "SHUTDOWN":
                wizard.shutdown()
            continue
        if screen == Screen.SPLASH:
            print(C.SPLASH_TAGLINE)
            _answer(wizard, "Press Enter… ")
            wizard.skip_splash()
            continue
        if screen == Screen.KEYBOARD:
            print(C.TITLE_KEYBOARD)
            print(C.KEYBOARD_LEAD)
            print(C.KEYBOARD_LIMITS)
            print(CONSOLE_DEAD_KEYS)
            for i, layout_id in enumerate(LAYOUT_ORDER, 1):
                spec = LAYOUTS[layout_id]
                mark = ">" if wizard.keyboard_layout == layout_id else " "
                print(f"{mark} {i} {spec.title}")
                print(spec.note)
            if wizard.keyboard_message:
                print(wizard.keyboard_message)
            elif wizard.error:
                print(wizard.error)
            print(C.KEYBOARD_CHECK_LABEL)
            typed = input("> ")
            key = typed.strip()
            mapping = {"1": "us", "2": "fr", "3": "de"}
            if key in mapping:
                wizard.set_keyboard_layout(mapping[key])
            elif key.upper() == "K":
                pass
            elif key == "":
                wizard.accept_keyboard()
            else:
                wizard.set_typing_check(typed)
            continue
        if screen == Screen.WHAT:
            for b in C.WHAT_BULLETS:
                print(" -", b)
            print(C.POWER_REMINDER)
            print(C.POWER_BLANKING)
            _answer(wizard, "Press Enter to continue… ")
            wizard.accept_what()
            continue
        if screen == Screen.OWNER:
            print(C.OWNER_CHECKBOX)
            ans = _answer(wizard, "Type YES if that is true: ").strip()
            wizard.set_owner(ans.upper() == "YES")
            if wizard.owner_ok:
                wizard.continue_owner()
            continue
        if screen == Screen.PICK_BLOCKED:
            print(wizard.error or C.IDENTIFY_ERROR)
            _answer(wizard, "Press Enter to shut down… ")
            wizard.shutdown()
            continue
        if screen == Screen.PICK_EMPTY:
            print(C.EMPTY_DISKS)
            if wizard.empty_detail:
                print(wizard.empty_detail)
            if wizard.other_devices:
                print(inventory.TITLE)
                print(inventory.full_text(wizard.other_devices))
            _answer(wizard, "Press Enter to shut down… ")
            wizard.shutdown()
            continue
        if screen == Screen.PICK:
            if wizard.other_devices:
                print(inventory.TITLE)
                print(inventory.full_text(wizard.other_devices))
            print("Eligible disks")
            if same_size_conflict(wizard.listed_disks):
                print(C.SAME_SIZE_HINT)
            numbered = sorted(wizard.selectable, key=lambda d: d.path)
            for i, disk in enumerate(numbered, 1):
                view = wizard.disk_view(disk)
                print(textwrap.fill(f"[{i}] {view.compact_line}", 76, break_long_words=True, break_on_hyphens=False))
                for note in view.notes:
                    print(textwrap.fill("    " + note, 76, break_long_words=True, break_on_hyphens=False))
            choice = _answer(wizard, "Number of disk to erase: ").strip()
            try:
                idx = int(choice) - 1
                if idx < 0:
                    raise IndexError
                wizard.select_disk(numbered[idx].path)
                wizard.continue_pick()
            except (ValueError, IndexError):
                pass
            continue
        if screen == Screen.CONFIRM:
            disk = wizard.selected
            spec = wizard.confirm
            if disk:
                _print_view(wizard.disk_view(disk))
            print(textwrap.fill(wizard.warning_text(), 76, break_long_words=True, break_on_hyphens=False))
            print(spec.prompt if spec else "")
            typed = _answer(wizard, "> ")
            wizard.set_confirm_input(typed)
            if wizard.token_ok:
                wizard.continue_confirm()
            continue
        if screen == Screen.METHOD:
            print(C.TITLE_METHOD)
            print(wizard.storage_notice)
            print(limits.BUTTON)
            for method, spec in METHODS.items():
                card = C.METHOD_CARDS[method]
                # One logical line so overwrite + verification stay a contiguous description.
                # The TTY wraps at its own width; pre-fill would split spec.description.
                print(
                    f"{card['key']} {spec.title}: "
                    f"{spec.overwrite_description} {spec.verification_description}"
                )
            choice = _answer(wizard, "Choice [1], L for storage limits, A for Advanced: ").strip()
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
                Screen.CHECKING: "Checking disk",
                Screen.STOPPING: "Stopping erase",
                Screen.REFRESHING: "Checking disks again",
            }
            messages = {
                Screen.CHECKING: "Confirming disk identity and boot USB exclusions. Please wait; controls are unavailable during this check.",
                Screen.STOPPING: "Waiting for the erase process to exit and cleanup to finish. The disk may still be erasing. Keep this USB connected.",
                Screen.REFRESHING: "Previous selections and confirmations have been cleared.",
            }
            print(titles[screen])
            if wizard.selected is not None:
                _print_view(wizard.disk_view(wizard.selected))
            print(textwrap.fill(messages[screen], 76))
            time.sleep(0.2)
            continue
        if screen == Screen.LAST_CHANCE:
            if wizard.selected:
                _print_view(wizard.disk_view(wizard.selected))
            print(wizard.prepare_text())
            print(wizard.operation_summary)
            print(wizard.erase_label())
            print(wizard.method_summary)
            if wizard.error:
                print(wizard.error)
            while wizard.countdown_left > 0:
                wizard.tick()
                print(f"Wait {wizard.countdown_display}…")
                time.sleep(0.4)
            ans = _answer(wizard, "Type ERASE to start: ").strip()
            if ans.upper() == "ERASE":
                wizard.confirm_erase()
            else:
                wizard.back()
            continue
        if screen == Screen.WORKING:
            status = (wizard.progress_view.status_text, wizard.error, wizard.evidence_warning)
            if status != last_working:
                print(status[0], "  [type CANCEL then Enter to interrupt]")
                for warning in status[1:]:
                    if warning:
                        print(warning)
                if last_working is None and wizard.selected:
                    _print_view(wizard.disk_view(wizard.selected))
                last_working = status
            # Poll canonical TTY input without blocking progress updates.
            # This remains usable when the hardened kiosk disables INTR.
            try:
                ready, _w, _x = select.select([sys.stdin], [], [], 0.3)
                if ready:
                    typed = sys.stdin.readline()
                    if typed == "":
                        raise EOFError
                    if typed.strip().casefold() == "cancel":
                        print("Stopping erase. Waiting for process termination and cleanup.")
                        wizard.cancel_wipe()
            except InterruptedError:
                time.sleep(0.3)
            except (OSError, ValueError) as exc:
                # A closed/failed terminal cannot accept the advertised
                # CANCEL command. Use the same stop-and-report recovery as
                # EOF instead of silently polling an inaccessible erase.
                raise EOFError from exc
            continue
        if screen == Screen.DONE:
            print(wizard.elapsed_text)
            report = wizard.report_view
            print(wizard.method_summary)
            print(wizard.method_result)
            if wizard.selected:
                _print_view(wizard.disk_view(wizard.selected))
            if report.evidence_error:
                print(wizard.evidence_warning)
            if wizard.preview:
                print(wizard.result_view.next_step)
                ans = _answer(wizard, "Enter to run again, or q to close… ").strip().lower()
                if ans in ("q", "quit", "close"):
                    wizard.shutdown()
                else:
                    wizard.reset_for_preview()
            else:
                print(wizard.result_view.next_step)
                print(C.report_aftercare(can_save=report.can_save, status=report.status, message=report.message))
                if report.can_retry_evidence:
                    prompt = "Type RETRY to save evidence again, or SHUTDOWN: "
                elif report.can_save:
                    prompt = "Type SAVE to save the report, or SHUTDOWN: "
                else:
                    prompt = "Type SHUTDOWN: "
                action = _answer(wizard, prompt).strip().upper()
                if action == "RETRY" and report.can_retry_evidence:
                    wizard.retry_evidence_save()
                elif action == "SAVE" and report.can_save:
                    wizard.save_report_to_usb()
                elif action == "SHUTDOWN":
                    wizard.shutdown()
            continue
        if screen == Screen.REPORT_HELP:
            print(C.REPORT_HELP_TITLE)
            print(wizard.report_recovery_warning)
            for paragraph in C.REPORT_HELP_SECTIONS:
                print(textwrap.fill(paragraph, 76))
                _answer(wizard, "Enter for more… ")
            print(f"{C.REPORT_WANTED}: {'yes' if wizard.report_wanted else 'no'}")
            print(f"{C.REPORT_SHARE_REDACTED}: {'yes' if wizard.report_share_redacted else 'no'}")
            action = _answer(wizard, "YES to want a report, SHARE for a redacted copy, NO to clear, BACK to return: ").strip().upper()
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
                print(textwrap.fill(body, 76))
                _answer(wizard, "Enter for more… ")
            wizard.close_limits()
            continue
        if screen == Screen.ADVANCED:
            print(C.ADVANCED_LEAD)
            print(textwrap.fill(C.ADVANCED_LOG_NOTE, 76))
            _answer(wizard, "Press Enter to go back… ")
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
    inventory_offset = 0
    pick_offset = 0
    while not wizard.wants_shutdown:
        wizard.tick()
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        h, w = max(2, h), max(20, w)
        footer = _footer_lines(wizard, inventory_open, w, h)
        y_max = max(1, h - len(footer))
        _add(stdscr, 0, 0, C.APP_NAME + "   " + wizard.screen.value, curses.A_BOLD)
        y = 2
        if wizard.preview:
            _add(stdscr, 1, 0, C.PREVIEW_BANNER)
            y = min(3, y_max)
        if inventory_open:
            _add(stdscr, y, 0, inventory.TITLE)
            y += 1
            lines = [line for paragraph in inventory.full_text(wizard.other_devices).split("\n")
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
            y = _wrap(stdscr, y, CONSOLE_DEAD_KEYS, w, y_max) + 1
            lines = []
            for i, layout_id in enumerate(LAYOUT_ORDER, 1):
                spec = LAYOUTS[layout_id]
                star = ">" if wizard.keyboard_layout == layout_id else " "
                lines.extend(_lines(f"{star} {i} {spec.title}: {spec.note}", w))
                lines.append("")
            if wizard.keyboard_message:
                lines.extend(_lines(wizard.keyboard_message, w))
            elif wizard.error:
                lines.extend(_lines(wizard.error, w))
            lines.extend(_lines(C.KEYBOARD_CHECK_LABEL, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen == Screen.WHAT:
            lines = []
            for bullet in C.WHAT_BULLETS:
                lines.extend(_lines(" * " + bullet, w))
                lines.append("")
            lines.extend(_lines(C.POWER_REMINDER, w))
            lines.extend(_lines(C.POWER_BLANKING, w))
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen == Screen.OWNER:
            y = _wrap(stdscr, y, C.OWNER_CHECKBOX, w, y_max)
            mark = "[X]" if wizard.owner_ok else "[ ]"
            _wrap(stdscr, min(y + 1, y_max - 1), f"{mark}  Space to check. Enter continues only when checked.", w, y_max)
        elif wizard.screen == Screen.PICK:
            y = _wrap(stdscr, y, C.pick_subtitle(), w, y_max) + 1
            if same_size_conflict(wizard.listed_disks):
                y = _wrap(stdscr, y, C.SAME_SIZE_HINT, w, y_max) + 1
            if wizard.error:
                y = _wrap(stdscr, y, wizard.error, w, y_max) + 1
            blocks = _pick_blocks(wizard, w)
            avail = max(1, y_max - y)
            page = max(1, avail - 2)
            selected_path = wizard.selected.path if wizard.selected is not None else None
            pick_offset, total = _keep_selected_visible(blocks, pick_offset, page, selected_path)
            need_above = pick_offset > 0
            need_below = pick_offset + page < total
            inner_max = y_max - (1 if need_below else 0)
            if need_above:
                y = _wrap(stdscr, y, "More disks above. Use Up and Down.", w, inner_max)
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
                _add(stdscr, y_max - 1, 0, "More disks below. Use Up and Down.")
        elif wizard.screen == Screen.SHUTDOWN_CONFIRM:
            y = _wrap(stdscr, y, C.SHUTDOWN_TITLE, w, y_max)
            y = _wrap(stdscr, y, C.SHUTDOWN_LOSS, w, y_max)
            _wrap(stdscr, y, wizard.report_recovery_warning, w, y_max)
        elif wizard.screen == Screen.DIAGNOSTIC:
            y = _wrap(stdscr, y, D.report_title(wizard.startup_error_code) + "\n" + D.NOTICE, w, y_max)
            y = _wrap(stdscr, y, D.PREPARE, w, y_max)
            _wrap(stdscr, y, wizard.diagnostic_message, w, y_max)
        elif wizard.screen == Screen.PICK_BLOCKED:
            _wrap(stdscr, y, wizard.error or C.IDENTIFY_ERROR, w, y_max)
        elif wizard.screen == Screen.PICK_EMPTY:
            _empty_text = C.EMPTY_DISKS
            if wizard.empty_detail:
                _empty_text = f"{_empty_text}\n\n{wizard.empty_detail}"
            _wrap(stdscr, y, _empty_text, w, y_max)
        elif wizard.screen == Screen.CONFIRM and wizard.selected:
            view = wizard.disk_view(wizard.selected)
            y = _wrap_view(stdscr, y, view, w, y_max)
            rest = _lines(wizard.warning_text(), w)
            spec = wizard.confirm
            if spec:
                rest.extend(_lines(spec.prompt, w))
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
                wizard.refresh_disks()
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
            lines = _lines(wizard.storage_notice, w)
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
            limits_offset = _paint_paged(stdscr, y, lines, limits_offset, y_max, w)
        elif wizard.screen in {Screen.LIMITS, Screen.REPORT_HELP, Screen.ADVANCED}:
            content = limits.full_text() if wizard.screen == Screen.LIMITS else C.ADVANCED_LOG_NOTE
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
            if wizard.selected:
                y = _wrap_view(stdscr, y, wizard.disk_view(wizard.selected), w, y_max)
            rest = []
            rest.extend(_lines(wizard.prepare_text(), w))
            rest.extend(_lines(wizard.operation_summary, w))
            rest.extend(_lines(wizard.erase_label(), w))
            rest.extend(_lines(wizard.method_summary, w))
            if wizard.error:
                rest.extend(_lines(wizard.error, w))
            limits_offset = _paint_paged(stdscr, y, rest, limits_offset, y_max, w)
        elif wizard.screen == Screen.WORKING:
            y = _wrap(stdscr, y, wizard.progress_view.status_text, w, y_max)
            if wizard.selected:
                y = _wrap_view(stdscr, y, wizard.disk_view(wizard.selected), w, y_max)
            if wizard.error:
                y = _wrap(stdscr, y, wizard.error, w, y_max)
            if wizard.evidence_warning:
                _wrap(stdscr, y, wizard.evidence_warning, w, y_max)
        elif wizard.screen in {Screen.CHECKING, Screen.STOPPING, Screen.REFRESHING}:
            titles = {
                Screen.CHECKING: "Checking disk",
                Screen.STOPPING: "Stopping erase",
                Screen.REFRESHING: "Checking disks again",
            }
            messages = {
                Screen.CHECKING: "Confirming disk identity and boot USB exclusions. Please wait; controls are unavailable during this check.",
                Screen.STOPPING: "Waiting for the erase process to exit and cleanup to finish. The disk may still be erasing.",
                Screen.REFRESHING: "Previous selections and confirmations have been cleared.",
            }
            y = _wrap(stdscr, y, titles[wizard.screen], w, y_max)
            if wizard.selected is not None:
                y = _wrap_view(stdscr, y, wizard.disk_view(wizard.selected), w, y_max)
            _wrap(stdscr, y, messages[wizard.screen], w, y_max)
        elif wizard.screen == Screen.DONE:
            report = wizard.report_view
            if wizard.selected:
                y = _wrap_view(stdscr, y, wizard.disk_view(wizard.selected), w, y_max)
            y = _wrap(stdscr, y, wizard.method_result, w, y_max)
            y = _wrap(stdscr, y, wizard.method_summary, w, y_max)
            y = _wrap(stdscr, y, wizard.result_view.next_step, w, y_max)
            content = wizard.elapsed_text + "\n" + wizard.result_view.next_step
            if not wizard.preview:
                content += "\n" + C.report_aftercare(can_save=report.can_save, status=report.status, message=report.message)
            if report.evidence_error:
                content += "\n" + wizard.evidence_warning
            lines = [line for paragraph in content.split("\n") for line in _lines(paragraph, w)]
            page_size = max(1, y_max - y)
            limits_offset = min(limits_offset, max(0, len(lines) - page_size))
            for row, line in enumerate(lines[limits_offset:limits_offset + page_size], y):
                if row >= y_max:
                    break
                _add(stdscr, row, 0, line)
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
            wizard.refresh_disks()
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
        if wizard.screen in (Screen.PICK, Screen.PICK_EMPTY) and ch in (ord("o"), ord("O")) and wizard.other_devices:
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
            Screen.LIMITS,
            Screen.REPORT_HELP,
            Screen.ADVANCED,
            Screen.DONE,
            Screen.WHAT,
            Screen.METHOD,
            Screen.LAST_CHANCE,
            Screen.CONFIRM,
            Screen.KEYBOARD,
        }
        if wizard.screen in _paged and ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            delta = {curses.KEY_UP: -1, curses.KEY_DOWN: 1,
                     curses.KEY_PPAGE: -(h - 5), curses.KEY_NPAGE: h - 5}[ch]
            limits_offset = max(0, limits_offset + delta)
            continue
        if wizard.screen not in _paged:
            limits_offset = 0
        if wizard.screen == Screen.WORKING and ch == 27:
            stdscr.erase()
            _wrap(stdscr, 0, "Stopping erase. Waiting for process termination and cleanup. The disk may still be erasing.", w)
            stdscr.refresh()
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
    _add(stdscr, h - 2, 0, f"Type {action} for diagnostic report, then Enter (anything else cancels):")
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
        _add(stdscr, h - 2, 0, "Type SHUT DOWN WITHOUT SAVING; anything else returns:")
        _add(stdscr, h - 1, 0, " " * 55)
        stdscr.refresh()
        answer = stdscr.getstr(h - 1, 0, 32).decode("ascii", errors="replace")
        if answer == "SHUT DOWN WITHOUT SAVING":
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
        _add(stdscr, max(0, h - 2), 0, "Type SAVE and press Enter: ")
        stdscr.refresh()
        typed = stdscr.getstr(max(0, h - 2), 27, 8).decode("ascii", errors="ignore")
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
        mapping = {ord("1"): "us", ord("2"): "fr", ord("3"): "de"}
        if ch in mapping:
            wizard.set_keyboard_layout(mapping[ch])
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
    if wizard.screen == Screen.DONE and ch in (ord("e"), ord("E")):
        wizard.begin_evidence_retry()
        return
    if wizard.screen == Screen.SHUTDOWN_CONFIRM:
        if ch in (27, curses.KEY_ENTER, 10, 13):
            wizard.keep_report_session()
        return
    if wizard.can_open_report_help and ch in (ord("r"), ord("R")):
        wizard.open_report_help()
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
    if wizard.screen == Screen.WORKING and ch == 27:
        # Esc on WORKING now cancels visibly instead of being ignored
        try:
            wizard.cancel_wipe()
        except Exception as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("ui", "console_cancel_failed", type(exc).__name__)
            except Exception:
                pass
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
    stdscr.addstr(y, x, (text or "")[: max(0, w - 1 - x)], attr)


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


def _wrap_view(stdscr, y, view, width, y_max) -> int:
    return _wrap(stdscr, y, _identity_text(view), width, y_max)
