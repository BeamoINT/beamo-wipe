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
from beamo_wipe.models import MethodId, Screen
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.wizard import Wizard, format_progress_percent


ENTER_RELEASE_QUIET_S = 1.0


def run_console(wizard: Wizard) -> int:
    try:
        return curses.wrapper(lambda stdscr: _loop(stdscr, wizard))
    except curses.error:
        return _plain_loop(wizard)


class _InventoryRefreshed(Exception):
    pass


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
            wizard.shutdown()
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
            wizard.shutdown()
            return 0


def _plain_loop_body(wizard: Wizard) -> int:
    while not wizard.wants_shutdown:
        wizard.tick()
        screen = wizard.screen
        print("\n" + "=" * 60)
        print(C.APP_NAME, screen.value)
        if wizard.preview:
            print(C.PREVIEW_BANNER)
        print("=" * 60)
        if screen == Screen.DIAGNOSTIC:
            print(D.TITLE)
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
        if screen == Screen.WHAT:
            for b in C.WHAT_BULLETS:
                print(" -", b)
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
                print(
                    f"[{i}] {disk.display_name} {disk.size_phrase} "
                    f"{disk.path} {disk.serial}"
                )
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
                print(
                    disk.display_name,
                    disk.size_phrase,
                    disk.serial or "no serial",
                    disk.path,
                )
            print(wizard.warning_text())
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
            for card in C.METHOD_CARDS.values():
                print(f"{card['key']} {card['title']}: {card['blurb']} {card['pace']}")
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
        if screen == Screen.LAST_CHANCE:
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
            pct = "—" if wizard.progress is None else format_progress_percent(wizard.progress)
            print(C.WORKING_PULSE, pct, "  [type CANCEL then Enter to interrupt]")
            if wizard.error:
                print(wizard.error)
            if wizard.evidence_error:
                print(f"Note: {wizard.evidence_error}")
            if wizard.selected:
                print(
                    wizard.selected.display_name,
                    wizard.selected.size_phrase,
                    wizard.selected.path,
                    wizard.selected.serial or "no serial",
                )
            # Poll canonical TTY input without blocking progress updates.
            # This remains usable when the hardened kiosk disables INTR.
            try:
                ready, _w, _x = select.select([sys.stdin], [], [], 0.3)
                if ready:
                    typed = sys.stdin.readline()
                    if typed.strip().casefold() == "cancel":
                        wizard.cancel_wipe()
            except (OSError, ValueError):
                time.sleep(0.3)
            continue
        if screen == Screen.DONE:
            report = wizard.report_view
            print(wizard.method_summary)
            print(wizard.method_result)
            if report.evidence_error:
                print(f"Evidence was not saved: {report.evidence_error}")
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
                if report.can_save:
                    prompt = "Type SAVE to save the report, or SHUTDOWN: "
                else:
                    prompt = "Type SHUTDOWN: "
                action = _answer(wizard, prompt).strip().upper()
                if action == "SAVE" and report.can_save:
                    wizard.save_report_to_usb()
                elif action == "SHUTDOWN":
                    wizard.shutdown()
            continue
        if screen == Screen.REPORT_HELP:
            print(C.REPORT_HELP_TITLE)
            for paragraph in C.REPORT_HELP_SECTIONS:
                print(textwrap.fill(paragraph, 76))
                _answer(wizard, "Enter for more… ")
            print(f"{C.REPORT_WANTED}: {'yes' if wizard.report_wanted else 'no'}")
            action = _answer(wizard, "YES to want a report, NO to clear, BACK to return: ").strip().upper()
            if action in {"YES", "NO"}:
                wizard.set_report_wanted(action == "YES")
                wizard.close_report_help()
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
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.nodelay(True)
    curses.use_default_colors()
    enter_held = False
    enter_quiet_since = None
    limits_offset = 0
    inventory_open = False
    inventory_offset = 0
    while not wizard.wants_shutdown:
        wizard.tick()
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _add(stdscr, 0, 0, C.APP_NAME + "   " + wizard.screen.value, curses.A_BOLD)
        y = 2
        if wizard.preview:
            _add(stdscr, 1, 0, C.PREVIEW_BANNER)
            y = 3
        if inventory_open:
            _add(stdscr, y, 0, inventory.TITLE)
            y += 1
            lines = [line for paragraph in inventory.full_text(wizard.other_devices).split("\n")
                     for line in (textwrap.wrap(paragraph, max(10, w - 2)) or [""])]
            page_size = max(1, h - y - 2)
            inventory_offset = min(inventory_offset, max(0, len(lines) - page_size))
            for line in lines[inventory_offset:inventory_offset + page_size]:
                _add(stdscr, y, 0, line)
                y += 1
            _add(stdscr, h - 1, 0, "Read only. Up/Down, PgUp/PgDn: read. Esc: back.")
        elif wizard.screen == Screen.SPLASH:
            y = _wrap(stdscr, y, C.SPLASH_TAGLINE, w)
            _add(stdscr, y + 1, 0, "Press any key.")
        elif wizard.screen == Screen.WHAT:
            for bullet in C.WHAT_BULLETS:
                y = _wrap(stdscr, y, " * " + bullet, w) + 1
            _add(stdscr, min(h - 2, y + 2), 0, "Enter: I understand    S: shut down")
        elif wizard.screen == Screen.OWNER:
            y = _wrap(stdscr, y, C.OWNER_CHECKBOX, w)
            mark = "[X]" if wizard.owner_ok else "[ ]"
            _add(stdscr, y + 2, 0, f"{mark}  Space to check. Enter continues only when checked.")
        elif wizard.screen == Screen.PICK:
            y = _wrap(stdscr, y, C.pick_subtitle(), w) + 1
            if same_size_conflict(wizard.listed_disks):
                y = _wrap(stdscr, y, C.SAME_SIZE_HINT, w) + 1
            ordered = sorted(wizard.selectable, key=lambda d: d.path)
            for disk in ordered:
                star = ">" if wizard.selected and disk.path == wizard.selected.path else " "
                extra = ""
                if disk.is_boot:
                    extra = "  " + (
                        C.BOOT_USB_BANNER if disk.bus == "USB" else C.BOOT_DISC_BANNER
                    )
                serial = disk.serial or "no serial"
                line = (
                    f"{star} {disk.display_name}  {disk.size_phrase}  "
                    f"{disk.kind.value}  {serial}  {disk.path}{extra}"
                )
                attr = curses.A_REVERSE if star == ">" else curses.A_NORMAL
                if disk.is_boot:
                    attr = curses.A_DIM
                _add(stdscr, y, 0, line[: w - 1], attr)
                y += 1
            if wizard.other_devices:
                _add(stdscr, min(h - 3, y), 0, "Other detected devices (O): read reasons; not selectable.")
            _add(stdscr, min(h - 2, y + 1), 0, "Up/Down then Enter. Esc back.")
        elif wizard.screen == Screen.DIAGNOSTIC:
            y = _wrap(stdscr, y, D.TITLE + "\n" + D.NOTICE, w)
            y = _wrap(stdscr, y + 1, D.PREPARE, w)
            _wrap(stdscr, y + 1, wizard.diagnostic_message, w)
            action = "save diagnostic report" if wizard._diagnostic_baseline else "prepare baseline"
            _add(stdscr, h - 2, 0, "R: " + action + "    Esc: back    S: shut down")
        elif wizard.screen == Screen.PICK_BLOCKED:
            _wrap(stdscr, y, wizard.error or C.IDENTIFY_ERROR, w)
            _add(stdscr, min(h - 2, y + 4), 0, "Enter: shut down    Esc: back")
        elif wizard.screen == Screen.PICK_EMPTY:
            y = _wrap(stdscr, y, C.EMPTY_DISKS, w)
            if wizard.other_devices:
                _add(stdscr, min(h - 3, y + 1), 0, "Other detected devices (O): read reasons; not selectable.")
            _add(stdscr, h - 2, 0, "Enter: shut down    Esc: back")
        elif wizard.screen == Screen.CONFIRM and wizard.selected:
            disk = wizard.selected
            _add(stdscr, y, 0, disk.display_name, curses.A_BOLD)
            _add(stdscr, y + 2, 0, f"{disk.size_phrase}  {disk.serial}  {disk.path}")
            y = _wrap(stdscr, y + 4, wizard.warning_text(), w)
            spec = wizard.confirm
            if spec:
                y = _wrap(stdscr, y + 1, spec.prompt, w)
            curses.echo()
            curses.curs_set(1)
            stdscr.nodelay(False)
            _add(stdscr, y + 2, 0, "> " + wizard.confirm_input)
            stdscr.refresh()
            ch = stdscr.getch()
            curses.noecho()
            curses.curs_set(0)
            stdscr.nodelay(True)
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
            y = _wrap(stdscr, y, wizard.storage_notice, w) + 1
            for i, method in enumerate((MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO), 1):
                star = ">" if wizard.method == method else " "
                card = C.METHOD_CARDS[method]
                y = _wrap(stdscr, y, f"{star} {i} {card['title']}: {card['blurb']} {card['pace']}", w) + 1
            _add(stdscr, y, 0, "L: limits. A: Advanced. 1/2/3: choose. Enter: continue.")
        elif wizard.screen in {Screen.LIMITS, Screen.REPORT_HELP, Screen.ADVANCED}:
            content = limits.full_text() if wizard.screen == Screen.LIMITS else C.ADVANCED_LOG_NOTE
            if wizard.screen == Screen.REPORT_HELP:
                _add(stdscr, y, 0, f"[{'X' if wizard.report_wanted else ' '}] {C.REPORT_WANTED}")
                y += 2
                content = C.REPORT_HELP_TITLE + "\n\n" + C.REPORT_HELP_TEXT
            lines = [line for paragraph in content.split("\n")
                     for line in (textwrap.wrap(paragraph, max(10, w - 2)) or [""])]
            limits_offset = min(limits_offset, max(0, len(lines) - (h - y - 2)))
            for line in lines[limits_offset:limits_offset + max(1, h - y - 2)]:
                _add(stdscr, y, 0, line)
                y += 1
            _add(stdscr, h - 1, 0, "Arrows/Pg: read. Space: report preference. Esc: back." if wizard.screen == Screen.REPORT_HELP else "Up/Down, PgUp/PgDn: read. Esc: back.")
        elif wizard.screen == Screen.LAST_CHANCE:
            y = _wrap(stdscr, y, wizard.erase_label(), w)
            y = _wrap(stdscr, y + 1, wizard.method_summary, w)
            if wizard.error:
                _wrap(stdscr, y + 2, wizard.error, w)
            _add(stdscr, y + 3, 0, f"Wait {wizard.countdown_display}s" if not wizard.erase_enabled else "Enter to erase.")
        elif wizard.screen == Screen.WORKING:
            _add(stdscr, y, 0, C.WORKING_PULSE)
            if wizard.progress is None:
                _add(stdscr, y + 2, 0, "—")
            else:
                _add(stdscr, y + 2, 0, format_progress_percent(wizard.progress))
            if wizard.selected:
                _add(stdscr, y + 4, 0, f"{wizard.selected.display_name} {wizard.selected.size_phrase}")
                _add(
                    stdscr,
                    y + 5,
                    0,
                    f"{wizard.selected.path}  {wizard.selected.serial or 'no serial'}",
                )
            # A failed cancel stays on WORKING with wizard.error set: show it
            # so the owner knows the disk may still be erasing.
            if wizard.error:
                _wrap(stdscr, y + 6, wizard.error, w)
            _add(stdscr, y + 7, 0, "Esc: cancel erase (interrupted)")
        elif wizard.screen == Screen.DONE:
            report = wizard.report_view
            y = _wrap(stdscr, y, wizard.method_summary, w)
            y = _wrap(stdscr, y, wizard.method_result, w)
            content = wizard.result_view.next_step
            if not wizard.preview:
                content += "\n" + C.report_aftercare(can_save=report.can_save, status=report.status, message=report.message)
            if report.evidence_error:
                content += "\nEvidence was not saved: " + report.evidence_error
            lines = [line for paragraph in content.split("\n")
                     for line in (textwrap.wrap(paragraph, max(10, w - 2)) or [""])]
            page_size = max(1, h - y - 3)
            limits_offset = min(limits_offset, max(0, len(lines) - page_size))
            for row, line in enumerate(lines[limits_offset:limits_offset + page_size], y):
                _add(stdscr, row, 0, line)
            _add(stdscr, h - 1, 0, "Up/Down, PgUp/PgDn: read aftercare.")
            _add(
                stdscr,
                h - 2,
                0,
                "Enter: run again    C: close"
                if wizard.preview
                else (
                    "R: save report to one FAT32 USB    Enter: shut down"
                    if report.can_save
                    else "Enter: shut down"
                ),
            )
        if wizard.can_open_report_help and not inventory_open:
            _add(stdscr, h - 2, 0, "R: Need a report? (optional)")
        if wizard.can_refresh and not inventory_open and wizard.screen != Screen.REPORT_HELP:
            _add(stdscr, h - 1, 0, "F5: Check disks again (clears all confirmations)")
        if wizard.can_open_diagnostic:
            _add(stdscr, h - 3, 0, "D: Diagnostic report (not erase evidence)")
        stdscr.refresh()
        ch = stdscr.getch()
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
        if wizard.screen in {Screen.LIMITS, Screen.REPORT_HELP, Screen.ADVANCED, Screen.DONE} and ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            delta = {curses.KEY_UP: -1, curses.KEY_DOWN: 1,
                     curses.KEY_PPAGE: -(h - 5), curses.KEY_NPAGE: h - 5}[ch]
            limits_offset = max(0, limits_offset + delta)
            continue
        if wizard.screen not in {Screen.LIMITS, Screen.REPORT_HELP, Screen.ADVANCED, Screen.DONE}:
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
    _add(stdscr, h - 2, 0, f"Type {action} for diagnostic report, then Enter (anything else cancels):")
    stdscr.refresh()
    stdscr.timeout(-1)
    curses.echo()
    try:
        answer = stdscr.getstr(h - 1, 0, 16).decode("ascii", errors="replace").strip()
        if answer == action:
            wizard.diagnostic_action(background=True)
    finally:
        curses.noecho()
        stdscr.timeout(100)


def _confirm_report_save(stdscr, wizard: Wizard) -> None:
    """A held R cannot confirm an export; the owner must type literal SAVE."""
    h, _w = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    stdscr.nodelay(False)
    try:
        _add(stdscr, max(0, h - 2), 0, "Type SAVE and press Enter: ")
        stdscr.refresh()
        typed = stdscr.getstr(max(0, h - 2), 27, 8).decode("ascii", errors="ignore")
        if typed == "SAVE":
            wizard.save_report_to_usb()
    finally:
        curses.noecho()
        curses.curs_set(0)
        stdscr.nodelay(True)


def _handle(wizard: Wizard, ch: int) -> None:
    if wizard.can_open_report_help and ch in (ord("r"), ord("R")):
        wizard.open_report_help()
        return
    if wizard.screen == Screen.REPORT_HELP:
        if ch == ord(" "):
            wizard.set_report_wanted(not wizard.report_wanted)
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
    if wizard.screen == Screen.PICK and ch in (curses.KEY_UP, curses.KEY_DOWN):
        wizard.move_selection(-1 if ch == curses.KEY_UP else 1)
    if wizard.screen == Screen.METHOD and ch in (ord("1"), ord("2"), ord("3")):
        mapping = {ord("1"): MethodId.EVERYDAY, ord("2"): MethodId.EXTRA, ord("3"): MethodId.QUICK_ZERO}
        wizard.set_method(mapping[ch])


def _add(stdscr, y, x, text, attr=curses.A_NORMAL) -> None:
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h:
        return
    stdscr.addstr(y, x, (text or "")[: max(0, w - 1 - x)], attr)


def _wrap(stdscr, y, text, width) -> int:
    words = (text or "").split()
    line = ""
    for word in words:
        trial = (line + " " + word).strip()
        if len(trial) > width - 2:
            _add(stdscr, y, 0, line)
            y += 1
            line = word
        else:
            line = trial
    if line:
        _add(stdscr, y, 0, line)
        y += 1
    return y
