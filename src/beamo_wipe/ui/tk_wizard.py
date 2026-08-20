# SPDX-License-Identifier: GPL-3.0-or-later
"""Fullscreen Tk wizard. Huge type, one primary button, keyboard-first."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import List, Optional

from beamo_wipe import copy as C
from beamo_wipe.models import MethodId, Screen
from beamo_wipe.wizard import Wizard

BG = "#F4F0E6"
HEADER = "#0B1F3A"
INK = "#1A1A1A"
MUTED = "#4A4A4A"
CARD = "#FFFFFF"
BORDER = "#C9C3B6"
SEL = "#1F4B99"
PRIMARY = "#1F4B99"
PRIMARY_FG = "#FFFFFF"
DANGER = "#B42318"
DISABLED = "#9A958A"
USB_BG = "#EEE9DC"
WARN = "#F8E6B0"
OK = "#0F7B3C"
FOCUS = "#E8A317"


def _family(root: tk.Tk) -> str:
    names = set(tkfont.names(root))
    families = set(tkfont.families(root))
    for candidate in ("DejaVu Sans", "Noto Sans", "Liberation Sans", "Helvetica", "Arial"):
        if candidate in families:
            return candidate
    del names
    return "TkDefaultFont"


class TkWizard:
    def __init__(self, wizard: Wizard, fullscreen: bool = False) -> None:
        self.w = wizard
        self.root = tk.Tk()
        self.root.title(C.APP_NAME)
        self.root.configure(bg=BG)
        self.root.minsize(1024, 700)
        if fullscreen:
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("1280x800")
        family = _family(self.root)
        self.font_h = tkfont.Font(root=self.root, family=family, size=36, weight="bold")
        self.font_b = tkfont.Font(root=self.root, family=family, size=22)
        self.font_s = tkfont.Font(root=self.root, family=family, size=16)
        self.font_btn = tkfont.Font(root=self.root, family=family, size=22, weight="bold")
        self._pick_index = 0
        self._confirm_var = tk.StringVar()
        self._owner_var = tk.IntVar(value=0)
        self._body: Optional[tk.Frame] = None
        self._footer: Optional[tk.Frame] = None
        self._header_step: Optional[tk.Label] = None
        self._primary: Optional[tk.Button] = None
        self._shown = None
        self._build_chrome()
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<Return>", self._on_return)
        self.root.bind("<Key>", self._on_key)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._draw()
        self.root.after(100, self._tick)

    def _build_chrome(self) -> None:
        header = tk.Frame(self.root, bg=HEADER, height=72)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header,
            text=C.APP_NAME,
            fg="#FFFFFF",
            bg=HEADER,
            font=self.font_btn,
        ).pack(side=tk.LEFT, padx=28)
        self._header_step = tk.Label(
            header, text="", fg="#D6DEEA", bg=HEADER, font=self.font_s
        )
        self._header_step.pack(side=tk.RIGHT, padx=28)
        self._body = tk.Frame(self.root, bg=BG)
        self._body.pack(fill=tk.BOTH, expand=True, padx=40, pady=24)
        self._footer = tk.Frame(self.root, bg=BG)
        self._footer.pack(fill=tk.X, padx=40, pady=(0, 28))

    def _clear(self, frame: tk.Frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _tick(self) -> None:
        prev = self.w.screen
        self.w.tick()
        if self.w.wants_shutdown:
            self.root.destroy()
            return
        if self.w.screen != prev or self.w.screen in (
            Screen.LAST_CHANCE,
            Screen.WORKING,
            Screen.SPLASH,
        ):
            self._draw()
        self.root.after(100, self._tick)

    def _steps(self) -> str:
        order = {
            Screen.WHAT: "Step 1 of 8",
            Screen.OWNER: "Step 2 of 8",
            Screen.PICK: "Step 3 of 8",
            Screen.PICK_EMPTY: "Step 3 of 8",
            Screen.PICK_BLOCKED: "Step 3 of 8",
            Screen.CONFIRM: "Step 4 of 8",
            Screen.METHOD: "Step 5 of 8",
            Screen.LAST_CHANCE: "Step 6 of 8",
            Screen.WORKING: "Step 7 of 8",
            Screen.DONE: "Step 8 of 8",
        }
        return order.get(self.w.screen, "")

    def _draw(self) -> None:
        assert self._body is not None and self._footer is not None
        self._header_step.configure(text=self._steps())
        self._clear(self._body)
        self._clear(self._footer)
        self._primary = None
        screen = self.w.screen
        if screen == Screen.SPLASH:
            self._splash()
        elif screen == Screen.WHAT:
            self._what()
        elif screen == Screen.OWNER:
            self._owner()
        elif screen == Screen.PICK:
            self._pick()
        elif screen == Screen.PICK_BLOCKED:
            self._blocked()
        elif screen == Screen.PICK_EMPTY:
            self._empty()
        elif screen == Screen.CONFIRM:
            self._confirm()
        elif screen == Screen.METHOD:
            self._method()
        elif screen == Screen.LAST_CHANCE:
            self._last()
        elif screen == Screen.WORKING:
            self._working()
        elif screen == Screen.DONE:
            self._done()
        elif screen == Screen.ADVANCED:
            self._advanced()
        self._shown = screen

    def _h(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(parent, text=text, font=self.font_h, fg=INK, bg=BG, wraplength=1100, justify=tk.LEFT)

    def _p(self, parent: tk.Widget, text: str, **kw) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            font=self.font_b,
            fg=kw.get("fg", INK),
            bg=kw.get("bg", BG),
            wraplength=kw.get("wraplength", 1100),
            justify=tk.LEFT,
            anchor="w",
        )

    def _back_btn(self, enabled: bool = True) -> None:
        assert self._footer is not None
        btn = tk.Button(
            self._footer,
            text=C.BTN_BACK,
            font=self.font_btn,
            command=self.w.back,
            takefocus=1,
            highlightthickness=3,
            highlightcolor=FOCUS,
            padx=18,
            pady=10,
        )
        if not enabled:
            btn.configure(state=tk.DISABLED)
        btn.pack(side=tk.LEFT)

    def _primary_btn(
        self,
        text: str,
        command,
        enabled: bool = True,
        danger: bool = False,
    ) -> tk.Button:
        assert self._footer is not None
        bg = DANGER if danger else PRIMARY
        fg = PRIMARY_FG
        if not enabled:
            bg = DISABLED
            fg = "#F4F0E6"
        btn = tk.Button(
            self._footer,
            text=text,
            font=self.font_btn,
            command=command if enabled else (lambda: None),
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief=tk.FLAT,
            padx=28,
            pady=12,
            takefocus=1 if enabled else 0,
            highlightthickness=3,
            highlightcolor=FOCUS,
            state=tk.NORMAL if enabled else tk.DISABLED,
        )
        btn.pack(side=tk.RIGHT)
        self._primary = btn
        return btn

    def _splash(self) -> None:
        self._h(self._body, C.APP_NAME).pack(anchor="w", pady=(40, 16))
        self._p(self._body, C.SPLASH_TAGLINE).pack(anchor="w")
        self._p(self._body, "Press any key to continue.", fg=MUTED).pack(anchor="w", pady=24)

    def _what(self) -> None:
        self._h(self._body, "What this is").pack(anchor="w", pady=(0, 16))
        for bullet in C.WHAT_BULLETS:
            self._p(self._body, f"•  {bullet}").pack(anchor="w", pady=8)
        self._p(self._body, C.ENGINE_LINE, fg=MUTED).pack(anchor="w", pady=(24, 8))
        self._p(self._body, C.SECURE_BOOT_HINT, fg=MUTED).pack(anchor="w")
        tk.Button(
            self._footer,
            text=C.BTN_SHUTDOWN,
            font=self.font_btn,
            command=self.w.shutdown,
            takefocus=1,
            highlightthickness=3,
            highlightcolor=FOCUS,
            padx=18,
            pady=10,
        ).pack(side=tk.LEFT)
        self._primary_btn(C.BTN_UNDERSTAND, self.w.accept_what)

    def _owner(self) -> None:
        self._h(self._body, "You must be the owner").pack(anchor="w", pady=(0, 20))
        self._p(
            self._body,
            "Check the box only if this is your computer, or you have written permission.",
        ).pack(anchor="w", pady=(0, 24))
        box = tk.Checkbutton(
            self._body,
            text=C.OWNER_CHECKBOX,
            font=self.font_b,
            variable=self._owner_var,
            command=self._owner_toggled,
            bg=BG,
            fg=INK,
            wraplength=1000,
            justify=tk.LEFT,
            anchor="w",
            takefocus=1,
            highlightthickness=3,
            highlightcolor=FOCUS,
            selectcolor=CARD,
        )
        box.pack(anchor="w")
        box.focus_set()
        self._back_btn()
        self._primary_btn(C.BTN_CONTINUE, self.w.continue_owner, enabled=self.w.owner_ok)

    def _owner_toggled(self) -> None:
        self.w.set_owner(bool(self._owner_var.get()))
        self._draw()

    def _pick(self) -> None:
        self._h(self._body, "Pick a disk").pack(anchor="w", pady=(0, 8))
        self._p(self._body, C.pick_subtitle(), fg=MUTED).pack(anchor="w", pady=(0, 16))
        cards = tk.Frame(self._body, bg=BG)
        cards.pack(fill=tk.BOTH, expand=True)
        items: List = list(self.w.discovery.disks)
        if self.w.selected is None:
            first = next((d for d in items if not d.is_boot), None)
            if first is not None:
                self.w.select_disk(first.path)
        for disk in items:
            selected = self.w.selected is not None and disk.path == self.w.selected.path
            bg = USB_BG if disk.is_boot else CARD
            highlight = SEL if selected and not disk.is_boot else BORDER
            card = tk.Frame(cards, bg=bg, highlightbackground=highlight, highlightthickness=4)
            card.pack(fill=tk.X, pady=8)
            title = f"{disk.display_name}    {disk.size_phrase}    {disk.kind.value}"
            tk.Label(card, text=title, font=self.font_b, bg=bg, fg=INK, anchor="w").pack(
                fill=tk.X, padx=16, pady=(12, 0)
            )
            detail = f"{disk.bus}   {disk.serial or 'no serial'}   {disk.path}"
            tk.Label(card, text=detail, font=self.font_s, bg=bg, fg=MUTED, anchor="w").pack(
                fill=tk.X, padx=16, pady=(0, 8)
            )
            if disk.is_boot:
                banner = C.BOOT_USB_BANNER if disk.bus == "USB" else C.BOOT_DISC_BANNER
                tk.Label(card, text=banner, font=self.font_b, bg=bg, fg=DANGER, anchor="w").pack(
                    fill=tk.X, padx=16, pady=(0, 12)
                )
            else:
                card.bind("<Button-1>", lambda _e, p=disk.path: self._click_disk(p))
                for child in card.winfo_children():
                    child.bind("<Button-1>", lambda _e, p=disk.path: self._click_disk(p))
        self._back_btn()
        self._primary_btn(
            C.BTN_CONTINUE,
            self.w.continue_pick,
            enabled=self.w.selected is not None and not self.w.selected.is_boot,
        )

    def _click_disk(self, path: str) -> None:
        self.w.select_disk(path)
        self._draw()

    def _blocked(self) -> None:
        self._h(self._body, "Stop").pack(anchor="w", pady=(0, 16))
        self._p(self._body, self.w.error or C.IDENTIFY_ERROR).pack(anchor="w")
        self._back_btn()
        self._primary_btn(C.BTN_SHUTDOWN, self.w.shutdown)

    def _empty(self) -> None:
        self._h(self._body, "No disk to erase").pack(anchor="w", pady=(0, 16))
        self._p(self._body, C.EMPTY_DISKS).pack(anchor="w")
        self._back_btn()
        self._primary_btn(C.BTN_SHUTDOWN, self.w.shutdown)

    def _confirm(self) -> None:
        disk = self.w.selected
        assert disk is not None
        spec = self.w.confirm
        assert spec is not None
        self._h(self._body, "Confirm the disk").pack(anchor="w", pady=(0, 12))
        card = tk.Frame(self._body, bg=WARN, highlightthickness=0)
        card.pack(fill=tk.X, pady=12)
        tk.Label(card, text=disk.display_name, font=self.font_h, bg=WARN, fg=INK).pack(
            anchor="w", padx=20, pady=(18, 0)
        )
        tk.Label(
            card,
            text=f"{disk.size_phrase}    {disk.kind.value}    {disk.serial or 'no serial'}",
            font=self.font_b,
            bg=WARN,
            fg=INK,
        ).pack(anchor="w", padx=20, pady=(8, 18))
        self._p(self._body, self.w.warning_text()).pack(anchor="w", pady=(12, 16))
        self._p(self._body, spec.prompt).pack(anchor="w", pady=(0, 8))
        entry = tk.Entry(
            self._body,
            textvariable=self._confirm_var,
            font=self.font_h,
            fg=INK,
            bg=CARD,
            highlightthickness=3,
            highlightcolor=FOCUS,
        )
        self._confirm_var.set(self.w.confirm_input)
        entry.pack(fill=tk.X, pady=8, ipady=8)
        entry.focus_set()

        def on_change(*_a) -> None:
            self.w.set_confirm_input(self._confirm_var.get())
            # Refresh only the primary enabled state without stealing focus.
            if self._primary is not None:
                state = tk.NORMAL if self.w.token_ok else tk.DISABLED
                self._primary.configure(state=state)
                if self.w.token_ok:
                    self._primary.configure(bg=PRIMARY, fg=PRIMARY_FG)
                else:
                    self._primary.configure(bg=DISABLED, fg="#F4F0E6")

        self._confirm_var.trace_add("write", on_change)
        self._back_btn()
        self._primary_btn(C.BTN_CONTINUE, self.w.continue_confirm, enabled=self.w.token_ok)

    def _method(self) -> None:
        self._h(self._body, "How thorough").pack(anchor="w", pady=(0, 12))
        for method in (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO):
            card_copy = C.METHOD_CARDS[method]
            selected = self.w.method == method
            border = SEL if selected else BORDER
            card = tk.Frame(self._body, bg=CARD, highlightbackground=border, highlightthickness=4)
            card.pack(fill=tk.X, pady=8)
            tk.Label(
                card,
                text=f"{card_copy['key']}   {card_copy['title']}",
                font=self.font_b,
                bg=CARD,
                fg=INK,
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(12, 0))
            tk.Label(
                card,
                text=card_copy["blurb"],
                font=self.font_s,
                bg=CARD,
                fg=MUTED,
                wraplength=1000,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=16, pady=(4, 12))
            card.bind("<Button-1>", lambda _e, m=method: self._choose_method(m))
            for child in card.winfo_children():
                child.bind("<Button-1>", lambda _e, m=method: self._choose_method(m))
        self._p(self._body, C.SSD_FOOTER, fg=MUTED).pack(anchor="w", pady=12)
        adv = tk.Button(
            self._body,
            text=C.BTN_ADVANCED,
            font=self.font_s,
            command=self.w.open_advanced,
            takefocus=1,
            highlightthickness=3,
            highlightcolor=FOCUS,
            relief=tk.FLAT,
            bg=BG,
            fg=SEL,
        )
        adv.pack(anchor="w")
        self._back_btn()
        self._primary_btn(C.BTN_CONTINUE, self.w.continue_method)

    def _choose_method(self, method: MethodId) -> None:
        self.w.set_method(method)
        self._draw()

    def _last(self) -> None:
        self._h(self._body, "Last chance").pack(anchor="w", pady=(0, 16))
        self._p(self._body, self.w.erase_label()).pack(anchor="w")
        left = int(self.w.countdown_left + 0.99)
        if left > 0:
            self._p(self._body, f"Wait {left} seconds…", fg=MUTED).pack(anchor="w", pady=16)
        else:
            self._p(self._body, "The Erase button is ready.", fg=MUTED).pack(anchor="w", pady=16)
        self._back_btn()
        self._primary_btn(
            C.BTN_ERASE,
            self.w.confirm_erase,
            enabled=self.w.erase_enabled,
            danger=True,
        )

    def _working(self) -> None:
        disk = self.w.selected
        self._h(self._body, "Working").pack(anchor="w", pady=(0, 16))
        if disk is not None:
            self._p(self._body, f"{disk.display_name}    {disk.size_phrase}    {disk.path}").pack(
                anchor="w"
            )
        pct = self.w.progress
        if pct is None:
            self._p(self._body, C.WORKING_PULSE).pack(anchor="w", pady=20)
        else:
            self._p(self._body, f"{pct:.0f}%    {C.WORKING_PULSE}").pack(anchor="w", pady=20)
            bar = tk.Frame(self._body, bg=BORDER, height=28)
            bar.pack(fill=tk.X, pady=8)
            fill = tk.Frame(bar, bg=SEL, height=28, width=max(8, int(11 * pct)))
            fill.place(relwidth=max(0.01, pct / 100.0), relheight=1)

    def _done(self) -> None:
        ok = self.w.done_ok
        title = "Finished" if ok else "The wipe did not finish"
        color = OK if ok else DANGER
        self._h(self._body, title).pack(anchor="w", pady=(0, 16))
        msg = C.DONE_OK if ok else C.DONE_FAIL
        self._p(self._body, msg, fg=color).pack(anchor="w")
        if self.w.selected is not None:
            self._p(
                self._body,
                f"{self.w.selected.display_name}    {self.w.selected.size_phrase}",
                fg=MUTED,
            ).pack(anchor="w", pady=16)
        self._primary_btn(C.BTN_SHUTDOWN, self.w.shutdown)

    def _advanced(self) -> None:
        self._h(self._body, "Advanced").pack(anchor="w", pady=(0, 12))
        self._p(
            self._body,
            "Raw nwipe method names. Technicians only. The happy-path screens stay simple.",
        ).pack(anchor="w", pady=(0, 12))
        from beamo_wipe.methods import METHODS

        for spec in METHODS.values():
            self._p(
                self._body,
                f"{spec.method_id.value}: nwipe --method={spec.nwipe_method}  ({spec.docs_name})",
            ).pack(anchor="w", pady=4)
        log = self.w._wipe_request.logfile if self.w._wipe_request else "(no wipe yet)"
        self._p(self._body, f"Log file (never on the target disk): {log}", fg=MUTED).pack(
            anchor="w", pady=16
        )
        self._p(
            self._body,
            "To save a log, plug in a second USB that is not the target disk and copy the log file there.",
            fg=MUTED,
        ).pack(anchor="w")
        self._back_btn()
        self._primary_btn(C.BTN_CONTINUE, self.w.close_advanced)

    def _on_escape(self, _event=None) -> None:
        if self.w.screen not in (Screen.SPLASH, Screen.WHAT, Screen.WORKING, Screen.DONE):
            self.w.back()
            self._draw()

    def _on_return(self, _event=None) -> str:
        screen = self.w.screen
        if screen == Screen.SPLASH:
            self.w.skip_splash()
        elif screen == Screen.WHAT:
            self.w.accept_what()
        elif screen == Screen.OWNER and self.w.owner_ok:
            self.w.continue_owner()
        elif screen == Screen.PICK:
            self.w.continue_pick()
        elif screen == Screen.CONFIRM and self.w.token_ok:
            self.w.continue_confirm()
        elif screen == Screen.METHOD:
            self.w.continue_method()
        elif screen == Screen.LAST_CHANCE and self.w.erase_enabled:
            self.w.confirm_erase()
        elif screen == Screen.DONE:
            self.w.shutdown()
        elif screen == Screen.ADVANCED:
            self.w.close_advanced()
        elif screen in (Screen.PICK_BLOCKED, Screen.PICK_EMPTY):
            self.w.shutdown()
        self._draw()
        return "break"

    def _on_key(self, event) -> Optional[str]:
        if event.keysym in ("Return", "Escape", "Tab"):
            return None
        if self.w.screen == Screen.SPLASH:
            self.w.skip_splash()
            self._draw()
            return "break"
        if self.w.screen == Screen.OWNER and event.keysym == "space":
            self.w.set_owner(not self.w.owner_ok)
            self._owner_var.set(1 if self.w.owner_ok else 0)
            self._draw()
            return "break"
        if self.w.screen == Screen.PICK and event.keysym in ("Up", "Down"):
            selectable = list(self.w.selectable)
            if not selectable:
                return "break"
            paths = [d.path for d in selectable]
            current = self.w.selected.path if self.w.selected else paths[0]
            idx = paths.index(current) if current in paths else 0
            idx = idx - 1 if event.keysym == "Up" else idx + 1
            idx = max(0, min(len(paths) - 1, idx))
            self.w.select_disk(paths[idx])
            self._draw()
            return "break"
        if self.w.screen == Screen.METHOD and event.char in ("1", "2", "3"):
            mapping = {"1": MethodId.EVERYDAY, "2": MethodId.EXTRA, "3": MethodId.QUICK_ZERO}
            self.w.set_method(mapping[event.char])
            self._draw()
            return "break"
        return None

    def _close(self) -> None:
        if self.w.screen == Screen.WORKING:
            return
        self.w.shutdown()
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def run_tk(wizard: Wizard, fullscreen: bool = False) -> int:
    ui = TkWizard(wizard, fullscreen=fullscreen)
    return ui.run()
