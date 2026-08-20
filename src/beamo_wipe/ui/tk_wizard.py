# SPDX-License-Identifier: GPL-3.0-or-later
"""Fullscreen Tk wizard. Huge type, one primary button, keyboard-first.

This module is a small design system on plain Tk (no assets, no themes):
tokens, canvas-drawn rounded components (buttons, cards, chips, panels,
progress bars, key-caps, a countdown ring), and canvas icons. Every screen
is built from the same components so the wizard looks and behaves
consistently on the live USB (Linux Tk + DejaVu) and in ./preview.

Design rules:
- One card pattern: white, rounded, soft shadow, hairline border.
- One selectable pattern: radio/checkbox card; selected = primary tint +
  primary ring; hover = alt surface; keyboard focus = focus ring.
- One alert pattern: filled badge icon + text (warn / danger / info).
- One status pattern: centered icon, title, message (blocked/empty/done).
- Keyboard affordances are drawn as key-caps, not buried in prose.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, List, Optional

from beamo_wipe import copy as C
from beamo_wipe.methods import DEFAULT_METHOD
from beamo_wipe.models import Disk, DiskKind, MethodId, Screen
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.wizard import COUNTDOWN_S, Wizard

# --- Design tokens ---------------------------------------------------------

BG = "#E9EDF4"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F2F5FA"
INK = "#0E1B2C"
MUTED = "#43506A"
BORDER = "#D6DDE7"
# Strong border: also the unchecked radio/checkbox/key-cap outline, so it
# must stay >= 3:1 on every surface (WCAG non-text contrast).
BORDER_STRONG = "#7A89A1"
NAVY = "#0A1C36"
NAVY_SOFT = "#16315C"
NAVY_MUTED = "#C9D6E8"
NAVY_TEXT = "#D9E2F0"
PRIMARY = "#2456C7"
PRIMARY_DARK = "#1C44A3"
PRIMARY_PRESS = "#16357E"
PRIMARY_TINT = "#E8EEFB"
DANGER = "#B42318"
DANGER_DARK = "#8F1B12"
DANGER_PRESS = "#6F140D"
DANGER_TINT = "#FBEBE8"
DANGER_BORDER = "#E5A89E"
OK = "#166E43"
OK_TINT = "#E6F2EA"
WARN = "#7A5200"
WARN_BG = "#FBF0D3"
WARN_BORDER = "#E3CE93"
USB_BG = "#F3EEE2"
USB_BORDER = "#D8CDB4"
FOCUS = "#1C44A3"
ACCENT = "#E8A317"
DISABLED_BG = "#E2E6EC"
DISABLED_FG = "#7A8494"
TRACK = "#DCE2EB"
SHADOW_A = "#D8DFE9"
SHADOW_B = "#E3E8F0"
PREVIEW_BG = "#E8A317"
PREVIEW_FG = "#0A1C36"

CONTENT_W = 940
WRAP = CONTENT_W - 72
RADIUS = 16
SHADOW_H = 6

_STEP_ORDER = {
    Screen.WHAT: (1, "Step 1 of 8", "What this is"),
    Screen.OWNER: (2, "Step 2 of 8", "Ownership"),
    Screen.PICK: (3, "Step 3 of 8", "Pick a disk"),
    Screen.PICK_EMPTY: (3, "Step 3 of 8", "Pick a disk"),
    Screen.PICK_BLOCKED: (3, "Step 3 of 8", "Pick a disk"),
    Screen.CONFIRM: (4, "Step 4 of 8", "Confirm the disk"),
    Screen.METHOD: (5, "Step 5 of 8", "How thorough"),
    Screen.ADVANCED: (5, "Advanced", "Advanced"),
    Screen.LAST_CHANCE: (6, "Step 6 of 8", "Last chance"),
    Screen.WORKING: (7, "Step 7 of 8", "Erasing"),
    Screen.DONE: (8, "Step 8 of 8", "Finished"),
}

# Spans of hint copy that render as key-caps instead of plain text.
_KEY_TOKEN_RE = re.compile(r"(Up/Down|1, 2, or 3|any key|Enter|Esc|Space)")
_KEY_TOKEN_KEYS = {
    "Up/Down": ("↑", "↓"),
    "1, 2, or 3": ("1", "2", "3"),
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


# --- Rounded rectangles ----------------------------------------------------


def _rr_points(x0: float, y0: float, x1: float, y1: float, r: float) -> List[float]:
    r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    return [
        x0 + r, y0,
        x1 - r, y0,
        x1, y0,
        x1, y0 + r,
        x1, y1 - r,
        x1, y1,
        x1 - r, y1,
        x0 + r, y1,
        x0, y1,
        x0, y1 - r,
        x0, y0 + r,
        x0, y0,
    ]


def _round_rect(canvas: tk.Canvas, x0, y0, x1, y1, r, **kwargs) -> int:
    return canvas.create_polygon(
        _rr_points(x0, y0, x1, y1, r), smooth=True, splinesteps=36, **kwargs
    )


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


def _icon_check_box(parent: tk.Widget, checked: bool, size: int = 32) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 2
    if checked:
        _round_rect(
            cv, pad, pad, size - pad, size - pad, 8,
            fill=PRIMARY, outline=PRIMARY, width=2,
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
        _round_rect(
            cv, pad, pad, size - pad, size - pad, 8,
            fill=SURFACE, outline=BORDER_STRONG, width=2,
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


def _icon_alert(parent: tk.Widget, kind: str, size: int = 34) -> tk.Canvas:
    """Filled badge: triangle for warn/danger, circle for info. White glyph."""
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    if kind == "info":
        color = PRIMARY
        cv.create_oval(2, 2, size - 2, size - 2, fill=color, outline="")
        cv.create_oval(
            size / 2 - 2.5, size * 0.24, size / 2 + 2.5, size * 0.24 + 5,
            fill="#FFFFFF", outline="",
        )
        cv.create_line(
            size / 2, size * 0.46, size / 2, size * 0.74,
            fill="#FFFFFF", width=3, capstyle="round",
        )
    else:
        color = WARN if kind == "warn" else DANGER
        cv.create_polygon(
            size / 2, 2, size - 2, size - 3, 2, size - 3,
            fill=color, outline=color, width=6, joinstyle="round",
        )
        cv.create_line(
            size / 2, size * 0.36, size / 2, size * 0.62,
            fill="#FFFFFF", width=3, capstyle="round",
        )
        cv.create_oval(
            size / 2 - 2, size * 0.72, size / 2 + 2, size * 0.72 + 4,
            fill="#FFFFFF", outline="",
        )
    return cv


def _icon_status(parent: tk.Widget, ok: bool, size: int = 104) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    color = OK if ok else DANGER
    tint = OK_TINT if ok else DANGER_TINT
    cv.create_oval(1, 1, size - 1, size - 1, fill=tint, outline="")
    pad = size // 8
    cv.create_oval(pad, pad, size - pad, size - pad, fill=color, outline="")
    cx0, cy0, cx1, cy1 = pad, pad, size - pad, size - pad
    if ok:
        cv.create_line(
            cx0 + (cx1 - cx0) * 0.22, cy0 + (cy1 - cy0) * 0.52,
            cx0 + (cx1 - cx0) * 0.42, cy0 + (cy1 - cy0) * 0.72,
            cx0 + (cx1 - cx0) * 0.78, cy0 + (cy1 - cy0) * 0.28,
            fill="#FFFFFF", width=max(5, size // 14), capstyle="round", joinstyle="round",
        )
    else:
        w = max(5, size // 14)
        cv.create_line(
            cx0 + (cx1 - cx0) * 0.30, cy0 + (cy1 - cy0) * 0.30,
            cx0 + (cx1 - cx0) * 0.70, cy0 + (cy1 - cy0) * 0.70,
            fill="#FFFFFF", width=w, capstyle="round",
        )
        cv.create_line(
            cx0 + (cx1 - cx0) * 0.30, cy0 + (cy1 - cy0) * 0.70,
            cx0 + (cx1 - cx0) * 0.70, cy0 + (cy1 - cy0) * 0.30,
            fill="#FFFFFF", width=w, capstyle="round",
        )
    return cv


# --- Components ------------------------------------------------------------


class _Box(tk.Canvas):
    """Rounded-rectangle container hosting one inner frame of widgets.

    The canvas background shows through at the rounded corners, so it always
    matches the parent surface. Content lives in ``self.inner``. With
    ``shadow=True`` the card gets a soft two-layer drop shadow (the canvas
    reserves SHADOW_H pixels at the bottom for it).
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        radius: int = RADIUS,
        fill: str = SURFACE,
        outline: Optional[str] = BORDER,
        ow: int = 1,
        padx: int = 18,
        pady: int = 14,
        bg: Optional[str] = None,
        ring: bool = False,
        shadow: bool = False,
    ) -> None:
        super().__init__(
            parent,
            highlightthickness=0,
            bd=0,
            bg=bg if bg is not None else parent.cget("bg"),
            takefocus=0,
        )
        self._radius = radius
        self._fill = fill
        self._outline = outline
        self._ow = ow
        self._padx = padx
        self._pady = pady
        self._ring = ring
        self._shadow = shadow
        self._focused = False
        self.inner = tk.Frame(self, bg=fill)
        self._win = self.create_window(padx, pady, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._sync_height)
        self.bind("<Configure>", self._sync_width)

    def _sync_height(self, _event=None) -> None:
        need_h = self.inner.winfo_reqheight() + 2 * self._pady + self._shadow_h
        if self.winfo_height() != need_h:
            self.configure(height=need_h)
        # Hug the content width only when no parent has stretched us (we are
        # unmapped, or our actual size still equals our own request). fill=X
        # parents own the width instead.
        need_w = self.inner.winfo_reqwidth() + 2 * self._padx
        if need_w > 1 and (
            self.winfo_width() <= 1 or self.winfo_width() == self.winfo_reqwidth()
        ):
            self.configure(width=need_w)
        self._redraw()

    @property
    def _shadow_h(self) -> int:
        return SHADOW_H if self._shadow else 0

    def _sync_width(self, _event=None) -> None:
        width = self.winfo_width()
        if width > 1:
            self.itemconfigure(self._win, width=max(1, width - 2 * self._padx))
        self._redraw()

    def _redraw(self) -> None:
        self.delete("rr")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1:
            return
        inset = 3 if self._ring else 1
        bottom = height - inset - self._shadow_h
        if self._shadow:
            _round_rect(
                self, inset + 1, inset + 4, width - inset - 1, bottom + 4,
                self._radius, fill=SHADOW_B, outline="", tags="rr",
            )
            _round_rect(
                self, inset, inset + 2, width - inset, bottom + 2,
                self._radius, fill=SHADOW_A, outline="", tags="rr",
            )
        if self._ring and self._focused:
            _round_rect(
                self, 1, 1, width - 1, bottom + 2, self._radius + 2,
                fill=FOCUS, outline="", tags="rr",
            )
        _round_rect(
            self,
            inset, inset, width - inset, bottom,
            self._radius,
            fill=self._fill,
            outline=self._outline or "",
            width=self._ow,
            tags="rr",
        )
        self.tag_lower("rr")

    def fit_now(self) -> None:
        """Size the canvas to its content synchronously.

        The <Configure>-driven sync only runs once the canvas has been
        mapped, so an unmapped box briefly requests Tk's default canvas size.
        For small hugged boxes (chips, key-caps) that transient request can
        exceed the window width and fight the window manager. Call this after
        adding content to request the right size up front.
        """
        self.inner.update_idletasks()
        self.configure(
            width=self.inner.winfo_reqwidth() + 2 * self._padx,
            height=self.inner.winfo_reqheight() + 2 * self._pady + self._shadow_h,
        )

    def set_focused(self, focused: bool) -> None:
        if focused == self._focused:
            return
        self._focused = focused
        self._redraw()

    def set_style(
        self,
        *,
        fill: Optional[str] = None,
        outline: Optional[str] = None,
        ow: Optional[int] = None,
    ) -> None:
        if fill is not None:
            self._fill = fill
        if outline is not None:
            self._outline = outline
        if ow is not None:
            self._ow = ow
        self.inner.configure(bg=self._fill)
        self._repaint(self.inner, self._fill)
        self._redraw()

    def _repaint(self, widget: tk.Widget, bg: str) -> None:
        if isinstance(widget, _Box):
            # A nested box keeps its own fill; only its corners blend in.
            widget.configure(bg=bg)
            return
        try:
            widget.configure(bg=bg)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._repaint(child, bg)


class _Button(tk.Canvas):
    """Canvas button: identical rendering on Linux Tk and macOS preview.

    Primary and danger buttons carry a soft shadow; secondary is a bordered
    white button; ghost is a quiet text button. All enabled buttons show a
    focus ring on keyboard focus.
    """

    _VARIANTS = {
        "primary": (PRIMARY, "#FFFFFF", PRIMARY_DARK, PRIMARY_PRESS, None),
        "danger": (DANGER, "#FFFFFF", DANGER_DARK, DANGER_PRESS, None),
        "secondary": (SURFACE, INK, SURFACE_ALT, "#E6EAF0", BORDER_STRONG),
        "ghost": (None, PRIMARY, PRIMARY_TINT, "#D9E5F8", None),
    }

    _SHADOWED = ("primary", "danger")
    _SHADOW_GAP = 4

    def __init__(
        self,
        parent: tk.Widget,
        *,
        text: str,
        command: Callable[[], None],
        font: tkfont.Font,
        variant: str = "secondary",
        enabled: bool = True,
        compact: bool = False,
    ) -> None:
        self._command = command
        self._variant = variant
        self._enabled = enabled
        self._focused = False
        self._hovering = False
        pad_x, pad_y = (20, 8) if compact else (26, 13)
        width = font.measure(text) + 2 * pad_x + 6
        height = font.metrics("linespace") + 2 * pad_y + 6 + self._SHADOW_GAP
        super().__init__(
            parent,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=parent.cget("bg"),
            cursor="hand2" if enabled else "arrow",
            takefocus=1 if enabled else 0,
        )
        self._bw = width
        self._bh = height
        self._label = self.create_text(
            width / 2, (height - self._SHADOW_GAP) / 2, text=text, font=font, anchor="center"
        )
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        # Space activates the focused control. Return/KP_Enter deliberately
        # stay unbound here so Enter always means "this screen's primary
        # action" via the gated global handler, no matter where focus sits.
        self.bind("<space>", self._key)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self._draw()

    def _state_colors(self) -> tuple:
        bg, fg, hover, press, outline = self._VARIANTS[self._variant]
        if not self._enabled:
            return DISABLED_BG, DISABLED_FG, None
        if self._hovering and hover is not None:
            return hover, fg, outline
        return bg, fg, outline

    def _draw(self) -> None:
        self.delete("rr")
        fill, fg, outline = self._state_colors()
        gap = self._SHADOW_GAP
        body_bottom = self._bh - 1 - gap
        if self._enabled and self._variant in self._SHADOWED:
            _round_rect(
                self, 4, 4 + 2, self._bw - 4, body_bottom + gap, 13,
                fill=SHADOW_A, outline="", tags="rr",
            )
        if self._focused and self._enabled:
            _round_rect(
                self, 1, 1, self._bw - 1, body_bottom + 2, 14,
                fill=FOCUS, outline="", tags="rr",
            )
        _round_rect(
            self, 3, 3, self._bw - 3, body_bottom, 12,
            fill=fill or "", outline=outline or "", width=1 if outline else 0,
            tags="rr",
        )
        self.tag_lower("rr")
        self.itemconfigure(self._label, fill=fg)

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
            self._hovering = True
            self._draw()

    def _leave(self, _event=None) -> None:
        if self._hovering:
            self._hovering = False
            self._draw()

    def _focus_in(self, _event=None) -> None:
        self._focused = True
        self._draw()

    def _focus_out(self, _event=None) -> None:
        self._focused = False
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self.configure(
            cursor="hand2" if enabled else "arrow",
            takefocus=1 if enabled else 0,
        )
        self._draw()


class TkWizard:
    def __init__(self, wizard: Wizard, fullscreen: bool = False) -> None:
        self.w = wizard
        self.root = tk.Tk()
        title = C.APP_NAME
        if wizard.preview:
            title = f"{C.APP_NAME} — PREVIEW (nothing is erased)"
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.minsize(1024, 740)
        if fullscreen:
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("1280x820")
        family = _family(self.root)
        mono = _mono_family(self.root)
        self.font_display = tkfont.Font(root=self.root, family=family, size=54, weight="bold")
        self.font_h = tkfont.Font(root=self.root, family=family, size=34, weight="bold")
        self.font_lead = tkfont.Font(root=self.root, family=family, size=20)
        self.font_b = tkfont.Font(root=self.root, family=family, size=18)
        self.font_bold = tkfont.Font(root=self.root, family=family, size=18, weight="bold")
        self.font_size_big = tkfont.Font(root=self.root, family=family, size=20, weight="bold")
        self.font_s = tkfont.Font(root=self.root, family=family, size=16)
        self.font_s_bold = tkfont.Font(root=self.root, family=family, size=16, weight="bold")
        self.font_tiny = tkfont.Font(root=self.root, family=family, size=14, weight="bold")
        self.font_btn = tkfont.Font(root=self.root, family=family, size=20, weight="bold")
        self.font_mono = tkfont.Font(root=self.root, family=mono, size=16)
        self.font_mono_sm = tkfont.Font(root=self.root, family=mono, size=15)
        self.font_entry = tkfont.Font(root=self.root, family=mono, size=30, weight="bold")
        self.font_stat = tkfont.Font(root=self.root, family=family, size=64, weight="bold")
        self.font_brand = tkfont.Font(root=self.root, family=family, size=21, weight="bold")
        self._confirm_var = tk.StringVar()
        self._owner_var = tk.IntVar(value=0)
        self._body: Optional[tk.Frame] = None
        self._footer: Optional[tk.Frame] = None
        self._header_step: Optional[tk.Label] = None
        self._strip: Optional[tk.Canvas] = None
        self._hint: Optional[tk.Frame] = None
        self._primary: Optional[_Button] = None
        self._countdown_ring: Optional[tk.Canvas] = None
        self._countdown_num: Optional[tk.Label] = None
        self._countdown_label: Optional[tk.Label] = None
        self._progress_label: Optional[tk.Label] = None
        self._progress_pct: Optional[tk.Label] = None
        self._progress_bar: Optional[tk.Canvas] = None
        self._match_label: Optional[tk.Label] = None
        self._match_icon: Optional[tk.Canvas] = None
        self._shown: Optional[Screen] = None
        self._primary_cmd: Optional[Callable[[], None]] = None
        self._after_id: Optional[str] = None
        self._build_chrome()
        self._confirm_var.trace_add("write", self._confirm_var_written)
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<KP_Enter>", self._on_return)
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
        mark = tk.Canvas(header, width=13, height=28, bg=NAVY, highlightthickness=0)
        _round_rect(mark, 1, 1, 12, 27, 5, fill=ACCENT, outline="")
        mark.pack(side=tk.LEFT, padx=(28, 0), pady=18)
        tk.Label(
            header,
            text=C.APP_NAME,
            fg="#FFFFFF",
            bg=NAVY,
            font=self.font_brand,
        ).pack(side=tk.LEFT, padx=(12, 28))
        self._header_step = tk.Label(
            header, text="", fg=NAVY_MUTED, bg=NAVY, font=self.font_s
        )
        self._header_step.pack(side=tk.RIGHT, padx=28)
        self._strip = tk.Canvas(self.root, height=6, bg=TRACK, highlightthickness=0)
        self._strip.pack(fill=tk.X)
        self._strip.bind("<Configure>", lambda _e: self._draw_strip())
        # Pack the footer first: when a small screen cannot fit everything,
        # pack clips the last-packed widget, and the action buttons must be
        # the last thing that ever gets clipped.
        self._footer = tk.Frame(self.root, bg=BG)
        self._footer.pack(fill=tk.X, side=tk.BOTTOM)
        self._body = tk.Frame(self.root, bg=BG)
        self._body.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
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
        step = _STEP_ORDER.get(self.w.screen, (0, "", ""))[0]
        frac = step / 8.0
        if frac > 0:
            _round_rect(cv, 0, 0, max(6.0, width * frac), 6, 3, fill=PRIMARY, outline="")

    def _column(self, parent: tk.Widget, *, fill_height: bool, bg: str = BG) -> tk.Frame:
        col = tk.Frame(parent, bg=bg)
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
        step = _STEP_ORDER.get(self.w.screen, (0, "", ""))
        self._header_step.configure(
            text=f"{step[1]} · {step[2]}" if step[2] and step[1] != step[2] else step[1]
        )
        self._clear(self._body)
        self._clear(self._footer)
        self._primary = None
        self._primary_cmd = None
        self._countdown_ring = None
        self._countdown_num = None
        self._countdown_label = None
        self._progress_label = None
        self._progress_pct = None
        self._progress_bar = None
        self._match_label = None
        self._match_icon = None
        screen = self.w.screen
        self._body.configure(bg=NAVY if screen == Screen.SPLASH else BG)
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

    def _h(self, parent: tk.Widget, text: str, *, bg: str = BG, fg: str = INK) -> tk.Label:
        return tk.Label(
            parent, text=text, font=self.font_h, fg=fg, bg=bg,
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
            justify=kw.get("justify", tk.LEFT),
            anchor=kw.get("anchor", "w"),
        )

    def _chip(self, parent: tk.Widget, text: str, *, fg: str, bg: str) -> _Box:
        chip = _Box(parent, radius=8, fill=bg, outline=None, ow=0, padx=10, pady=3)
        tk.Label(chip.inner, text=text, font=self.font_tiny, fg=fg, bg=bg).pack()
        chip.fit_now()
        return chip

    def _kbd(self, parent: tk.Widget, text: str, *, dark: bool = False) -> _Box:
        """A keyboard key-cap. Makes keyboard affordances scannable."""
        fill = NAVY_SOFT if dark else SURFACE
        outline = "#33517F" if dark else BORDER_STRONG
        fg = NAVY_TEXT if dark else INK
        cap = _Box(parent, radius=7, fill=fill, outline=outline, ow=1, padx=9, pady=2)
        tk.Label(cap.inner, text=text, font=self.font_tiny, fg=fg, bg=fill).pack()
        cap.fit_now()
        return cap

    def _hint_bar(self, parent: tk.Widget, hint: str, *, dark: bool = False) -> tk.Frame:
        """Hint copy with known key names rendered as key-caps."""
        bar = tk.Frame(parent, bg=NAVY if dark else BG)
        fg = NAVY_MUTED if dark else MUTED
        pos = 0
        for match in _KEY_TOKEN_RE.finditer(hint):
            if match.start() > pos:
                self._hint_text(bar, hint[pos:match.start()], fg, dark)
            for key in _KEY_TOKEN_KEYS.get(match.group(0), (match.group(0),)):
                self._kbd(bar, key, dark=dark).pack(side=tk.LEFT, padx=(0, 5))
            pos = match.end()
        if pos < len(hint):
            self._hint_text(bar, hint[pos:], fg, dark)
        return bar

    def _hint_text(self, parent: tk.Widget, text: str, fg: str, dark: bool) -> None:
        if not text:
            return
        tk.Label(
            parent, text=text, font=self.font_s, fg=fg,
            bg=NAVY if dark else BG, anchor="w",
        ).pack(side=tk.LEFT)

    def _panel(self, parent: tk.Widget, *, kind: str, text: str) -> _Box:
        colors = {
            "warn": (WARN_BG, WARN_BORDER),
            "danger": (DANGER_TINT, DANGER_BORDER),
            "info": (SURFACE_ALT, BORDER),
        }
        bg, border = colors[kind]
        box = _Box(parent, radius=14, fill=bg, outline=border, ow=1, padx=18, pady=16)
        row = tk.Frame(box.inner, bg=bg)
        row.pack(fill=tk.X)
        icon = _icon_alert(row, kind, 34)
        icon.configure(bg=bg)
        icon.pack(side=tk.LEFT, anchor="n", pady=2)
        tk.Label(
            row, text=text, font=self.font_b, fg=INK, bg=bg,
            wraplength=WRAP - 130, justify=tk.LEFT, anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 0))
        return box

    def _bind_tree(self, widget: tk.Widget, click) -> None:
        widget.bind("<Button-1>", click)
        for child in widget.winfo_children():
            self._bind_tree(child, click)

    def _bind_hover(
        self,
        widget: tk.Widget,
        on_enter: Callable[[], None],
        on_leave: Callable[[], None],
    ) -> None:
        def collect(w: tk.Widget) -> List[tk.Widget]:
            out = [w]
            for child in w.winfo_children():
                out.extend(collect(child))
            return out

        def enter(_e) -> None:
            on_enter()

        def leave(_e) -> None:
            def check() -> None:
                try:
                    ptr = widget.winfo_containing(*widget.winfo_pointerxy())
                except tk.TclError:
                    return
                node: Optional[tk.Widget] = ptr
                while node is not None:
                    if node == widget:
                        return
                    node = node.master
                on_leave()

            widget.after(10, check)

        for w in collect(widget):
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _meta_line(self, parent: tk.Widget, disk: Disk, bg: str) -> tk.Frame:
        meta = tk.Frame(parent, bg=bg)

        def dot() -> None:
            tk.Label(meta, text="·", font=self.font_s, fg=BORDER_STRONG, bg=bg).pack(
                side=tk.LEFT, padx=8
            )

        tk.Label(meta, text=disk.bus, font=self.font_s, fg=MUTED, bg=bg).pack(side=tk.LEFT)
        dot()
        tk.Label(meta, text="Serial ", font=self.font_s, fg=MUTED, bg=bg).pack(side=tk.LEFT)
        tk.Label(
            meta, text=disk.serial or "no serial", font=self.font_mono_sm, fg=INK, bg=bg
        ).pack(side=tk.LEFT)
        dot()
        tk.Label(meta, text="Device ", font=self.font_s, fg=MUTED, bg=bg).pack(side=tk.LEFT)
        tk.Label(meta, text=disk.path, font=self.font_mono_sm, fg=MUTED, bg=bg).pack(
            side=tk.LEFT
        )
        return meta

    def _disk_summary(self, parent: tk.Widget, disk: Disk) -> _Box:
        """The selected disk, shown the same way on confirm, working, and done."""
        box = _Box(
            parent, radius=RADIUS, fill=SURFACE, outline=BORDER, ow=1,
            padx=20, pady=18, shadow=True,
        )
        inner = box.inner
        top = tk.Frame(inner, bg=SURFACE)
        top.pack(fill=tk.X)
        tk.Label(
            top, text=disk.display_name, font=self.font_bold, fg=INK, bg=SURFACE, anchor="w"
        ).pack(side=tk.LEFT)
        self._chip(top, disk.kind.value, fg=MUTED, bg=SURFACE_ALT).pack(
            side=tk.LEFT, padx=(12, 0)
        )
        tk.Label(
            top, text=disk.size_phrase, font=self.font_size_big, fg=INK, bg=SURFACE, anchor="e"
        ).pack(side=tk.RIGHT)
        self._meta_line(inner, disk, SURFACE).pack(fill=tk.X, pady=(6, 0))
        return box

    # -- footer / buttons -----------------------------------------------------

    def _close_label(self) -> str:
        return C.BTN_CLOSE_PREVIEW if self.w.preview else C.BTN_SHUTDOWN

    def _footer_shell(self, hint: str) -> tk.Frame:
        assert self._footer is not None
        col = self._column(self._footer, fill_height=False)
        tk.Frame(col, bg=BORDER, height=1).pack(fill=tk.X)
        self._hint = self._hint_bar(col, hint)
        self._hint.pack(fill=tk.X, pady=(12, 0))
        row = tk.Frame(col, bg=BG)
        row.pack(fill=tk.X, pady=(12, 20))
        return row

    def _back_btn(self, row: tk.Frame) -> _Button:
        btn = _Button(
            row,
            text=C.BTN_BACK,
            command=self._nav(self.w.back),
            font=self.font_btn,
            variant="secondary",
        )
        btn.pack(side=tk.LEFT)
        return btn

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

    def _set_primary_enabled(self, enabled: bool) -> None:
        if self._primary is None:
            return
        self._primary.set_enabled(enabled)

    # -- screens ---------------------------------------------------------------

    def _splash(self) -> None:
        col = self._column(self._body, fill_height=True, bg=NAVY)
        tk.Frame(col, bg=NAVY).pack(fill=tk.BOTH, expand=True)
        tk.Label(
            col, text=C.APP_NAME, font=self.font_display, fg="#FFFFFF", bg=NAVY,
            anchor="center",
        ).pack(fill=tk.X)
        bar = tk.Canvas(col, width=140, height=10, bg=NAVY, highlightthickness=0)
        _round_rect(bar, 1, 1, 139, 9, 4, fill=ACCENT, outline="")
        bar.pack(pady=(24, 30))
        self._p(
            col, C.SPLASH_TAGLINE, fg=NAVY_TEXT, bg=NAVY, font=self.font_lead,
            wraplength=720, justify=tk.CENTER, anchor="center",
        ).pack(fill=tk.X)
        any_key = tk.Frame(col, bg=NAVY)
        any_key.pack(pady=(34, 0))
        self._kbd(any_key, "any key", dark=True).pack(side=tk.LEFT)
        tk.Label(
            any_key, text=" to continue.", font=self.font_b, fg=NAVY_TEXT, bg=NAVY,
        ).pack(side=tk.LEFT)
        tk.Frame(col, bg=NAVY).pack(fill=tk.BOTH, expand=True)
        row = self._footer_shell(C.HINT_SPLASH)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.skip_splash)
        if self._primary is not None:
            self._primary.focus_set()

    def _what(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "What this is").pack(fill=tk.X, pady=(30, 18))
        card = _Box(
            col, radius=RADIUS, fill=SURFACE, outline=BORDER, ow=1,
            padx=22, pady=18, shadow=True,
        )
        card.pack(fill=tk.X)
        for i, bullet in enumerate(C.WHAT_BULLETS):
            line = tk.Frame(card.inner, bg=SURFACE)
            line.pack(fill=tk.X, pady=(2 if i == 0 else 14, 2 if i == len(C.WHAT_BULLETS) - 1 else 0))
            tk.Label(
                line, text="•", font=self.font_bold, fg=PRIMARY, bg=SURFACE
            ).pack(side=tk.LEFT, anchor="n")
            tk.Label(
                line, text=bullet, font=self.font_lead, fg=INK, bg=SURFACE,
                wraplength=WRAP - 110, justify=tk.LEFT, anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        info = _Box(col, radius=14, fill=SURFACE_ALT, outline=BORDER, ow=1, padx=18, pady=14)
        info.pack(fill=tk.X, pady=(16, 0))
        icon = _icon_alert(info.inner, "info", 26)
        icon.configure(bg=SURFACE_ALT)
        icon.pack(side=tk.LEFT, anchor="n", pady=2)
        notes = tk.Frame(info.inner, bg=SURFACE_ALT)
        notes.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        tk.Label(
            notes, text=C.ENGINE_LINE, font=self.font_s, fg=MUTED, bg=SURFACE_ALT,
            wraplength=WRAP - 130, justify=tk.LEFT, anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            notes, text=C.SECURE_BOOT_HINT, font=self.font_s, fg=MUTED, bg=SURFACE_ALT,
            wraplength=WRAP - 130, justify=tk.LEFT, anchor="w",
        ).pack(fill=tk.X, pady=(8, 0))
        row = self._footer_shell(C.HINT_DEFAULT)
        self._secondary_btn(row, self._close_label(), self.w.shutdown)
        self._primary_btn(row, C.BTN_UNDERSTAND, self.w.accept_what)
        if self._primary is not None:
            self._primary.focus_set()

    def _owner(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._owner_var.set(1 if self.w.owner_ok else 0)
        self._h(col, "You must be the owner").pack(fill=tk.X, pady=(30, 12))
        self._p(col, C.OWNER_LEAD, fg=MUTED).pack(fill=tk.X, pady=(0, 24))
        checked = bool(self.w.owner_ok)
        card = _Box(
            col,
            radius=RADIUS,
            fill=PRIMARY_TINT if checked else SURFACE,
            outline=PRIMARY if checked else BORDER_STRONG,
            ow=2 if checked else 1,
            padx=20,
            pady=20,
            ring=True,
            shadow=True,
        )
        card.pack(fill=tk.X)
        card.configure(cursor="hand2", takefocus=1)
        box = _icon_check_box(card.inner, checked, 32)
        box.configure(bg=card._fill)
        box.pack(side=tk.LEFT, anchor="n", pady=2)
        text = tk.Label(
            card.inner,
            text=C.OWNER_CHECKBOX,
            font=self.font_lead,
            fg=INK,
            bg=card._fill,
            wraplength=WRAP - 150,
            justify=tk.LEFT,
            anchor="w",
        )
        text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(18, 0))
        self._bind_tree(card, self._owner_clicked)
        card.bind("<space>", self._owner_clicked)
        card.bind("<FocusIn>", lambda _e: card.set_focused(True))
        card.bind("<FocusOut>", lambda _e: card.set_focused(False))
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

    def _disk_row(self, parent: tk.Widget, disk: Disk, selected: bool) -> None:
        if disk.is_boot:
            fill, outline, ow = USB_BG, USB_BORDER, 1
        elif selected:
            fill, outline, ow = PRIMARY_TINT, PRIMARY, 2
        else:
            fill, outline, ow = SURFACE, BORDER, 1
        card = _Box(
            parent, radius=RADIUS, fill=fill, outline=outline, ow=ow,
            padx=18, pady=16, shadow=True,
        )
        card.pack(fill=tk.X, pady=6, padx=2)
        inner = card.inner
        top = tk.Frame(inner, bg=fill)
        top.pack(fill=tk.X)
        if disk.is_boot:
            icon = _icon_no_entry(top, 26)
        else:
            icon = _icon_radio(top, selected, 26)
        icon.configure(bg=fill)
        icon.pack(side=tk.LEFT, anchor="n", pady=2)
        title_col = tk.Frame(top, bg=fill)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 0))
        title_row = tk.Frame(title_col, bg=fill)
        title_row.pack(fill=tk.X)
        tk.Label(
            title_row, text=disk.display_name, font=self.font_bold, fg=INK, bg=fill, anchor="w"
        ).pack(side=tk.LEFT)
        self._chip(title_row, disk.kind.value, fg=MUTED, bg=SURFACE_ALT).pack(
            side=tk.LEFT, padx=(12, 0)
        )
        tk.Label(
            title_row, text=disk.size_phrase, font=self.font_size_big, fg=INK, bg=fill, anchor="e"
        ).pack(side=tk.RIGHT)
        self._meta_line(title_col, disk, fill).pack(fill=tk.X, pady=(6, 0))
        if disk.is_boot:
            banner = C.BOOT_USB_BANNER if disk.bus == "USB" else C.BOOT_DISC_BANNER
            tk.Label(
                inner, text=banner, font=self.font_s_bold, fg=DANGER, bg=fill, anchor="w"
            ).pack(fill=tk.X, pady=(10, 0), padx=(42, 0))
            return

        def _click(_e, p=disk.path):
            self._click_disk(p)
            return "break"

        self._bind_tree(card, _click)
        card.configure(cursor="hand2")
        inner.configure(cursor="hand2")
        if not selected:
            self._bind_hover(
                card,
                lambda c=card: c.set_style(fill=SURFACE_ALT),
                lambda c=card: c.set_style(fill=SURFACE),
            )

    def _pick(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "Pick a disk").pack(fill=tk.X, pady=(26, 6))
        self._p(col, C.pick_subtitle(), fg=MUTED, font=self.font_b).pack(fill=tk.X, pady=(0, 16))
        if same_size_conflict(self.w.selectable):
            self._panel(col, kind="warn", text=C.SAME_SIZE_HINT).pack(fill=tk.X, pady=(0, 12))
        if self.w.selected and self.w.selected.kind in (DiskKind.SSD, DiskKind.NVME):
            self._panel(col, kind="info", text=C.SSD_FOOTER).pack(fill=tk.X, pady=(0, 12))
        list_wrap = tk.Frame(col, bg=BG)
        list_wrap.pack(fill=tk.BOTH, expand=True, pady=(2, 8))
        canvas = tk.Canvas(list_wrap, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(
            list_wrap, orient=tk.VERTICAL, command=canvas.yview, width=14, troughcolor=BG
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
            self._disk_row(cards, disk, selected)
        row = self._footer_shell(C.HINT_PICK)
        back = self._back_btn(row)
        can = self.w.selected is not None and not self.w.selected.is_boot
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_pick, enabled=can)
        # Always land keyboard focus somewhere sensible: the obvious next
        # action when a disk is chosen, otherwise the safe way out.
        (self._primary if can and self._primary is not None else back).focus_set()

    def _click_disk(self, path: str) -> None:
        self.w.select_disk(path)
        self._draw()

    def _status_screen(self, kind: str, title: str, message: str) -> None:
        """Centered status layout shared by the blocked and empty screens."""
        col = self._column(self._body, fill_height=True)
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        icon = _icon_alert(col, kind, 88)
        icon.configure(bg=BG)
        icon.pack()
        self._h(col, title).pack(pady=(22, 12))
        self._p(
            col, message, wraplength=720, justify=tk.CENTER, anchor="center"
        ).pack(fill=tk.X)
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)

    def _blocked(self) -> None:
        self._status_screen("warn", "Stop", self.w.error or C.IDENTIFY_ERROR)
        row = self._footer_shell(C.HINT_DEFAULT)
        self._back_btn(row)
        self._primary_btn(row, self._close_label(), self.w.shutdown)
        if self._primary is not None:
            self._primary.focus_set()

    def _empty(self) -> None:
        self._status_screen("info", "No disk to erase", C.EMPTY_DISKS)
        row = self._footer_shell(C.HINT_DEFAULT)
        self._back_btn(row)
        self._primary_btn(row, self._close_label(), self.w.shutdown)
        if self._primary is not None:
            self._primary.focus_set()

    def _confirm(self) -> None:
        disk = self.w.selected
        assert disk is not None
        spec = self.w.confirm
        assert spec is not None
        col = self._column(self._body, fill_height=True)
        self._h(col, "Confirm the disk").pack(fill=tk.X, pady=(26, 16))
        self._disk_summary(col, disk).pack(fill=tk.X)
        self._panel(col, kind="warn", text=self.w.warning_text()).pack(fill=tk.X, pady=14)
        self._p(col, spec.prompt).pack(fill=tk.X, pady=(2, 10))
        shell = _Box(
            col, radius=14, fill=SURFACE, outline=BORDER_STRONG, ow=1,
            padx=16, pady=10, ring=True, shadow=True,
        )
        shell.pack(fill=tk.X)
        entry = tk.Entry(
            shell.inner,
            textvariable=self._confirm_var,
            font=self.font_entry,
            fg=INK,
            bg=SURFACE,
            insertbackground=INK,
            relief=tk.FLAT,
            highlightthickness=0,
            bd=0,
        )
        self._confirm_var.set(self.w.confirm_input)
        entry.pack(fill=tk.X, ipady=6)
        entry.bind("<FocusIn>", lambda _e: shell.set_focused(True))
        entry.bind("<FocusOut>", lambda _e: shell.set_focused(False))
        shell.set_focused(True)
        entry.focus_set()
        match_row = tk.Frame(col, bg=BG)
        match_row.pack(fill=tk.X, pady=(12, 0))
        self._match_icon = tk.Canvas(match_row, width=22, height=22, highlightthickness=0, bg=BG)
        self._match_icon.pack(side=tk.LEFT)
        self._match_label = tk.Label(
            match_row,
            text="",
            font=self.font_s,
            fg=MUTED,
            bg=BG,
            anchor="w",
        )
        self._match_label.pack(side=tk.LEFT, padx=(10, 0))
        self._paint_match()
        row = self._footer_shell(C.HINT_CONFIRM)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_confirm, enabled=self.w.token_ok)

    def _paint_match(self) -> None:
        if self._match_icon is None or self._match_label is None:
            return
        cv = self._match_icon
        cv.delete("all")
        if self.w.token_ok:
            cv.create_oval(1, 1, 21, 21, fill=OK, outline="")
            cv.create_line(
                6, 11.5, 9.5, 15, 16, 7,
                fill="#FFFFFF", width=2.5, capstyle="round", joinstyle="round",
            )
            self._match_label.configure(text=C.CONFIRM_MATCH_OK, fg=OK)
        else:
            cv.create_oval(2, 2, 20, 20, outline=BORDER_STRONG, width=2)
            self._match_label.configure(text=C.CONFIRM_MATCH_WAIT, fg=MUTED)

    def _confirm_var_written(self, *_a) -> None:
        if self.w.screen != Screen.CONFIRM:
            return
        self.w.set_confirm_input(self._confirm_var.get())
        self._set_primary_enabled(self.w.token_ok)
        self._paint_match()

    def _method_card(self, parent: tk.Widget, method: MethodId) -> None:
        card_copy = C.METHOD_CARDS[method]
        selected = self.w.method == method
        fill = PRIMARY_TINT if selected else SURFACE
        outline = PRIMARY if selected else BORDER
        card = _Box(
            parent, radius=RADIUS, fill=fill, outline=outline, ow=2 if selected else 1,
            padx=18, pady=9, shadow=True,
        )
        card.pack(fill=tk.X, pady=3)
        inner = card.inner
        top = tk.Frame(inner, bg=fill)
        top.pack(fill=tk.X)
        icon = _icon_radio(top, selected, 26)
        icon.configure(bg=fill)
        icon.pack(side=tk.LEFT, anchor="n", pady=2)
        title_row = tk.Frame(top, bg=fill)
        title_row.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 0))
        self._kbd(title_row, card_copy["key"]).pack(side=tk.LEFT)
        tk.Label(
            title_row, text=card_copy["title"], font=self.font_bold, fg=INK, bg=fill, anchor="w"
        ).pack(side=tk.LEFT, padx=(12, 0))
        if method == DEFAULT_METHOD:
            self._chip(title_row, C.RECOMMENDED_TAG, fg=OK, bg=OK_TINT).pack(
                side=tk.LEFT, padx=(12, 0)
            )
        for text in (card_copy["blurb"], card_copy["pace"]):
            tk.Label(
                inner,
                text=text,
                font=self.font_s,
                fg=MUTED,
                bg=fill,
                wraplength=WRAP - 120,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=(58, 16), pady=(1, 0))

        def _click(_e, m=method):
            self._choose_method(m)
            return "break"

        self._bind_tree(card, _click)
        card.configure(cursor="hand2")
        inner.configure(cursor="hand2")
        if not selected:
            self._bind_hover(
                card,
                lambda c=card: c.set_style(fill=SURFACE_ALT),
                lambda c=card: c.set_style(fill=SURFACE),
            )

    def _method(self) -> None:
        col = self._column(self._body, fill_height=True)
        # Tightest screen in the wizard: keep the whole column inside the
        # 1024x740 minimum window with the footer fully visible.
        self._h(col, "How thorough").pack(fill=tk.X, pady=(14, 8))
        for method in (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO):
            self._method_card(col, method)
        self._panel(col, kind="info", text=C.SSD_FOOTER).pack(fill=tk.X, pady=(6, 2))
        adv = _Button(
            col,
            text=C.BTN_ADVANCED,
            command=self.w.open_advanced,
            font=self.font_s_bold,
            variant="ghost",
            compact=True,
        )
        adv.pack(anchor="w", pady=(2, 0))
        row = self._footer_shell(C.HINT_METHOD)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_method)
        if self._primary is not None:
            self._primary.focus_set()

    def _choose_method(self, method: MethodId) -> None:
        self.w.set_method(method)
        self._draw()

    def _last(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "Last chance").pack(fill=tk.X, pady=(26, 14))
        self._panel(col, kind="danger", text=self.w.erase_label()).pack(fill=tk.X)
        if self.w.error:
            self._panel(col, kind="danger", text=self.w.error).pack(fill=tk.X, pady=(12, 0))
        count = tk.Frame(col, bg=BG)
        count.pack(pady=(26, 0))
        ring = tk.Canvas(count, width=190, height=190, bg=BG, highlightthickness=0)
        ring.pack()
        self._countdown_ring = ring
        self._countdown_num = tk.Label(
            ring, text="", font=self.font_stat, fg=INK, bg=BG, anchor="center"
        )
        ring.create_window(95, 92, window=self._countdown_num)
        self._countdown_label = tk.Label(
            col, text="", font=self.font_b, fg=MUTED, bg=BG, anchor="center", justify=tk.CENTER
        )
        self._countdown_label.pack(fill=tk.X, pady=(12, 0))
        row = self._footer_shell(C.HINT_DEFAULT)
        back = self._back_btn(row)
        self._primary_btn(
            row,
            C.BTN_ERASE,
            self.w.confirm_erase,
            enabled=self.w.erase_enabled,
            danger=True,
        )
        # Safe default: focus Back, never the Erase button.
        back.focus_set()
        self._refresh_last_chance()

    def _refresh_last_chance(self) -> None:
        if self._countdown_ring is None or self._countdown_label is None:
            return
        left = int(self.w.countdown_left + 0.99)
        ring = self._countdown_ring
        ring.delete("arc")
        ring.create_oval(14, 14, 176, 176, outline=TRACK, width=13, tags="arc")
        if left > 0:
            frac = min(1.0, max(0.0, self.w.countdown_left / COUNTDOWN_S))
            ring.create_arc(
                14, 14, 176, 176, start=90, extent=-359.99 * frac,
                style=tk.ARC, outline=PRIMARY, width=13, tags="arc",
            )
            if self._countdown_num is not None:
                self._countdown_num.configure(text=str(left), fg=INK)
            self._countdown_label.configure(text=C.COUNTDOWN_CAPTION, fg=MUTED)
        else:
            ring.create_oval(14, 14, 176, 176, outline=OK, width=13, tags="arc")
            if self._countdown_num is not None:
                self._countdown_num.configure(text="✓", fg=OK)
            self._countdown_label.configure(text=C.COUNTDOWN_READY, fg=OK)
        self._set_primary_enabled(self.w.erase_enabled)

    def _working(self) -> None:
        col = self._column(self._body, fill_height=True)
        disk = self.w.selected
        self._h(col, "Working").pack(fill=tk.X, pady=(26, 16))
        if disk is not None:
            self._disk_summary(col, disk).pack(fill=tk.X)
        card_copy = C.METHOD_CARDS[self.w.method]
        self._progress_pct = tk.Label(
            col, text="", font=self.font_stat, fg=INK, bg=BG, anchor="w"
        )
        self._progress_pct.pack(fill=tk.X, pady=(28, 10))
        bar = tk.Canvas(col, height=18, bg=BG, highlightthickness=0)
        bar.pack(fill=tk.X)
        bar.bind("<Configure>", lambda _e: self._refresh_working())
        self._progress_bar = bar
        self._progress_label = self._p(
            col, f"{card_copy['title']}.  {C.WORKING_PULSE}", fg=MUTED, font=self.font_b
        )
        self._progress_label.pack(fill=tk.X, pady=(18, 0))
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
        bar.delete("all")
        width = max(bar.winfo_width(), 1)
        _round_rect(bar, 0, 0, width, 18, 9, fill=TRACK, outline="")
        fill_w = width * min(1.0, frac)
        if fill_w > 1:
            _round_rect(bar, 0, 0, max(fill_w, 18), 18, 9, fill=PRIMARY, outline="")

    def _done(self) -> None:
        col = self._column(self._body, fill_height=True)
        ok = self.w.done_ok
        title = "Finished" if ok else "The wipe did not finish"
        color = OK if ok else DANGER
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        icon = _icon_status(col, ok, 104)
        icon.configure(bg=BG)
        icon.pack()
        heading = self._h(col, title)
        heading.configure(anchor="center", justify=tk.CENTER)
        heading.pack(fill=tk.X, pady=(22, 10))
        if self.w.preview:
            msg = C.DONE_OK_PREVIEW if ok else C.DONE_FAIL_PREVIEW
        else:
            msg = C.DONE_OK if ok else C.DONE_FAIL
        self._p(
            col, msg, fg=color, wraplength=720, justify=tk.CENTER, anchor="center"
        ).pack(fill=tk.X)
        if self.w.selected is not None:
            self._disk_summary(col, self.w.selected).pack(fill=tk.X, pady=(22, 0))
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        row = self._footer_shell(C.HINT_DEFAULT)
        if self.w.preview:
            self._secondary_btn(row, C.BTN_CLOSE_PREVIEW, self.w.shutdown)
            self._primary_btn(row, C.BTN_RUN_AGAIN, self.w.reset_for_preview)
        else:
            self._primary_btn(row, C.BTN_SHUTDOWN, self.w.shutdown)
        if self._primary is not None:
            self._primary.focus_set()

    def _advanced(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._h(col, "Advanced").pack(fill=tk.X, pady=(26, 10))
        self._p(col, C.ADVANCED_LEAD, fg=MUTED, font=self.font_b).pack(fill=tk.X, pady=(0, 14))
        from beamo_wipe.methods import METHODS

        card = _Box(
            col, radius=RADIUS, fill=SURFACE, outline=BORDER, ow=1,
            padx=20, pady=14, shadow=True,
        )
        card.pack(fill=tk.X)
        count = len(METHODS)
        for i, spec in enumerate(METHODS.values()):
            tk.Label(
                card.inner,
                text=f"{spec.method_id.value}: nwipe --method={spec.nwipe_method}  ({spec.docs_name})",
                font=self.font_mono_sm,
                fg=INK,
                bg=SURFACE,
                anchor="w",
            ).pack(
                fill=tk.X,
                pady=(4 if i == 0 else 6, 4 if i == count - 1 else 6),
            )
        log = self.w._wipe_request.logfile if self.w._wipe_request else "(no wipe yet)"
        log_row = tk.Frame(col, bg=BG)
        log_row.pack(fill=tk.X, pady=(18, 6))
        tk.Label(
            log_row, text="Log file (never on the target disk): ", font=self.font_s,
            fg=MUTED, bg=BG, anchor="w",
        ).pack(side=tk.LEFT)
        tk.Label(
            log_row, text=log, font=self.font_mono_sm, fg=INK, bg=BG, anchor="w"
        ).pack(side=tk.LEFT)
        self._p(col, C.ADVANCED_LOG_NOTE, fg=MUTED, font=self.font_s).pack(fill=tk.X)
        row = self._footer_shell(C.HINT_DEFAULT)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.close_advanced)
        if self._primary is not None:
            self._primary.focus_set()

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
        if event.keysym in ("Return", "KP_Enter", "Escape", "Tab"):
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
        if self.w.screen == Screen.METHOD:
            # Some X servers/IMEs deliver keysym with an empty char.
            digit = event.char if event.char in ("1", "2", "3") else event.keysym
            if digit in ("1", "2", "3"):
                mapping = {"1": MethodId.EVERYDAY, "2": MethodId.EXTRA, "3": MethodId.QUICK_ZERO}
                self.w.set_method(mapping[digit])
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
