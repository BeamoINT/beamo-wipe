# SPDX-License-Identifier: GPL-3.0-or-later
"""Fullscreen Tk wizard. Huge type, one primary button, keyboard-first.

This module is a small design system on plain Tk (no assets, no themes):
tokens, canvas-drawn icons, frame-based buttons, cards, and panels. Every
screen is built from the same components so the wizard looks and behaves
consistently on the live USB (Linux Tk + DejaVu) and in ./preview.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, List, Optional

from beamo_wipe import copy as C
from beamo_wipe.methods import DEFAULT_METHOD
from beamo_wipe.models import Disk, DiskKind, MethodId, Screen
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.wizard import Wizard

# --- Design tokens ---------------------------------------------------------

BG = "#EEF1F4"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F5F8FB"
INK = "#14202E"
MUTED = "#5B6672"
FAINT = "#7E8894"
BORDER = "#D6DCE3"
BORDER_STRONG = "#B7C0CA"
NAVY = "#0B1F3A"
NAVY_MUTED = "#B9C6D8"
PRIMARY = "#1F4B99"
PRIMARY_DARK = "#173A79"
PRIMARY_TINT = "#E9F0FA"
DANGER = "#B42318"
DANGER_DARK = "#8F1B12"
DANGER_TINT = "#FCEBE8"
DANGER_BORDER = "#E5B0A8"
OK = "#177245"
OK_TINT = "#E8F4EC"
OK_BORDER = "#B7DBC5"
WARN = "#8A5A00"
WARN_BG = "#FDF3D7"
WARN_BORDER = "#E7D59B"
USB_BG = "#F0ECE2"
USB_BORDER = "#D9D0BC"
FOCUS = "#E8A317"
DISABLED_BG = "#E2E6EA"
DISABLED_FG = "#7E8894"
TRACK = "#E2E6EA"
PREVIEW_BG = "#E8A317"
PREVIEW_FG = "#0B1F3A"

CONTENT_W = 940
WRAP = CONTENT_W - 72

_STEP_ORDER = {
    Screen.WHAT: (1, "Step 1 of 8"),
    Screen.OWNER: (2, "Step 2 of 8"),
    Screen.PICK: (3, "Step 3 of 8"),
    Screen.PICK_EMPTY: (3, "Step 3 of 8"),
    Screen.PICK_BLOCKED: (3, "Step 3 of 8"),
    Screen.CONFIRM: (4, "Step 4 of 8"),
    Screen.METHOD: (5, "Step 5 of 8"),
    Screen.ADVANCED: (5, "Advanced"),
    Screen.LAST_CHANCE: (6, "Step 6 of 8"),
    Screen.WORKING: (7, "Step 7 of 8"),
    Screen.DONE: (8, "Step 8 of 8"),
}


def _family(root: tk.Tk) -> str:
    families = set(tkfont.families(root))
    for candidate in ("DejaVu Sans", "Noto Sans", "Liberation Sans", "Helvetica", "Arial"):
        if candidate in families:
            return candidate
    return "TkDefaultFont"


def _mono_family(root: tk.Tk) -> str:
    families = set(tkfont.families(root))
    for candidate in ("DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono", "Courier"):
        if candidate in families:
            return candidate
    return "TkFixedFont"


# --- Canvas icons (drawn, so they never depend on font glyph coverage) -----


def _icon_radio(parent: tk.Widget, selected: bool, size: int = 26) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 2
    ring = PRIMARY if selected else BORDER_STRONG
    cv.create_oval(pad, pad, size - pad, size - pad, outline=ring, width=2)
    if selected:
        inset = size // 4 + 1
        cv.create_oval(inset, inset, size - inset, size - inset, fill=PRIMARY, outline="")
    return cv


def _icon_check_box(parent: tk.Widget, checked: bool, size: int = 30) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 2
    if checked:
        cv.create_rectangle(
            pad, pad, size - pad, size - pad, fill=PRIMARY, outline=PRIMARY, width=2
        )
        cv.create_line(
            size * 0.28,
            size * 0.52,
            size * 0.45,
            size * 0.70,
            size * 0.74,
            size * 0.30,
            fill="#FFFFFF",
            width=3,
            capstyle="round",
            joinstyle="round",
        )
    else:
        cv.create_rectangle(
            pad, pad, size - pad, size - pad, outline=BORDER_STRONG, width=2
        )
    return cv


def _icon_no_entry(parent: tk.Widget, size: int = 26) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 3
    cv.create_oval(pad, pad, size - pad, size - pad, outline=DANGER, width=3)
    cv.create_line(
        size * 0.27, size * 0.73, size * 0.73, size * 0.27, fill=DANGER, width=3,
        capstyle="round",
    )
    return cv


def _icon_warn(
    parent: tk.Widget, size: int = 30, *, color: str = WARN, bg: str = WARN_BG
) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    cv.create_polygon(
        size / 2, 3, size - 3, size - 4, 3, size - 4,
        fill=bg, outline=color, width=2, joinstyle="round",
    )
    cv.create_line(
        size / 2, size * 0.34, size / 2, size * 0.62, fill=color, width=3,
        capstyle="round",
    )
    cv.create_oval(
        size / 2 - 2, size * 0.72, size / 2 + 2, size * 0.72 + 4, fill=color, outline=""
    )
    return cv


def _icon_info(parent: tk.Widget, size: int = 26, *, color: str = MUTED) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 2
    cv.create_oval(pad, pad, size - pad, size - pad, outline=color, width=2)
    cv.create_oval(
        size / 2 - 2, size * 0.26, size / 2 + 2, size * 0.26 + 4, fill=color, outline=""
    )
    cv.create_line(
        size / 2, size * 0.46, size / 2, size * 0.72, fill=color, width=3,
        capstyle="round",
    )
    return cv


def _icon_status(parent: tk.Widget, ok: bool, size: int = 96) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    color = OK if ok else DANGER
    cv.create_oval(2, 2, size - 2, size - 2, fill=color, outline="")
    if ok:
        cv.create_line(
            size * 0.26, size * 0.52, size * 0.44, size * 0.70, size * 0.76, size * 0.30,
            fill="#FFFFFF", width=max(4, size // 12), capstyle="round", joinstyle="round",
        )
    else:
        w = max(4, size // 12)
        cv.create_line(
            size * 0.32, size * 0.32, size * 0.68, size * 0.68,
            fill="#FFFFFF", width=w, capstyle="round",
        )
        cv.create_line(
            size * 0.32, size * 0.68, size * 0.68, size * 0.32,
            fill="#FFFFFF", width=w, capstyle="round",
        )
    return cv


# --- Components ------------------------------------------------------------

_VARIANTS = {
    "primary": (PRIMARY, "#FFFFFF", PRIMARY_DARK),
    "danger": (DANGER, "#FFFFFF", DANGER_DARK),
    "secondary": ("#E4E8ED", INK, "#D3D9E0"),
}


class _Button(tk.Frame):
    """Frame-based button: identical rendering on Linux Tk and macOS preview."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        text: str,
        command: Callable[[], None],
        font: tkfont.Font,
        variant: str = "secondary",
        enabled: bool = True,
    ) -> None:
        self._variant = variant
        self._command = command
        self._enabled = enabled
        bg, fg, _hover = _VARIANTS[variant]
        super().__init__(
            parent,
            bg=bg if enabled else DISABLED_BG,
            highlightthickness=2,
            highlightcolor=FOCUS,
            highlightbackground=BG,
            cursor="hand2" if enabled else "arrow",
            takefocus=1 if enabled else 0,
        )
        self._label = tk.Label(
            self,
            text=text,
            font=font,
            bg=self.cget("bg"),
            fg=fg if enabled else DISABLED_FG,
            padx=26,
            pady=12,
        )
        self._label.pack()
        for widget in (self, self._label):
            widget.bind("<Button-1>", self._click)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)
        self.bind("<space>", self._key)

    def _click(self, _event=None) -> str:
        self.focus_set()
        if self._enabled and self._command is not None:
            self._command()
        return "break"

    def _key(self, _event=None) -> str:
        if self._enabled and self._command is not None:
            self._command()
        return "break"

    def _enter(self, _event=None) -> None:
        if self._enabled:
            self._paint(_VARIANTS[self._variant][2])

    def _leave(self, _event=None) -> None:
        if self._enabled:
            self._paint(_VARIANTS[self._variant][0])

    def _paint(self, bg: str, fg: Optional[str] = None) -> None:
        self.configure(bg=bg)
        if fg is not None:
            self._label.configure(bg=bg, fg=fg)
        else:
            self._label.configure(bg=bg)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        bg, fg, _hover = _VARIANTS[self._variant]
        self._paint(bg if enabled else DISABLED_BG, fg if enabled else DISABLED_FG)
        self.configure(
            cursor="hand2" if enabled else "arrow",
            takefocus=1 if enabled else 0,
        )


class TkWizard:
    def __init__(self, wizard: Wizard, fullscreen: bool = False) -> None:
        self.w = wizard
        self.root = tk.Tk()
        title = C.APP_NAME
        if wizard.preview:
            title = f"{C.APP_NAME} — PREVIEW (nothing is erased)"
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.minsize(1024, 700)
        if fullscreen:
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("1280x820")
        family = _family(self.root)
        mono = _mono_family(self.root)
        self.font_display = tkfont.Font(root=self.root, family=family, size=40, weight="bold")
        self.font_h = tkfont.Font(root=self.root, family=family, size=30, weight="bold")
        self.font_lead = tkfont.Font(root=self.root, family=family, size=20)
        self.font_b = tkfont.Font(root=self.root, family=family, size=18)
        self.font_bold = tkfont.Font(root=self.root, family=family, size=18, weight="bold")
        self.font_s = tkfont.Font(root=self.root, family=family, size=15)
        self.font_s_bold = tkfont.Font(root=self.root, family=family, size=15, weight="bold")
        self.font_tiny = tkfont.Font(root=self.root, family=family, size=13, weight="bold")
        self.font_btn = tkfont.Font(root=self.root, family=family, size=19, weight="bold")
        self.font_mono = tkfont.Font(root=self.root, family=mono, size=16)
        self.font_mono_sm = tkfont.Font(root=self.root, family=mono, size=14)
        self.font_entry = tkfont.Font(root=self.root, family=mono, size=28, weight="bold")
        self.font_stat = tkfont.Font(root=self.root, family=family, size=54, weight="bold")
        self.font_brand = tkfont.Font(root=self.root, family=family, size=20, weight="bold")
        self._confirm_var = tk.StringVar()
        self._owner_var = tk.IntVar(value=0)
        self._body: Optional[tk.Frame] = None
        self._footer: Optional[tk.Frame] = None
        self._header_step: Optional[tk.Label] = None
        self._strip: Optional[tk.Canvas] = None
        self._hint: Optional[tk.Label] = None
        self._primary: Optional[_Button] = None
        self._countdown_num: Optional[tk.Label] = None
        self._countdown_label: Optional[tk.Label] = None
        self._progress_label: Optional[tk.Label] = None
        self._progress_pct: Optional[tk.Label] = None
        self._progress_bar: Optional[tk.Canvas] = None
        self._match_label: Optional[tk.Label] = None
        self._shown: Optional[Screen] = None
        self._primary_cmd: Optional[Callable[[], None]] = None
        self._after_id: Optional[str] = None
        self._build_chrome()
        self._confirm_var.trace_add("write", self._confirm_var_written)
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<Return>", self._on_return)
        self.root.bind("<Key>", self._on_key)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._draw()
        self._after_id = self.root.after(100, self._tick)

    # -- chrome -------------------------------------------------------------

    def _build_chrome(self) -> None:
        if self.w.preview:
            stripe = tk.Frame(self.root, bg=PREVIEW_BG, height=42)
            stripe.pack(fill=tk.X)
            stripe.pack_propagate(False)
            tk.Label(
                stripe,
                text=C.PREVIEW_BANNER,
                fg=PREVIEW_FG,
                bg=PREVIEW_BG,
                font=self.font_s_bold,
            ).pack(side=tk.LEFT, padx=24, pady=8)
        header = tk.Frame(self.root, bg=NAVY, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header,
            text=C.APP_NAME,
            fg="#FFFFFF",
            bg=NAVY,
            font=self.font_brand,
        ).pack(side=tk.LEFT, padx=28)
        self._header_step = tk.Label(
            header, text="", fg=NAVY_MUTED, bg=NAVY, font=self.font_s
        )
        self._header_step.pack(side=tk.RIGHT, padx=28)
        self._strip = tk.Canvas(self.root, height=6, bg=TRACK, highlightthickness=0)
        self._strip.pack(fill=tk.X)
        self._strip.bind("<Configure>", lambda _e: self._draw_strip())
        self._body = tk.Frame(self.root, bg=BG)
        self._body.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        self._footer = tk.Frame(self.root, bg=BG)
        self._footer.pack(fill=tk.X, side=tk.BOTTOM)
        for area, expand in ((self._body, True), (self._footer, False)):
            area.grid_columnconfigure(0, weight=1)
            area.grid_columnconfigure(1, minsize=CONTENT_W, weight=0)
            area.grid_columnconfigure(2, weight=1)
            area.grid_rowconfigure(0, weight=1 if expand else 0)

    def _draw_strip(self) -> None:
        cv = self._strip
        if cv is None:
            return
        cv.delete("all")
        width = cv.winfo_width()
        if width <= 1:
            return
        step = _STEP_ORDER.get(self.w.screen, (0, ""))[0]
        total = 8
        gap = 4
        seg = max(1, (width - (total - 1) * gap) / total)
        for i in range(step):
            x0 = i * (seg + gap)
            cv.create_rectangle(x0, 0, x0 + seg, 6, fill=PRIMARY, outline="")

    def _column(self, parent: tk.Widget, *, fill_height: bool) -> tk.Frame:
        col = tk.Frame(parent, bg=BG)
        col.grid(row=0, column=1, sticky="nsew" if fill_height else "ew")
        return col

    def _clear(self, frame: tk.Frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _nav(self, fn: Callable[[], None]) -> Callable[[], None]:
        def wrapped() -> None:
            fn()
            if self.w.wants_shutdown:
                self._teardown()
                return
            self._draw()

        return wrapped

    def _teardown(self) -> None:
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self.root.destroy()

    def _tick(self) -> None:
        try:
            prev = self.w.screen
            self.w.tick()
            if self.w.wants_shutdown:
                self._teardown()
                return
            if self.w.screen != prev:
                self._draw()
            elif self.w.screen == Screen.LAST_CHANCE:
                self._refresh_last_chance()
            elif self.w.screen == Screen.WORKING:
                self._refresh_working()
            self._after_id = self.root.after(100, self._tick)
        except tk.TclError:
            self._after_id = None

    def _draw(self) -> None:
        assert self._body is not None and self._footer is not None
        self._header_step.configure(text=_STEP_ORDER.get(self.w.screen, (0, ""))[1])
        self._clear(self._body)
        self._clear(self._footer)
        self._primary = None
        self._primary_cmd = None
        self._countdown_num = None
        self._countdown_label = None
        self._progress_label = None
        self._progress_pct = None
        self._progress_bar = None
        self._match_label = None
        screen = self.w.screen
        dispatch = {
            Screen.SPLASH: self._splash,
            Screen.WHAT: self._what,
            Screen.OWNER: self._owner,
            Screen.PICK: self._pick,
            Screen.PICK_BLOCKED: self._blocked,
            Screen.PICK_EMPTY: self._empty,
            Screen.CONFIRM: self._confirm,
            Screen.METHOD: self._method,
            Screen.LAST_CHANCE: self._last,
            Screen.WORKING: self._working,
            Screen.DONE: self._done,
            Screen.ADVANCED: self._advanced,
        }
        dispatch[screen]()
        self._draw_strip()
        self._shown = screen

    # -- text / small components --------------------------------------------

    def _h(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent, text=text, font=self.font_h, fg=INK, bg=BG,
            wraplength=WRAP, justify=tk.LEFT,
        )

    def _p(self, parent: tk.Widget, text: str, **kw) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            font=kw.get("font", self.font_lead),
            fg=kw.get("fg", INK),
            bg=kw.get("bg", BG),
            wraplength=kw.get("wraplength", WRAP),
            justify=tk.LEFT,
            anchor="w",
        )

    def _chip(
        self, parent: tk.Widget, text: str, *, fg: str, bg: str, border: str
    ) -> tk.Frame:
        chip = tk.Frame(parent, bg=bg, highlightbackground=border, highlightthickness=1)
        chip._no_tint = True  # type: ignore[attr-defined]
        label = tk.Label(chip, text=text, font=self.font_tiny, fg=fg, bg=bg, padx=8, pady=2)
        label.pack()
        return chip

    def _panel(self, parent: tk.Widget, *, kind: str, text: str) -> tk.Frame:
        colors = {
            "warn": (WARN_BG, WARN_BORDER),
            "danger": (DANGER_TINT, DANGER_BORDER),
            "info": (SURFACE_ALT, BORDER),
        }
        bg, border = colors[kind]
        outer = tk.Frame(parent, bg=border)
        inner = tk.Frame(outer, bg=bg)
        inner.pack(fill=tk.BOTH, padx=2, pady=2)
        row = tk.Frame(inner, bg=bg)
        row.pack(fill=tk.X, padx=16, pady=14)
        if kind == "warn":
            icon = _icon_warn(row, 30)
        elif kind == "danger":
            icon = _icon_warn(row, 30, color=DANGER, bg=DANGER_TINT)
        else:
            icon = _icon_info(row, 26)
        icon.configure(bg=bg)
        icon.pack(side=tk.LEFT, anchor="n", pady=2)
        tk.Label(
            row, text=text, font=self.font_b, fg=INK, bg=bg,
            wraplength=WRAP - 110, justify=tk.LEFT, anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        return outer

    def _tint_widget(self, widget: tk.Widget, bg: Optional[str]) -> None:
        if getattr(widget, "_no_tint", False):
            return
        if bg is None:
            orig = getattr(widget, "_orig_bg", None)
            if orig is not None:
                try:
                    widget.configure(bg=orig)
                except tk.TclError:
                    pass
        else:
            if not hasattr(widget, "_orig_bg"):
                try:
                    widget._orig_bg = widget.cget("bg")  # type: ignore[attr-defined]
                except tk.TclError:
                    widget._orig_bg = None  # type: ignore[attr-defined]
            try:
                widget.configure(bg=bg)
            except tk.TclError:
                pass
        for child in widget.winfo_children():
            self._tint_widget(child, bg)

    # -- footer / buttons -----------------------------------------------------

    def _close_label(self) -> str:
        return C.BTN_CLOSE_PREVIEW if self.w.preview else C.BTN_SHUTDOWN

    def _footer_shell(self, hint: str) -> tk.Frame:
        assert self._footer is not None
        col = self._column(self._footer, fill_height=False)
        tk.Frame(col, bg=BORDER, height=1).pack(fill=tk.X)
        self._hint = tk.Label(
            col, text=hint, font=self.font_s, fg=MUTED, bg=BG, anchor="w"
        )
        self._hint.pack(fill=tk.X, pady=(10, 0))
        row = tk.Frame(col, bg=BG)
        row.pack(fill=tk.X, pady=(10, 22))
        return row

    def _back_btn(self, row: tk.Frame) -> None:
        _Button(
            row,
            text=C.BTN_BACK,
            command=self._nav(self.w.back),
            font=self.font_btn,
            variant="secondary",
        ).pack(side=tk.LEFT)

    def _secondary_btn(self, row: tk.Frame, text: str, command: Callable[[], None]) -> _Button:
        btn = _Button(
            row,
            text=text,
            command=self._nav(command),
            font=self.font_btn,
            variant="secondary",
        )
        btn.pack(side=tk.LEFT)
        return btn

    def _primary_btn(
        self,
        row: tk.Frame,
        text: str,
        command: Callable[[], None],
        enabled: bool = True,
        danger: bool = False,
    ) -> _Button:
        self._primary_cmd = command
        btn = _Button(
            row,
            text=text,
            command=self._nav(command),
            font=self.font_btn,
            variant="danger" if danger else "primary",
            enabled=enabled,
        )
        btn.pack(side=tk.RIGHT)
        self._primary = btn
        return btn

    def _set_primary_enabled(self, enabled: bool, danger: bool = False) -> None:
        if self._primary is None:
            return
        self._primary.set_enabled(enabled)

    # -- screens ---------------------------------------------------------------

    def _splash(self) -> None:
        col = self._column(self._body, fill_height=True)
        tk.Frame(col, bg=BG, height=80).pack()
        tk.Label(
            col, text=C.APP_NAME, font=self.font_display, fg=NAVY, bg=BG, anchor="w"
        ).pack(fill=tk.X)
        bar = tk.Canvas(col, width=120, height=6, bg=BG, highlightthickness=0)
        bar.create_rectangle(0, 0, 120, 6, fill=PREVIEW_BG, outline="")
        bar.pack(anchor="w", pady=(18, 26))
        self._p(col, C.SPLASH_TAGLINE).pack(fill=tk.X)
        self._p(col, "Press any key to continue.", fg=MUTED, font=self.font_b).pack(
            fill=tk.X, pady=(26, 0)
        )
        row = self._footer_shell(C.HINT_SPLASH)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.skip_splash)

    def _what(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "What this is").pack(fill=tk.X, pady=(28, 18))
        card = tk.Frame(col, bg=BORDER)
        card.pack(fill=tk.X)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill=tk.BOTH, padx=2, pady=2)
        for i, bullet in enumerate(C.WHAT_BULLETS):
            line = tk.Frame(inner, bg=SURFACE)
            line.pack(fill=tk.X, padx=20, pady=(16 if i == 0 else 12, 0))
            tk.Label(
                line, text="•", font=self.font_bold, fg=PRIMARY, bg=SURFACE
            ).pack(side=tk.LEFT, anchor="n")
            tk.Label(
                line, text=bullet, font=self.font_lead, fg=INK, bg=SURFACE,
                wraplength=WRAP - 92, justify=tk.LEFT, anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0))
        tk.Frame(inner, bg=SURFACE, height=16).pack()
        self._p(col, C.ENGINE_LINE, fg=MUTED, font=self.font_s).pack(fill=tk.X, pady=(20, 6))
        self._p(col, C.SECURE_BOOT_HINT, fg=MUTED, font=self.font_s).pack(fill=tk.X)
        row = self._footer_shell(C.HINT_DEFAULT)
        self._secondary_btn(row, self._close_label(), self.w.shutdown)
        self._primary_btn(row, C.BTN_UNDERSTAND, self.w.accept_what)

    def _owner(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._owner_var.set(1 if self.w.owner_ok else 0)
        self._h(col, "You must be the owner").pack(fill=tk.X, pady=(28, 14))
        self._p(col, C.OWNER_LEAD).pack(fill=tk.X, pady=(0, 22))
        checked = bool(self.w.owner_ok)
        border = PRIMARY if checked else BORDER_STRONG
        bg = PRIMARY_TINT if checked else SURFACE
        card = tk.Frame(
            col,
            bg=border,
            cursor="hand2",
            takefocus=1,
            highlightthickness=2,
            highlightcolor=FOCUS,
            highlightbackground=BG,
        )
        card.pack(fill=tk.X)
        inner = tk.Frame(card, bg=bg)
        inner.pack(fill=tk.BOTH, padx=3, pady=3)
        box = _icon_check_box(inner, checked, 30)
        box.configure(bg=bg)
        box.pack(side=tk.LEFT, padx=(18, 0), pady=18)
        text = tk.Label(
            inner,
            text=C.OWNER_CHECKBOX,
            font=self.font_lead,
            fg=INK,
            bg=bg,
            wraplength=WRAP - 130,
            justify=tk.LEFT,
            anchor="w",
        )
        text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=18, pady=18)
        for widget in (card, inner, box, text):
            widget.bind("<Button-1>", self._owner_clicked)
        card.bind("<space>", self._owner_clicked)
        card.focus_set()
        row = self._footer_shell(C.HINT_OWNER)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_owner, enabled=self.w.owner_ok)

    def _owner_clicked(self, _event=None) -> str:
        self._owner_var.set(0 if self._owner_var.get() else 1)
        self._owner_toggled()
        return "break"

    def _owner_toggled(self) -> None:
        self.w.set_owner(bool(self._owner_var.get()))
        self._draw()

    def _disk_card(self, parent: tk.Widget, disk: Disk, selected: bool) -> None:
        border = USB_BORDER if disk.is_boot else (PRIMARY if selected else BORDER)
        bg = USB_BG if disk.is_boot else (PRIMARY_TINT if selected else SURFACE)
        card = tk.Frame(parent, bg=border)
        card.pack(fill=tk.X, pady=6, padx=2)
        inner = tk.Frame(card, bg=bg)
        inner.pack(fill=tk.BOTH, padx=3, pady=3)
        top = tk.Frame(inner, bg=bg)
        top.pack(fill=tk.X, padx=16, pady=(14, 0))
        if disk.is_boot:
            icon = _icon_no_entry(top, 26)
        else:
            icon = _icon_radio(top, selected, 26)
        icon.configure(bg=bg)
        icon.pack(side=tk.LEFT, anchor="n", pady=2)
        title_col = tk.Frame(top, bg=bg)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        title_row = tk.Frame(title_col, bg=bg)
        title_row.pack(fill=tk.X)
        tk.Label(
            title_row, text=disk.display_name, font=self.font_bold, fg=INK, bg=bg, anchor="w"
        ).pack(side=tk.LEFT)
        self._chip(
            title_row, disk.kind.value, fg=MUTED, bg=SURFACE_ALT, border=BORDER
        ).pack(side=tk.LEFT, padx=(12, 0))
        tk.Label(
            top, text=disk.size_phrase, font=self.font_bold, fg=INK, bg=bg, anchor="e"
        ).pack(side=tk.RIGHT)
        meta = tk.Frame(title_col, bg=bg)
        meta.pack(fill=tk.X, pady=(4, 0))
        tk.Label(
            meta, text=f"{disk.bus}   Serial ", font=self.font_s, fg=MUTED, bg=bg, anchor="w"
        ).pack(side=tk.LEFT)
        tk.Label(
            meta, text=disk.serial or "no serial", font=self.font_mono, fg=INK, bg=bg,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Label(
            meta, text="   Device ", font=self.font_s, fg=MUTED, bg=bg, anchor="w"
        ).pack(side=tk.LEFT)
        tk.Label(
            meta, text=disk.path, font=self.font_mono, fg=MUTED, bg=bg, anchor="w"
        ).pack(side=tk.LEFT)
        tail = tk.Frame(inner, bg=bg)
        tail.pack(fill=tk.X, padx=16, pady=(6, 14))
        if disk.is_boot:
            banner = C.BOOT_USB_BANNER if disk.bus == "USB" else C.BOOT_DISC_BANNER
            tk.Label(
                tail, text=banner, font=self.font_s_bold, fg=DANGER, bg=bg, anchor="w"
            ).pack(fill=tk.X)
        else:
            def _click(_e, p=disk.path):
                self._click_disk(p)
                return "break"

            def _enter(_e, i=inner, s=selected):
                if not s:
                    self._tint_widget(i, SURFACE_ALT)

            def _leave(_e, i=inner, s=selected):
                if not s:
                    self._tint_widget(i, None)

            card.bind("<Button-1>", _click)
            inner.bind("<Button-1>", _click)
            self._bind_tree(inner, _click)
            card.configure(cursor="hand2")
            inner.configure(cursor="hand2")
            card.bind("<Enter>", _enter)
            card.bind("<Leave>", _leave)

    def _bind_tree(self, widget: tk.Widget, click) -> None:
        for child in widget.winfo_children():
            child.bind("<Button-1>", click)
            self._bind_tree(child, click)

    def _pick(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "Pick a disk").pack(fill=tk.X, pady=(24, 8))
        self._p(col, C.pick_subtitle(), fg=MUTED, font=self.font_b).pack(fill=tk.X, pady=(0, 12))
        if same_size_conflict(self.w.selectable):
            self._panel(col, kind="warn", text=C.SAME_SIZE_HINT).pack(fill=tk.X, pady=(0, 10))
        if self.w.selected and self.w.selected.kind in (DiskKind.SSD, DiskKind.NVME):
            self._panel(col, kind="info", text=C.SSD_FOOTER).pack(fill=tk.X, pady=(0, 10))
        list_wrap = tk.Frame(col, bg=BG)
        list_wrap.pack(fill=tk.BOTH, expand=True, pady=(2, 8))
        canvas = tk.Canvas(list_wrap, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(
            list_wrap, orient=tk.VERTICAL, command=canvas.yview, width=16, troughcolor=BG
        )
        cards = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=cards, anchor="nw")

        def _stretch(_event=None) -> None:
            canvas.itemconfigure(window_id, width=max(1, canvas.winfo_width()))
            canvas.configure(scrollregion=canvas.bbox("all"))

        cards.bind("<Configure>", _stretch)
        canvas.bind("<Configure>", _stretch)
        canvas.configure(yscrollcommand=scroll.set)

        def _wheel(event) -> Optional[str]:
            if getattr(event, "num", None) == 5:
                steps = 1
            elif getattr(event, "num", None) == 4:
                steps = -1
            elif event.delta:
                steps = -1 if event.delta > 0 else 1
            else:
                return None
            canvas.yview_scroll(steps, "units")
            return "break"

        for widget in (canvas, cards):
            widget.bind("<MouseWheel>", _wheel)
            widget.bind("<Button-4>", _wheel)
            widget.bind("<Button-5>", _wheel)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        items: List = sorted(self.w.discovery.disks, key=lambda d: (d.is_boot, d.path))
        for disk in items:
            selected = self.w.selected is not None and disk.path == self.w.selected.path
            self._disk_card(cards, disk, selected)
        row = self._footer_shell(C.HINT_PICK)
        self._back_btn(row)
        can = self.w.selected is not None and not self.w.selected.is_boot
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_pick, enabled=can)

    def _click_disk(self, path: str) -> None:
        self.w.select_disk(path)
        self._draw()

    def _blocked(self) -> None:
        col = self._column(self._body, fill_height=True)
        tk.Frame(col, bg=BG, height=48).pack()
        icon = _icon_warn(col, 72)
        icon.configure(bg=BG)
        icon.pack(anchor="w", pady=(0, 18))
        self._h(col, "Stop").pack(fill=tk.X, pady=(0, 14))
        self._p(col, self.w.error or C.IDENTIFY_ERROR).pack(fill=tk.X)
        row = self._footer_shell(C.HINT_DEFAULT)
        self._back_btn(row)
        self._primary_btn(row, self._close_label(), self.w.shutdown)

    def _empty(self) -> None:
        col = self._column(self._body, fill_height=True)
        tk.Frame(col, bg=BG, height=48).pack()
        icon = _icon_info(col, 64)
        icon.configure(bg=BG)
        icon.pack(anchor="w", pady=(0, 18))
        self._h(col, "No disk to erase").pack(fill=tk.X, pady=(0, 14))
        self._p(col, C.EMPTY_DISKS).pack(fill=tk.X)
        row = self._footer_shell(C.HINT_DEFAULT)
        self._back_btn(row)
        self._primary_btn(row, self._close_label(), self.w.shutdown)

    def _confirm(self) -> None:
        disk = self.w.selected
        assert disk is not None
        spec = self.w.confirm
        assert spec is not None
        col = self._column(self._body, fill_height=True)
        self._h(col, "Confirm the disk").pack(fill=tk.X, pady=(24, 14))
        card = tk.Frame(col, bg=BORDER)
        card.pack(fill=tk.X)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill=tk.BOTH, padx=2, pady=2)
        top = tk.Frame(inner, bg=SURFACE)
        top.pack(fill=tk.X, padx=18, pady=(16, 0))
        tk.Label(
            top, text=disk.display_name, font=self.font_bold, fg=INK, bg=SURFACE, anchor="w"
        ).pack(side=tk.LEFT)
        tk.Label(
            top, text=disk.size_phrase, font=self.font_bold, fg=INK, bg=SURFACE, anchor="e"
        ).pack(side=tk.RIGHT)
        meta = tk.Frame(inner, bg=SURFACE)
        meta.pack(fill=tk.X, padx=18, pady=(6, 16))
        self._chip(meta, disk.kind.value, fg=MUTED, bg=SURFACE_ALT, border=BORDER).pack(
            side=tk.LEFT
        )
        tk.Label(meta, text="Serial ", font=self.font_s, fg=MUTED, bg=SURFACE).pack(
            side=tk.LEFT, padx=(14, 0)
        )
        tk.Label(
            meta, text=disk.serial or "no serial", font=self.font_mono, fg=INK, bg=SURFACE
        ).pack(side=tk.LEFT)
        tk.Label(meta, text="Device ", font=self.font_s, fg=MUTED, bg=SURFACE).pack(
            side=tk.LEFT, padx=(14, 0)
        )
        tk.Label(meta, text=disk.path, font=self.font_mono, fg=MUTED, bg=SURFACE).pack(
            side=tk.LEFT
        )
        self._panel(col, kind="warn", text=self.w.warning_text()).pack(fill=tk.X, pady=14)
        self._p(col, spec.prompt).pack(fill=tk.X, pady=(4, 8))
        entry = tk.Entry(
            col,
            textvariable=self._confirm_var,
            font=self.font_entry,
            fg=INK,
            bg=SURFACE,
            insertbackground=INK,
            relief=tk.FLAT,
            highlightthickness=2,
            highlightcolor=FOCUS,
            highlightbackground=BORDER_STRONG,
        )
        self._confirm_var.set(self.w.confirm_input)
        entry.pack(fill=tk.X, pady=(0, 8), ipady=10)
        entry.focus_set()
        self._match_label = tk.Label(
            col,
            text=C.CONFIRM_MATCH_OK if self.w.token_ok else C.CONFIRM_MATCH_WAIT,
            font=self.font_s,
            fg=OK if self.w.token_ok else MUTED,
            bg=BG,
            anchor="w",
        )
        self._match_label.pack(fill=tk.X)
        row = self._footer_shell(C.HINT_CONFIRM)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_confirm, enabled=self.w.token_ok)

    def _confirm_var_written(self, *_a) -> None:
        if self.w.screen != Screen.CONFIRM:
            return
        self.w.set_confirm_input(self._confirm_var.get())
        self._set_primary_enabled(self.w.token_ok)
        if self._match_label is not None:
            if self.w.token_ok:
                self._match_label.configure(text=C.CONFIRM_MATCH_OK, fg=OK)
            else:
                self._match_label.configure(text=C.CONFIRM_MATCH_WAIT, fg=MUTED)

    def _method_card(self, parent: tk.Widget, method: MethodId) -> None:
        card_copy = C.METHOD_CARDS[method]
        selected = self.w.method == method
        border = PRIMARY if selected else BORDER
        bg = PRIMARY_TINT if selected else SURFACE
        card = tk.Frame(parent, bg=border, cursor="hand2")
        card.pack(fill=tk.X, pady=6)
        inner = tk.Frame(card, bg=bg)
        inner.pack(fill=tk.BOTH, padx=3, pady=3)
        top = tk.Frame(inner, bg=bg)
        top.pack(fill=tk.X, padx=16, pady=(12, 0))
        icon = _icon_radio(top, selected, 26)
        icon.configure(bg=bg)
        icon.pack(side=tk.LEFT, anchor="n", pady=2)
        title_row = tk.Frame(top, bg=bg)
        title_row.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        self._chip(
            title_row, card_copy["key"], fg=MUTED, bg=SURFACE_ALT, border=BORDER
        ).pack(side=tk.LEFT)
        tk.Label(
            title_row, text=card_copy["title"], font=self.font_bold, fg=INK, bg=bg, anchor="w"
        ).pack(side=tk.LEFT, padx=(12, 0))
        if method == DEFAULT_METHOD:
            self._chip(
                title_row, C.RECOMMENDED_TAG, fg=OK, bg=OK_TINT, border=OK_BORDER
            ).pack(side=tk.LEFT, padx=(12, 0))
        for text in (card_copy["blurb"], card_copy["pace"]):
            tk.Label(
                inner,
                text=text,
                font=self.font_s,
                fg=MUTED,
                bg=bg,
                wraplength=WRAP - 110,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=(56, 16), pady=(2, 0))
        tk.Frame(inner, bg=bg, height=12).pack()

        def _click(_e, m=method):
            self._choose_method(m)
            return "break"

        card.bind("<Button-1>", _click)
        inner.bind("<Button-1>", _click)
        self._bind_tree(inner, _click)

    def _method(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "How thorough").pack(fill=tk.X, pady=(24, 12))
        for method in (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO):
            self._method_card(col, method)
        self._panel(col, kind="info", text=C.SSD_FOOTER).pack(fill=tk.X, pady=(8, 6))
        adv = tk.Label(
            col,
            text=C.BTN_ADVANCED,
            font=self.font_s_bold,
            fg=PRIMARY,
            bg=BG,
            cursor="hand2",
            anchor="w",
            takefocus=1,
            highlightthickness=2,
            highlightcolor=FOCUS,
            highlightbackground=BG,
            padx=2,
            pady=2,
        )
        adv.pack(anchor="w", pady=(2, 0))
        adv.bind("<Button-1>", lambda _e: self._nav(self.w.open_advanced)())
        adv.bind("<space>", lambda _e: self._nav(self.w.open_advanced)() or "break")
        row = self._footer_shell(C.HINT_METHOD)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_method)

    def _choose_method(self, method: MethodId) -> None:
        self.w.set_method(method)
        self._draw()

    def _last(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "Last chance").pack(fill=tk.X, pady=(24, 14))
        self._panel(col, kind="danger", text=self.w.erase_label()).pack(fill=tk.X)
        count = tk.Frame(col, bg=BG)
        count.pack(anchor="w", pady=(22, 0))
        self._countdown_num = tk.Label(
            count, text="", font=self.font_stat, fg=INK, bg=BG, anchor="w"
        )
        self._countdown_num.pack(side=tk.LEFT)
        self._countdown_label = tk.Label(
            count, text="", font=self.font_b, fg=MUTED, bg=BG, anchor="w", justify=tk.LEFT
        )
        self._countdown_label.pack(side=tk.LEFT, padx=(16, 0), pady=(18, 0))
        row = self._footer_shell(C.HINT_DEFAULT)
        self._back_btn(row)
        self._primary_btn(
            row,
            C.BTN_ERASE,
            self.w.confirm_erase,
            enabled=self.w.erase_enabled,
            danger=True,
        )
        self._refresh_last_chance()

    def _refresh_last_chance(self) -> None:
        if self._countdown_label is None or self._countdown_num is None:
            return
        left = int(self.w.countdown_left + 0.99)
        if left > 0:
            self._countdown_num.configure(text=str(left), fg=INK)
            self._countdown_label.configure(text=C.COUNTDOWN_CAPTION, fg=MUTED)
        else:
            self._countdown_num.configure(text="✓", fg=OK)
            self._countdown_label.configure(text=C.COUNTDOWN_READY, fg=OK)
        self._set_primary_enabled(self.w.erase_enabled, danger=True)

    def _working(self) -> None:
        col = self._column(self._body, fill_height=True)
        disk = self.w.selected
        self._h(col, "Working").pack(fill=tk.X, pady=(24, 14))
        if disk is not None:
            card = tk.Frame(col, bg=BORDER)
            card.pack(fill=tk.X)
            inner = tk.Frame(card, bg=SURFACE)
            inner.pack(fill=tk.BOTH, padx=2, pady=2)
            tk.Label(
                inner,
                text=f"{disk.display_name}    {disk.size_phrase}",
                font=self.font_bold,
                fg=INK,
                bg=SURFACE,
                anchor="w",
            ).pack(fill=tk.X, padx=18, pady=(14, 0))
            tk.Label(
                inner,
                text=disk.path,
                font=self.font_mono,
                fg=MUTED,
                bg=SURFACE,
                anchor="w",
            ).pack(fill=tk.X, padx=18, pady=(4, 14))
        card_copy = C.METHOD_CARDS[self.w.method]
        self._progress_pct = tk.Label(
            col, text="", font=self.font_stat, fg=INK, bg=BG, anchor="w"
        )
        self._progress_pct.pack(fill=tk.X, pady=(26, 6))
        bar = tk.Canvas(col, height=32, bg=TRACK, highlightthickness=0)
        bar.pack(fill=tk.X)
        bar.bind("<Configure>", lambda _e: self._refresh_working())
        self._progress_bar = bar
        self._progress_label = self._p(
            col, f"{card_copy['title']}.  {C.WORKING_PULSE}", fg=MUTED, font=self.font_b
        )
        self._progress_label.pack(fill=tk.X, pady=(14, 0))
        self._footer_shell(C.HINT_WORKING)
        self._refresh_working()

    def _refresh_working(self) -> None:
        if self._progress_label is None:
            return
        pulse = f"{C.METHOD_CARDS[self.w.method]['title']}.  {C.WORKING_PULSE}"
        pct = self.w.progress
        if pct is None:
            if self._progress_pct is not None:
                self._progress_pct.configure(text="…")
            self._progress_label.configure(text=pulse)
            self._paint_bar(0.02)
        else:
            if self._progress_pct is not None:
                self._progress_pct.configure(text=f"{pct:.0f}%")
            self._progress_label.configure(text=pulse)
            self._paint_bar(max(0.02, pct / 100.0))

    def _paint_bar(self, frac: float) -> None:
        bar = self._progress_bar
        if bar is None:
            return
        bar.delete("fill")
        width = max(bar.winfo_width(), 1)
        bar.create_rectangle(
            0, 0, width * min(1.0, frac), 32, fill=PRIMARY, outline="", tags="fill"
        )

    def _done(self) -> None:
        col = self._column(self._body, fill_height=True)
        ok = self.w.done_ok
        title = "Finished" if ok else "The wipe did not finish"
        color = OK if ok else DANGER
        tk.Frame(col, bg=BG, height=36).pack()
        icon = _icon_status(col, ok, 96)
        icon.configure(bg=BG)
        icon.pack(anchor="w", pady=(0, 18))
        self._h(col, title).pack(fill=tk.X, pady=(0, 12))
        if self.w.preview:
            msg = C.DONE_OK_PREVIEW if ok else C.DONE_FAIL_PREVIEW
        else:
            msg = C.DONE_OK if ok else C.DONE_FAIL
        self._p(col, msg, fg=color).pack(fill=tk.X)
        if self.w.selected is not None:
            self._p(
                col,
                f"{self.w.selected.display_name}    {self.w.selected.size_phrase}",
                fg=MUTED,
                font=self.font_b,
            ).pack(fill=tk.X, pady=(16, 0))
        row = self._footer_shell(C.HINT_DEFAULT)
        if self.w.preview:
            self._secondary_btn(row, C.BTN_CLOSE_PREVIEW, self.w.shutdown)
            self._primary_btn(row, C.BTN_RUN_AGAIN, self.w.reset_for_preview)
        else:
            self._primary_btn(row, C.BTN_SHUTDOWN, self.w.shutdown)

    def _advanced(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "Advanced").pack(fill=tk.X, pady=(24, 10))
        self._p(col, C.ADVANCED_LEAD, fg=MUTED, font=self.font_b).pack(fill=tk.X, pady=(0, 12))
        from beamo_wipe.methods import METHODS

        card = tk.Frame(col, bg=BORDER)
        card.pack(fill=tk.X)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill=tk.BOTH, padx=2, pady=2)
        count = len(METHODS)
        for i, spec in enumerate(METHODS.values()):
            tk.Label(
                inner,
                text=f"{spec.method_id.value}: nwipe --method={spec.nwipe_method}  ({spec.docs_name})",
                font=self.font_mono_sm,
                fg=INK,
                bg=SURFACE,
                anchor="w",
            ).pack(
                fill=tk.X,
                padx=18,
                pady=(14 if i == 0 else 6, 14 if i == count - 1 else 6),
            )
        log = self.w._wipe_request.logfile if self.w._wipe_request else "(no wipe yet)"
        log_row = tk.Frame(col, bg=BG)
        log_row.pack(fill=tk.X, pady=(16, 6))
        tk.Label(
            log_row, text="Log file (never on the target disk): ", font=self.font_s,
            fg=MUTED, bg=BG, anchor="w",
        ).pack(side=tk.LEFT)
        tk.Label(
            log_row, text=log, font=self.font_mono, fg=INK, bg=BG, anchor="w"
        ).pack(side=tk.LEFT)
        self._p(col, C.ADVANCED_LOG_NOTE, fg=MUTED, font=self.font_s).pack(fill=tk.X)
        row = self._footer_shell(C.HINT_DEFAULT)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.close_advanced)

    # -- keyboard ------------------------------------------------------------

    def _on_escape(self, _event=None) -> str:
        if self.w.screen not in (Screen.SPLASH, Screen.WHAT, Screen.WORKING, Screen.DONE):
            self.w.back()
            self._draw()
        return "break"

    def _on_return(self, _event=None) -> str:
        screen = self.w.screen
        before = screen
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
            if self.w.preview:
                self.w.reset_for_preview()
            else:
                self.w.shutdown()
        elif screen == Screen.ADVANCED:
            self.w.close_advanced()
        elif screen in (Screen.PICK_BLOCKED, Screen.PICK_EMPTY):
            self.w.shutdown()
        if self.w.wants_shutdown:
            self._teardown()
            return "break"
        if self.w.screen != before or screen != Screen.CONFIRM:
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
            self.w.move_selection(-1 if event.keysym == "Up" else 1)
            self._draw()
            return "break"
        if self.w.screen == Screen.METHOD and event.char in ("1", "2", "3"):
            mapping = {"1": MethodId.EVERYDAY, "2": MethodId.EXTRA, "3": MethodId.QUICK_ZERO}
            self.w.set_method(mapping[event.char])
            self._draw()
            return "break"
        return None

    def _close(self) -> None:
        if self.w.screen == Screen.WORKING and not self.w.preview:
            return
        self.w.shutdown()
        self._teardown()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def run_tk(wizard: Wizard, fullscreen: bool = False) -> int:
    ui = TkWizard(wizard, fullscreen=fullscreen)
    return ui.run()
