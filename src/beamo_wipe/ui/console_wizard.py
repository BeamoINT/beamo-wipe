# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard console fallback when X/Tk is unavailable. Same wizard, larger text."""

from __future__ import annotations

import curses
import time

from beamo_wipe import copy as C
from beamo_wipe.models import MethodId, Screen
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.wizard import Wizard, format_progress_percent


def run_console(wizard: Wizard) -> int:
    try:
        return curses.wrapper(lambda stdscr: _loop(stdscr, wizard))
    except curses.error:
        return _plain_loop(wizard)


def _plain_loop(wizard: Wizard) -> int:
    """Last-resort TTY with input(). Still requires confirms; never auto-wipes."""
    try:
        return _plain_loop_body(wizard)
    except EOFError:
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
        if screen == Screen.SPLASH:
            print(C.SPLASH_TAGLINE)
            input("Press Enter… ")
            wizard.skip_splash()
            continue
        if screen == Screen.WHAT:
            for b in C.WHAT_BULLETS:
                print(" -", b)
            input("Press Enter to continue… ")
            wizard.accept_what()
            continue
        if screen == Screen.OWNER:
            print(C.OWNER_CHECKBOX)
            ans = input("Type YES if that is true: ").strip()
            wizard.set_owner(ans.upper() == "YES")
            if wizard.owner_ok:
                wizard.continue_owner()
            continue
        if screen == Screen.PICK_BLOCKED:
            print(wizard.error or C.IDENTIFY_ERROR)
            input("Press Enter to shut down… ")
            wizard.shutdown()
            continue
        if screen == Screen.PICK_EMPTY:
            print(C.EMPTY_DISKS)
            input("Press Enter to shut down… ")
            wizard.shutdown()
            continue
        if screen == Screen.PICK:
            boot = wizard.discovery.boot
            if boot is not None:
                print(
                    f"[BOOT — do not erase] {boot.display_name} {boot.size_phrase} "
                    f"{boot.path} {boot.serial}"
                )
            if same_size_conflict(wizard.listed_disks):
                print(C.SAME_SIZE_HINT)
            numbered = sorted(wizard.selectable, key=lambda d: d.path)
            for i, disk in enumerate(numbered, 1):
                print(
                    f"[{i}] {disk.display_name} {disk.size_phrase} "
                    f"{disk.path} {disk.serial}"
                )
            choice = input("Number of disk to erase: ").strip()
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
            typed = input("> ")
            wizard.set_confirm_input(typed)
            if wizard.token_ok:
                wizard.continue_confirm()
            continue
        if screen == Screen.METHOD:
            print("1 Everyday  2 Extra thorough  3 Quick zero")
            print(C.SSD_FOOTER)
            choice = input("Choice [1]: ").strip() or "1"
            mapping = {"1": MethodId.EVERYDAY, "2": MethodId.EXTRA, "3": MethodId.QUICK_ZERO}
            if choice not in mapping:
                continue
            wizard.set_method(mapping[choice])
            wizard.continue_method()
            continue
        if screen == Screen.LAST_CHANCE:
            print(wizard.erase_label())
            if wizard.error:
                print(wizard.error)
            while wizard.countdown_left > 0:
                wizard.tick()
                print(f"Wait {int(wizard.countdown_left + 0.99)}…")
                time.sleep(0.4)
            ans = input("Type ERASE to start: ").strip()
            if ans.upper() == "ERASE":
                wizard.confirm_erase()
            else:
                wizard.back()
            continue
        if screen == Screen.WORKING:
            pct = "—" if wizard.progress is None else wizard.progress
            print(C.WORKING_PULSE, pct)
            if wizard.selected:
                print(
                    wizard.selected.display_name,
                    wizard.selected.size_phrase,
                    wizard.selected.path,
                    wizard.selected.serial or "no serial",
                )
            time.sleep(0.3)
            continue
        if screen == Screen.DONE:
            if wizard.preview:
                print(C.DONE_OK_PREVIEW if wizard.done_ok else C.DONE_FAIL_PREVIEW)
                ans = input("Enter to run again, or q to close… ").strip().lower()
                if ans in ("q", "quit", "close"):
                    wizard.shutdown()
                else:
                    wizard.reset_for_preview()
            else:
                print(C.DONE_OK if wizard.done_ok else C.DONE_FAIL)
                input("Press Enter to shut down… ")
                wizard.shutdown()
            continue
        if screen == Screen.ADVANCED:
            input("Press Enter to go back… ")
            wizard.close_advanced()
            continue
    return 0


def _loop(stdscr, wizard: Wizard) -> int:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.nodelay(True)
    curses.use_default_colors()
    while not wizard.wants_shutdown:
        wizard.tick()
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        _add(stdscr, 0, 0, C.APP_NAME + "   " + wizard.screen.value, curses.A_BOLD)
        y = 2
        if wizard.preview:
            _add(stdscr, 1, 0, C.PREVIEW_BANNER)
            y = 3
        if wizard.screen == Screen.SPLASH:
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
            ordered = sorted(wizard.listed_disks, key=lambda d: (d.is_boot, d.path))
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
            _add(stdscr, min(h - 2, y + 1), 0, "Up/Down then Enter. Esc back.")
        elif wizard.screen == Screen.PICK_BLOCKED:
            _wrap(stdscr, y, wizard.error or C.IDENTIFY_ERROR, w)
            _add(stdscr, min(h - 2, y + 4), 0, "Enter: shut down    Esc: back")
        elif wizard.screen == Screen.PICK_EMPTY:
            _wrap(stdscr, y, C.EMPTY_DISKS, w)
            _add(stdscr, min(h - 2, y + 4), 0, "Enter: shut down    Esc: back")
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
            elif ch in (27,):
                wizard.back()
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                wizard.set_confirm_input(wizard.confirm_input[:-1])
            elif 32 <= ch < 127:
                wizard.set_confirm_input(wizard.confirm_input + chr(ch))
            continue
        elif wizard.screen == Screen.METHOD:
            for i, method in enumerate((MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO), 1):
                star = ">" if wizard.method == method else " "
                card = C.METHOD_CARDS[method]
                _add(stdscr, y, 0, f"{star} {i} {card['title']} — {card['blurb']}"[: w - 1])
                y += 2
            _wrap(stdscr, y, C.SSD_FOOTER, w)
        elif wizard.screen == Screen.LAST_CHANCE:
            _wrap(stdscr, y, wizard.erase_label(), w)
            if wizard.error:
                _wrap(stdscr, y + 2, wizard.error, w)
            _add(stdscr, y + 3, 0, f"Wait {int(wizard.countdown_left + 0.99)}s" if wizard.countdown_left else "Enter to erase.")
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
        elif wizard.screen == Screen.DONE:
            _wrap(
                stdscr,
                y,
                (C.DONE_OK_PREVIEW if wizard.done_ok else C.DONE_FAIL_PREVIEW)
                if wizard.preview
                else (C.DONE_OK if wizard.done_ok else C.DONE_FAIL),
                w,
            )
            _add(
                stdscr,
                y + 4,
                0,
                "Enter: run again    C: close" if wizard.preview else "Enter: shut down",
            )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == -1:
            if wizard.screen in (Screen.DONE, Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
                wizard.arm_done_keyboard()
            time.sleep(0.08)
            continue
        _handle(wizard, ch)
    return 0


def _handle(wizard: Wizard, ch: int) -> None:
    if wizard.screen == Screen.SPLASH:
        wizard.skip_splash()
        return
    if ch == 27:
        wizard.back()
        return
    if ch in (ord("s"), ord("S")) and wizard.screen == Screen.WHAT:
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
