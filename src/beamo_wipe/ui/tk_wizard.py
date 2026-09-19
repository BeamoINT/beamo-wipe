# SPDX-License-Identifier: GPL-3.0-or-later
"""Fullscreen Tk wizard with a quiet, consistent utility design.

White canvas, navy identity, amber accent, and restrained blue actions.
Rounded surfaces and pill buttons keep attention on disk identity and the
next step. Red is reserved for destructive actions and failures. Keyboard
focus always has a visible ring; details use the same controls as navigation.
The web gallery and offline helper mirror these tokens. Native system fonts
keep the live USB self-contained and readable without network dependencies.
"""

from __future__ import annotations

import math
import re
import sys
import threading
from functools import partial
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Callable, List, Literal, Optional

from beamo_wipe import copy as C
from beamo_wipe import diagnostic_report as D
from beamo_wipe.outcomes import may_have_erased
from beamo_wipe.diagnostics import emit_serial_marker
from beamo_wipe.methods import DEFAULT_METHOD
from beamo_wipe import storage_limits as limits
from beamo_wipe import inventory
from beamo_wipe import keyboard as _keyboard
from beamo_wipe.keyboard import LAYOUT_ORDER
from beamo_wipe.lang import LANGUAGE_NAMES, LANGUAGE_ORDER
from beamo_wipe.models import Disk, DiskKind, MethodId, Screen
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.ui.layout import DEFAULT_SIZE, MIN_SIZE, layout_for, opening_size
from beamo_wipe.recovery import (
    RecoverySections,
    recovery_for_blocked,
    recovery_for_diagnostic,
    recovery_for_empty,
    recovery_for_view,
    recovery_for_wizard_error,
)
from beamo_wipe.support_export import next_step_needs_support
from beamo_wipe.wizard import (
    COUNTDOWN_S,
    ReportView,
    Wizard,
    error_needs_support,
    format_progress_percent,
)

# --- Design tokens ---------------------------------------------------------
#
# One palette, three renderings: this file, the web click-through
# (gallery.py), and the boot-menu helper (helper/index.html) must carry the
# same values — tests/test_ui_system.py pins the sync and the WCAG contrast
# floor, so tune here and mirror there, never in one place only.

# The field is plain white on every screen, splash included: hierarchy
# comes from spacing, type, and the navy/amber brand accents, not tint.
BG = "#FFFFFF"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F4F6F8"
INK = "#12202E"
MUTED = "#4A5A6A"
BORDER = "#E3E8EE"
# Strong border: also the unchecked radio/checkbox/key-cap outline, so it
# must stay >= 3:1 on every surface (WCAG non-text contrast).
BORDER_STRONG = "#6E7C8A"
NAVY = "#0A1B34"
NAVY_SOFT = "#16315C"
NAVY_MUTED = "#C9D6E8"
NAVY_DEEP = "#071426"  # fallback emblem platter
PRIMARY = "#1C4A73"
PRIMARY_DARK = "#163A5C"
PRIMARY_PRESS = "#102A44"
PRIMARY_TINT = "#F0F5FA"
DANGER = "#B3261E"
DANGER_DARK = "#8E1D16"
DANGER_PRESS = "#6E1510"
DANGER_TINT = "#FBEBE9"
DANGER_BORDER = "#E6A79E"
OK = "#17703F"
OK_TINT = "#E7F2EB"
OK_BORDER = "#9CC3AB"
WARN = "#7A5200"
WARN_BG = "#FBF1D5"
WARN_BORDER = "#E3CE96"
USB_BG = "#F7F1E6"
USB_BORDER = "#D9CEB5"
FOCUS = "#2563EB"
ACCENT = "#E6A817"
DISABLED_BG = "#E8ECF1"
DISABLED_FG = "#6E7989"
TRACK = "#E4E9EF"
# One soft shadow layer. Tk has no blur, so the single rounded rect is
# offset down a few pixels in a cool gray that stays quiet on BG.
SHADOW = "#D5DCE6"
PREVIEW_BG = "#E6A817"
PREVIEW_FG = "#0A1B34"

CONTENT_W = 940
WRAP = CONTENT_W - 72
RADIUS = 12
PILL = 999  # _rr_points clamps to half the shape: fully rounded ends
BAR_H = 8
SHADOW_H = 8
HALO_INSET = 5  # canvas margin a haloed _Box reserves for its glow

# Countdown ring on the last-chance screen.
RING_SIZE = 64
RING_PAD = 6
RING_W = 4


def header_caption(step_n: int, step_label: str) -> str:
    """One current-stage label. Not eight equal pages, and not a percent."""
    if not step_label:
        return ""
    if step_n and 1 <= step_n <= len(C.JOURNEY_LABELS):
        if step_label.startswith(C.STEP_PREFIX) or step_label in C.JOURNEY_LABELS:
            return C.JOURNEY_LABELS[step_n - 1]
    return step_label


_STEP_ORDER = {
    Screen.KEYBOARD: (C.journey_stage(Screen.KEYBOARD), C.journey_caption(Screen.KEYBOARD), C.TITLE_KEYBOARD),
    Screen.WHAT: (C.journey_stage(Screen.WHAT), C.journey_caption(Screen.WHAT), C.TITLE_WHAT),
    Screen.OWNER: (C.journey_stage(Screen.OWNER), C.journey_caption(Screen.OWNER), C.STEP_OWNERSHIP),
    Screen.DISK_HELP: (C.journey_stage(Screen.DISK_HELP), C.DISK_HELP_TITLE, C.DISK_HELP_TITLE),
    Screen.PICK: (C.journey_stage(Screen.PICK), C.journey_caption(Screen.PICK), C.TITLE_PICK),
    Screen.PICK_EMPTY: (C.journey_stage(Screen.PICK_EMPTY), C.journey_caption(Screen.PICK_EMPTY), C.TITLE_PICK),
    Screen.PICK_BLOCKED: (C.journey_stage(Screen.PICK_BLOCKED), C.journey_caption(Screen.PICK_BLOCKED), C.TITLE_PICK),
    Screen.CONFIRM: (C.journey_stage(Screen.CONFIRM), C.journey_caption(Screen.CONFIRM), C.TITLE_CONFIRM),
    Screen.METHOD: (C.journey_stage(Screen.METHOD), C.journey_caption(Screen.METHOD), C.TITLE_METHOD),
    Screen.ADVANCED: (C.journey_stage(Screen.ADVANCED), C.TITLE_ADVANCED, C.TITLE_ADVANCED),
    Screen.LIMITS: (C.journey_stage(Screen.LIMITS), limits.TITLE, limits.TITLE),
    Screen.REFRESHING: (C.journey_stage(Screen.REFRESHING), C.journey_caption(Screen.REFRESHING), C.BUSY_REFRESHING_TITLE),
    Screen.REFRESH_CONFIRM: (0, "", C.TITLE_REFRESH),
    Screen.LAST_CHANCE: (C.journey_stage(Screen.LAST_CHANCE), C.journey_caption(Screen.LAST_CHANCE), C.TITLE_LAST),
    Screen.CHECKING: (C.journey_stage(Screen.CHECKING), C.journey_caption(Screen.CHECKING), C.BUSY_CHECKING_TITLE),
    Screen.STOPPING: (C.journey_stage(Screen.STOPPING), C.journey_caption(Screen.STOPPING), C.BUSY_STOPPING_TITLE),
    Screen.WORKING: (C.journey_stage(Screen.WORKING), C.journey_caption(Screen.WORKING), C.TITLE_WORKING),
    Screen.DONE: (C.journey_stage(Screen.DONE), C.journey_caption(Screen.DONE), C.TITLE_DONE_OK),
    Screen.REPORT_HELP: (C.journey_stage(Screen.REPORT_HELP), C.REPORT_HELP_TITLE, C.REPORT_HELP_TITLE),
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


# --- Color helpers ---------------------------------------------------------


def _mix(a: str, b: str, t: float) -> str:
    """Blend two #RRGGBB colors. t=0 gives a, t=1 gives b."""
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


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


def _icon_radio(parent: tk.Widget, selected: bool, size: int = 22) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 1.5
    ring = PRIMARY if selected else BORDER_STRONG
    cv.create_oval(pad, pad, size - pad, size - pad, outline=ring, width=2)
    if selected:
        inset = size * 0.30
        cv.create_oval(inset, inset, size - inset, size - inset, fill=PRIMARY, outline="")
    return cv


def _icon_check_box(parent: tk.Widget, checked: bool, size: int = 28) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 2
    if checked:
        _round_rect(
            cv, pad, pad, size - pad, size - pad, 10,
            fill=PRIMARY, outline=PRIMARY, width=2,
        )
        cv.create_line(
            [size * 0.28,
            size * 0.52,
            size * 0.45,
            size * 0.70,
            size * 0.74,
            size * 0.30],
            fill="#FFFFFF",
            width=3,
            capstyle="round",
            joinstyle="round",
        )
    else:
        _round_rect(
            cv, pad, pad, size - pad, size - pad, 10,
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


def _icon_clock(parent: tk.Widget, size: int = 18) -> tk.Canvas:
    """Small clock glyph for the "how long does this take" line on method cards."""
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 1.5
    cv.create_oval(pad, pad, size - pad, size - pad, outline=MUTED, width=2)
    cx = size / 2.0
    cy = size / 2.0
    cv.create_line(cx, cy, cx, cy - size * 0.26, fill=MUTED, width=2, capstyle="round")
    cv.create_line(
        cx, cy, cx + size * 0.20, cy + size * 0.12, fill=MUTED, width=2, capstyle="round"
    )
    return cv


def _draw_alert_glyph(cv: tk.Canvas, x: float, y: float, size: float, kind: str) -> None:
    """Filled badge at (x, y). Every severity differs by shape, not color:
    triangle for warn, circle-X for danger, circle-i for info, circle-check
    for ok, document square for limits."""
    if kind == "info":
        cv.create_oval(x + 2, y + 2, x + size - 2, y + size - 2, fill=PRIMARY, outline="")
        cv.create_oval(
            x + size / 2 - 2.5, y + size * 0.24, x + size / 2 + 2.5, y + size * 0.24 + 5,
            fill="#FFFFFF", outline="",
        )
        cv.create_line(
            x + size / 2, y + size * 0.46, x + size / 2, y + size * 0.74,
            fill="#FFFFFF", width=3, capstyle="round",
        )
    elif kind == "warn":
        cv.create_polygon(
            x + size / 2, y + 2, x + size - 2, y + size - 3, x + 2, y + size - 3,
            fill=WARN, outline=WARN, width=6, joinstyle="round",
        )
        cv.create_line(
            x + size / 2, y + size * 0.36, x + size / 2, y + size * 0.62,
            fill="#FFFFFF", width=3, capstyle="round",
        )
        cv.create_oval(
            x + size / 2 - 2, y + size * 0.72, x + size / 2 + 2, y + size * 0.72 + 4,
            fill="#FFFFFF", outline="",
        )
    elif kind == "danger":
        cv.create_oval(x + 2, y + 2, x + size - 2, y + size - 2, fill=DANGER, outline="")
        cross = max(3.0, size * 0.10)
        cv.create_line(
            x + size * 0.30, y + size * 0.30, x + size * 0.70, y + size * 0.70,
            fill="#FFFFFF", width=cross, capstyle="round",
        )
        cv.create_line(
            x + size * 0.30, y + size * 0.70, x + size * 0.70, y + size * 0.30,
            fill="#FFFFFF", width=cross, capstyle="round",
        )
    elif kind == "ok":
        cv.create_oval(x + 2, y + 2, x + size - 2, y + size - 2, fill=OK, outline="")
        cv.create_line(
            [x + size * 0.26, y + size * 0.54,
             x + size * 0.44, y + size * 0.70,
             x + size * 0.74, y + size * 0.30],
            fill="#FFFFFF", width=max(3.0, size * 0.10),
            capstyle="round", joinstyle="round",
        )
    elif kind == "limits":
        _round_rect(
            cv, x + 2, y + 2, x + size - 2, y + size - 2, size * 0.22,
            fill=PRIMARY, outline="",
        )
        for frac in (0.36, 0.52, 0.68):
            cv.create_line(
                x + size * 0.28, y + size * frac, x + size * 0.72, y + size * frac,
                fill="#FFFFFF", width=max(2.0, size * 0.07), capstyle="round",
            )
    else:
        raise ValueError(f"unknown severity glyph: {kind!r}")


def _icon_alert(parent: tk.Widget, kind: str, size: int = 34) -> tk.Canvas:
    """Filled badge: triangle warn, circle-X danger, circle-i info,
    circle-check ok, document limits. White glyph."""
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    _draw_alert_glyph(cv, 0, 0, size, kind)
    return cv


def _icon_badge(parent: tk.Widget, kind: str, size: int = 96) -> tk.Canvas:
    """Status-screen badge: the alert glyph on a tinted halo circle."""
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    tint = {
        "warn": WARN_BG, "danger": DANGER_TINT, "info": SURFACE_ALT,
        "ok": OK_TINT, "limits": SURFACE_ALT,
    }[kind]
    cv.create_oval(1, 1, size - 1, size - 1, fill=tint, outline="")
    glyph = size * 0.58
    off = (size - glyph) / 2
    _draw_alert_glyph(cv, off, off, glyph, kind)
    return cv


_ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _draw_emblem(cv: tk.Canvas, cx: float, cy: float, size: float, tags: str = "emblem") -> None:
    """Fallback brand mark centered at (cx, cy): an amber rounded tile with
    a navy disk platter. Used only when the real logo PNGs are missing."""
    half = size / 2.0
    _round_rect(
        cv, cx - half, cy - half, cx + half, cy + half, size * 0.24,
        fill=ACCENT, outline="", tags=tags,
    )
    platter = size * 0.30
    cv.create_oval(
        cx - platter, cy - platter, cx + platter, cy + platter,
        fill=NAVY_DEEP, outline="", tags=tags,
    )
    hub = size * 0.10
    cv.create_oval(
        cx - hub, cy - hub, cx + hub, cy + hub, fill=ACCENT, outline="", tags=tags,
    )


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
            [cx0 + (cx1 - cx0) * 0.22, cy0 + (cy1 - cy0) * 0.52,
            cx0 + (cx1 - cx0) * 0.42, cy0 + (cy1 - cy0) * 0.72,
            cx0 + (cx1 - cx0) * 0.78, cy0 + (cy1 - cy0) * 0.28],
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
    ``shadow=True`` the card gets a single soft drop shadow (the canvas
    reserves SHADOW_H pixels at the bottom for it). With ``halo=True`` the
    card gets a soft primary glow — the selected state for cards.
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
        halo: bool = False,
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
        self._halo = halo
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

    @property
    def _inset(self) -> int:
        if self._halo:
            return HALO_INSET
        return 3 if self._ring else 1

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
        inset = self._inset
        bottom = height - inset - self._shadow_h
        if self._shadow:
            # Fake a blurred shadow with three stacked rounded rects: a
            # darker umbra hugging the card, lighter penumbra falling away.
            base = self.cget("bg")
            for off, t in ((6, 0.80), (3, 0.52), (1, 0.22)):
                _round_rect(
                    self, inset + 1, inset + off, width - inset - 1, bottom + off,
                    self._radius, fill=_mix(SHADOW, base, t), outline="", tags="rr",
                )
        if self._halo:
            base = self.cget("bg")
            _round_rect(
                self, inset - 2, inset - 2, width - inset + 2, bottom + 2,
                self._radius + 2, fill=_mix(PRIMARY, base, 0.22), outline="", tags="rr",
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

        Sizes are summed from the children's own requested sizes — labels
        know theirs as soon as they are created — instead of calling
        update_idletasks(): a global geometry pass mid-build would lay the
        window out against a half-built footer and make the pick list's
        scroll restoration chase transient canvas heights.
        """
        req_w = 0
        req_h = 0
        for child in self.inner.winfo_children():
            req_w += child.winfo_reqwidth()
            req_h = max(req_h, child.winfo_reqheight())
        self.configure(
            width=req_w + 2 * self._padx,
            height=req_h + 2 * self._pady + self._shadow_h,
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

    def _repaint(self, widget: tk.Misc, bg: str) -> None:
        if isinstance(widget, _Box):
            # A nested box keeps its own fill; only its corners blend in.
            widget.configure({"bg": bg})
            return
        try:
            widget.configure({"bg": bg})
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._repaint(child, bg)


def _soft_break_tokens(
    text: str, measure: Callable[[str], int], max_px: int
) -> str:
    """Insert explicit breaks so space-only Tk wrapping never clips long tokens.

    Tk ``wraplength`` breaks lines at spaces only, so an unbroken serial
    number or device path wider than its card renders past the edge and
    hides the distinguishing tail. This pre-breaks only tokens wider than
    ``max_px`` (measured with the real font, so it holds at any DPI),
    inserting ``"\\n"`` and nothing else: removing the breaks restores the
    exact input, and callers keep the raw string for evidence, copy, and
    readout paths. Plain spaced text passes through untouched.
    """

    def _split_long(word: str) -> list:
        parts: list = []
        cur = ""
        for ch in word:
            trial = cur + ch
            if cur and measure(trial) > max_px:
                parts.append(cur)
                cur = ch
            else:
                cur = trial
        if cur:
            parts.append(cur)
        return parts

    max_px = max(1, int(max_px))
    out: list = []
    for para in (text or "").split("\n"):
        cur = ""
        for tok in re.split(r"(\s+)", para):
            if not tok:
                continue
            # Whitespace runs split into single spaces too: an over-wide
            # run must still fit, and spaces rejoin greedily when they do.
            pieces = [tok] if measure(tok) <= max_px else _split_long(tok)
            for piece in pieces:
                trial = cur + piece
                if cur and measure(trial) > max_px:
                    out.append(cur)
                    cur = piece
                else:
                    cur = trial
        out.append(cur)
    return "\n".join(out)


class _Button(tk.Canvas):
    """Canvas button: identical rendering on Linux Tk and macOS preview.

    Buttons are flat rounded rectangles: filled primary/danger, bordered white secondary,
    quiet ghost. All enabled buttons show a focus ring on keyboard focus, a
    hover shade under the pointer, and a darker press shade while held, so
    the control always answers the user.
    """

    # bg, fg, hover, press, outline, focus-ring.
    _VARIANTS = {
        "primary": (PRIMARY, "#FFFFFF", PRIMARY_DARK, PRIMARY_PRESS, None, FOCUS),
        "danger": (DANGER, "#FFFFFF", DANGER_DARK, DANGER_PRESS, None, FOCUS),
        "secondary": (SURFACE, INK, SURFACE_ALT, "#E2E8EE", BORDER_STRONG, FOCUS),
        "ghost": (None, PRIMARY, PRIMARY_TINT, "#D7E4F2", None, FOCUS),
    }

    _RING_GAP = 4  # canvas room below the pill so the focus ring never clips

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
        large: bool = False,
        min_width: int = 0,
    ) -> None:
        self._command = command
        self._variant = variant
        self._enabled = enabled
        self._focused = False
        self._hovering = False
        self._held = False  # mouse button is down on this control
        self._pressed = False  # drawn in the pressed shade (held and inside)
        if large:
            pad_x, pad_y = 34, 14
        else:
            pad_x, pad_y = (12, 3) if compact else (24, 10)
        width = max(min_width, font.measure(text) + 2 * pad_x + 6)
        height = font.metrics("linespace") + 2 * pad_y + 6 + self._RING_GAP
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
            width / 2, (height - self._RING_GAP) / 2, text=text, font=font, anchor="center"
        )
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        # Space activates the focused control. Return/KP_Enter use the
        # global repeat gate; on Last chance it also respects button focus.
        self.bind("<space>", self._key)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self._draw()

    def _state_colors(self) -> tuple:
        bg, fg, hover, press, outline, _ring = self._VARIANTS[self._variant]
        if not self._enabled:
            if self._variant == "ghost":
                return self.cget("bg"), DISABLED_FG, None
            return DISABLED_BG, DISABLED_FG, None
        if self._pressed and press is not None:
            return press, fg, outline
        if self._hovering and hover is not None:
            return hover, fg, outline
        return bg, fg, outline

    def _draw(self) -> None:
        self.delete("rr")
        fill, fg, outline = self._state_colors()
        ring = self._VARIANTS[self._variant][5]
        body_bottom = self._bh - 1 - self._RING_GAP
        if self._focused and self._enabled:
            _round_rect(
                self, 1, 1, self._bw - 1, body_bottom + 2, PILL,
                fill=ring, outline="", tags="rr",
            )
        _round_rect(
            self, 3, 3, self._bw - 3, body_bottom, PILL,
            fill=fill or "", outline=outline or "", width=1 if outline else 0,
            tags="rr",
        )
        self.tag_lower("rr")
        self.itemconfigure(self._label, fill=fg)

    def _press(self, _event=None) -> str:
        if self._enabled:
            # A disabled button never takes focus: on gated screens (confirm
            # entry, owner card) the keyboard input must stay where it is.
            self.focus_set()
            self._held = True
            self._pressed = True
            self._draw()
        return "break"

    def _release(self, event=None) -> str:
        held = self._held
        self._held = False
        self._pressed = False
        self._draw()
        inside = (
            event is not None
            and 0 <= event.x <= self._bw
            and 0 <= event.y <= self._bh
        )
        if self._enabled and held and inside and self._command is not None:
            self._command()
        return "break"

    def _key(self, _event=None) -> str:
        app = getattr(self.winfo_toplevel(), "_tk_wizard", None)
        if app is not None:
            if not app._claim_space_press(_event):
                return "break"
            app._space_action_active = True
        if self._enabled and self._command is not None:
            try:
                self._command()
            finally:
                if app is not None:
                    app._space_action_active = False
        elif app is not None:
            app._space_action_active = False
        return "break"

    def _enter(self, _event=None) -> None:
        if self._enabled:
            self._hovering = True
            if self._held:
                self._pressed = True
            self._draw()

    def _leave(self, _event=None) -> None:
        if self._hovering or self._pressed:
            self._hovering = False
            self._pressed = False
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


class _Scrollbar(tk.Canvas):
    """Slim rounded-thumb scrollbar.

    Same yview protocol as a stock scrollbar (the list canvas drives it via
    yscrollcommand; drags and track clicks call back into the canvas), drawn
    as a quiet rounded thumb so readers do not carry native chrome.
    """

    WIDTH = 10
    MIN_THUMB = 30

    def __init__(
        self, parent: tk.Widget, command: Callable, *, takefocus: bool = False
    ) -> None:
        bg = parent.cget("bg")
        super().__init__(
            parent,
            width=self.WIDTH,
            highlightthickness=0,
            bd=0,
            bg=bg,
            takefocus=1 if takefocus else 0,
        )
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._drag_off: Optional[float] = None
        self._focused = False
        self.bind("<Configure>", lambda _e: self._draw_thumb())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", self._wheel)
        self.bind("<Button-5>", self._wheel)
        if takefocus:
            self.bind("<FocusIn>", lambda _e: self._set_focused(True))
            self.bind("<FocusOut>", lambda _e: self._set_focused(False))
            self.bind("<Up>", lambda _e: self._key_scroll(-1, "units"))
            self.bind("<Down>", lambda _e: self._key_scroll(1, "units"))
            self.bind("<Prior>", lambda _e: self._key_scroll(-1, "pages"))
            self.bind("<Next>", lambda _e: self._key_scroll(1, "pages"))
            self.bind("<Home>", lambda _e: self._key_move(0.0))
            self.bind("<End>", lambda _e: self._key_move(1.0))

    def set(self, first, last) -> None:
        self._first, self._last = float(first), float(last)
        self._draw_thumb()

    def _thumb_span(self) -> Optional[tuple]:
        height = self.winfo_height()
        if height <= 1:
            return None
        if self._first <= 0.001 and self._last >= 0.999:
            return None  # everything fits: no thumb at all
        y0 = self._first * height
        y1 = self._last * height
        if y1 - y0 < self.MIN_THUMB:
            y1 = y0 + self.MIN_THUMB
            if y1 > height:
                y0, y1 = height - self.MIN_THUMB, float(height)
        return y0, y1

    def _draw_thumb(self) -> None:
        self.delete("thumb")
        span = self._thumb_span()
        if span is None:
            return
        y0, y1 = span
        if self._focused:
            color = FOCUS
        elif self._drag_off is not None:
            color = BORDER_STRONG
        else:
            color = _mix(BORDER_STRONG, BG, 0.35)
        _round_rect(
            self, 2, y0 + 2, self.WIDTH - 2, max(y1 - 2, y0 + 4), 4,
            fill=color, outline="", tags="thumb",
        )

    def _set_focused(self, focused: bool) -> None:
        self._focused = focused
        self._draw_thumb()

    def _key_scroll(self, steps: int, what: str) -> str:
        self._command("scroll", steps, what)
        return "break"

    def _key_move(self, first: float) -> str:
        self._command("moveto", first)
        return "break"

    def _wheel(self, event) -> Optional[str]:
        if getattr(event, "num", None) == 5:
            steps = 1
        elif getattr(event, "num", None) == 4:
            steps = -1
        elif event.delta:
            steps = -1 if event.delta > 0 else 1
        else:
            return None
        self._command("scroll", steps, "units")
        return "break"

    def _press(self, event) -> None:
        span = self._thumb_span()
        if span is not None and span[0] <= event.y <= span[1]:
            self._drag_off = event.y - span[0]
            self._draw_thumb()
        else:
            self._command("scroll", 1 if span and event.y > span[1] else -1, "pages")

    def _drag(self, event) -> None:
        if self._drag_off is None:
            return
        height = max(1, self.winfo_height())
        span = max(1e-6, self._last - self._first)
        first = (event.y - self._drag_off) / height
        first = max(0.0, min(1.0 - span, first))
        self._command("moveto", first)

    def _release(self, _event) -> None:
        if self._drag_off is not None:
            self._drag_off = None
            self._draw_thumb()


class _CheckRow(tk.Frame):
    """Checkbox + label using the shared check icon. Replaces native Checkbutton."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        text: str,
        variable: tk.BooleanVar,
        command: Callable[[], None],
        font: tkfont.Font,
        wraplength: int = 0,
    ) -> None:
        bg = parent.cget("bg")
        super().__init__(
            parent,
            bg=bg,
            takefocus=1,
            highlightthickness=2,
            highlightbackground=bg,
            highlightcolor=FOCUS,
            cursor="hand2",
        )
        self._text = text
        self._variable = variable
        self._command = command
        self._font = font
        self._wraplength = wraplength
        self._base_bg = bg
        self._hovering = False
        self._held = False
        self._pressed = False
        self._icon: Optional[tk.Canvas] = None
        self._label = tk.Label(
            self, text=text, font=font, fg=INK, bg=bg, justify=tk.LEFT, anchor="w",
            wraplength=wraplength or 0,
        )
        self._label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 4), pady=6)
        self._sync()
        self._paint()
        variable.trace_add("write", self._on_variable)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<space>", self._activate)
        self.bind("<Return>", self._activate)
        self.bind("<KP_Enter>", self._activate)
        self._label.bind("<ButtonPress-1>", self._press)
        self._label.bind("<ButtonRelease-1>", self._release)

    def cget(self, key):
        if key == "text":
            return self._text
        return super().cget(key)

    def _on_variable(self, *_args) -> None:
        self._sync()
        self._paint()

    def _row_bg(self) -> str:
        if self._pressed:
            return "#E2E8EE"
        if bool(self._variable.get()):
            return PRIMARY_TINT
        if self._hovering:
            return SURFACE_ALT
        return self._base_bg

    def _paint(self) -> None:
        bg = self._row_bg()
        self.configure(bg=bg)
        self._label.configure(bg=bg)
        if self._icon is not None:
            try:
                self._icon.configure(bg=bg)
            except tk.TclError:
                pass

    def _enter(self, _event=None) -> None:
        self._hovering = True
        if self._held:
            self._pressed = True
        self._paint()

    def _leave(self, _event=None) -> None:
        self._hovering = False
        self._pressed = False
        self._paint()

    def _press(self, _event=None) -> str:
        self.focus_set()
        self._held = True
        self._pressed = True
        self._paint()
        return "break"

    def _release(self, event=None) -> str:
        held = self._held
        self._held = False
        self._pressed = False
        inside = True
        if event is not None:
            try:
                inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
            except tk.TclError:
                inside = True
        self._paint()
        if held and inside:
            self.invoke()
        return "break"

    def _activate(self, _event=None) -> str:
        self.invoke()
        return "break"

    def invoke(self) -> None:
        self._variable.set(not bool(self._variable.get()))
        self._command()

    def _sync(self) -> None:
        if self._icon is not None:
            self._icon.destroy()
        bg = self._row_bg()
        icon = _icon_check_box(self, bool(self._variable.get()), 22)
        icon.configure(bg=bg)
        icon.pack(side=tk.LEFT, anchor="n", pady=6, before=self._label)
        icon.bind("<ButtonPress-1>", self._press)
        icon.bind("<ButtonRelease-1>", self._release)
        self._icon = icon


class TkWizard:
    def __init__(self, wizard: Wizard, fullscreen: bool = False) -> None:
        self.w = wizard
        self.root = tk.Tk()
        self.root._tk_wizard = self  # type: ignore[attr-defined]
        # Set the geometry scale; fonts below use explicit pixel sizes. The layout geometry below is fixed pixels (content
        # column, minimum window, countdown ring), so point-sized fonts must
        # not float with the X server's reported DPI — on a 100+ DPI panel
        # every screen would render ~1.4x larger than designed and clip.
        # The kiosk window owns the whole display; deterministic type beats
        # DPI fidelity. (macOS Tk already renders at scaling 1.0.)
        self.root.tk.call("tk", "scaling", 1.0)
        title = C.APP_NAME
        if wizard.preview:
            title = f"{C.APP_NAME} — PREVIEW (nothing is erased)"
        self.root.title(title)
        # Familiar arrow over ordinary content. The bare startx kiosk has
        # no window manager or cursor theme, so an unset root inherits the
        # X-server X cursor. Children inherit this; explicit hand2/xterm
        # cursors on actions and text are unaffected.
        self.root.configure(bg=BG, cursor="arrow")
        self.root.minsize(*MIN_SIZE)
        if fullscreen:
            # The live startx kiosk has no window manager to honor the EWMH
            # fullscreen hint. Pin geometry too, or content-driven sizing
            # can feed back into responsive redraws and starve key releases.
            self.root.geometry(
                f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0"
            )
            self.root.attributes("-fullscreen", True)
        else:
            width, height = opening_size(
                self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            )
            self.root.geometry(f"{width}x{height}")
        family = _family(self.root)
        mono = _mono_family(self.root)
        # Negative Tk font sizes are pixels. Tk 9 on macOS can adjust its
        # point scale after mapping a window; pixel sizes keep text and our
        # geometry in agreement. Type scale follows window size (compact on
        # 800x600, slightly larger on 1600x1000+), never the X server DPI.
        self.lay = layout_for(*DEFAULT_SIZE)
        self.font_hero = tkfont.Font(root=self.root, family=family, size=-52, weight="bold")
        self.font_h = tkfont.Font(root=self.root, family=family, size=-30, weight="bold")
        self.font_lead = tkfont.Font(root=self.root, family=family, size=-18)
        self.font_b = tkfont.Font(root=self.root, family=family, size=-16)
        self.font_bold = tkfont.Font(root=self.root, family=family, size=-16, weight="bold")
        self.font_size_big = tkfont.Font(root=self.root, family=family, size=-20, weight="bold")
        self.font_s = tkfont.Font(root=self.root, family=family, size=-14)
        self.font_s_bold = tkfont.Font(root=self.root, family=family, size=-14, weight="bold")
        self.font_tiny = tkfont.Font(root=self.root, family=family, size=-12, weight="bold")
        self.font_meta = tkfont.Font(root=self.root, family=family, size=-12)
        self.font_btn = tkfont.Font(root=self.root, family=family, size=-16, weight="bold")
        self.font_mono = tkfont.Font(root=self.root, family=mono, size=-14)
        self.font_mono_bold = tkfont.Font(root=self.root, family=mono, size=-14, weight="bold")
        self.font_mono_sm = tkfont.Font(root=self.root, family=mono, size=-13)
        self.font_entry = tkfont.Font(root=self.root, family=mono, size=-26, weight="bold")
        self.font_stat = tkfont.Font(root=self.root, family=family, size=-56, weight="bold")
        self.font_brand = tkfont.Font(root=self.root, family=family, size=-16, weight="bold")
        self._apply_fonts()
        # The brand mark ships as PNGs (Tk cannot draw the SVG source).
        # Bound to this app's root explicitly: tests run several roots per
        # process, and an unbound PhotoImage dies with the first root.
        self._logo_header = self._load_image("logo-header.png")
        self._logo_splash = self._load_image("logo-splash.png")
        self._support_qr: Optional[tk.PhotoImage] = None
        self._support_lead: Optional[tk.Label] = None
        self._support_copy_bound = False
        self._confirm_var = tk.StringVar()
        self._typing_var = tk.StringVar()
        self._owner_var = tk.IntVar(value=0)
        self._body: Optional[tk.Frame] = None
        self._footer: Optional[tk.Frame] = None
        self._header: Optional[tk.Canvas] = None
        self._strip: Optional[tk.Canvas] = None
        self._hint: Optional[tk.Frame] = None
        self._primary: Optional[_Button] = None
        # The splash hides the header/strip so the white field runs clean;
        # every other screen shows them. Tracked so re-packing stays ordered.
        self._chrome_shown = True
        self._countdown_ring: Optional[tk.Canvas] = None
        self._countdown_num: Optional[tk.Label] = None
        self._countdown_label: Optional[tk.Label] = None
        self._progress_label: Optional[tk.Label] = None
        self._progress_pct: Optional[tk.Label] = None
        self._progress_bar: Optional[tk.Canvas] = None
        self._indet = 0.0
        self._match_label: Optional[tk.Label] = None
        self._match_icon: Optional[tk.Canvas] = None
        self._match_pill: Optional[_Box] = None
        self._shown: Optional[Screen] = None
        self._shown_report_revision = -1
        self._after_id: Optional[str] = None
        # Pick-list scroll state: the list is rebuilt on every redraw, so the
        # scroll offset is saved before teardown and restored (or the selected
        # card scrolled into view after keyboard navigation) after rebuild.
        self._pick_canvas: Optional[tk.Canvas] = None
        self._pick_cards: dict = {}
        self._pick_scroll = 0.0  # pixel offset into the list, not a fraction
        self._pick_ensure_visible = False
        self._pick_restore_pending = False
        self._pick_applied: Optional[float] = None
        self._pick_applied_geometry: Optional[tuple[float, float]] = None
        self._pick_after_ids: list[str] = []
        self._pick_gen = 0
        self._refresh_lock = threading.Lock()
        self._refresh_results: dict = {}
        self._refresh_threads: dict = {}
        self._ui_dead = False
        self._return_held = False
        self._return_release_after: Optional[str] = None
        self._return_release_time: Optional[int] = None
        self._space_held = False
        self._space_release_after: Optional[str] = None
        self._space_release_time: Optional[int] = None
        self._space_action_active = False
        self._f5_held = False
        self._fatal_ui = False
        self._accessible_requested = False
        # Optional extra detail (device path, bus) on existing screens.
        # One flag for the session; not a new wizard step.
        self._show_more = False
        self._body_inner: Optional[tk.Frame] = None
        self._body_canvas: Optional[tk.Canvas] = None
        self._ring_px = self.lay.ring
        self._layout_drawing = False
        self._build_chrome()
        self.root.bind("<Configure>", self._on_root_configure)
        self._confirm_var.trace_add("write", self._confirm_var_written)
        self._typing_var.trace_add("write", self._typing_var_written)
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<KP_Enter>", self._on_return)
        self.root.bind("<Return>", self._on_return)
        self.root.bind("<KeyRelease-Return>", self._on_return_release)
        self.root.bind("<KeyRelease-KP_Enter>", self._on_return_release)
        self.root.bind("<KeyRelease-space>", self._on_space_release)
        self.root.bind("<KeyRelease-F5>", self._on_f5_release)
        self.root.bind("<Key>", self._on_key)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._draw()
        self._after_id = self.root.after(100, self._tick)

    # -- chrome -------------------------------------------------------------

    def _build_chrome(self) -> None:
        if self.w.preview:
            # Content-sized stripe: a fixed height clipped the label on
            # Linux Tk, where DejaVu metrics run taller than macOS.
            stripe = tk.Frame(self.root, bg=PREVIEW_BG)
            stripe.pack(fill=tk.X)
            tk.Label(
                stripe,
                text=C.PREVIEW_BANNER,
                fg=PREVIEW_FG,
                bg=PREVIEW_BG,
                font=self.font_s_bold,
            ).pack(side=tk.LEFT, padx=24, pady=7)
        self._header = tk.Canvas(
            self.root, height=self.lay.header_h, bg=BG, highlightthickness=0, bd=0
        )
        self._header.pack(fill=tk.X)
        self._header.bind("<Configure>", lambda _e: self._draw_header())
        self._strip = tk.Canvas(self.root, height=2, bg=TRACK, highlightthickness=0)
        self._strip.pack(fill=tk.X)
        self._strip.bind("<Configure>", lambda _e: self._draw_strip())
        # Pack the footer first: when a small screen cannot fit everything,
        # pack clips the last-packed widget, and the action buttons must be
        # the last thing that ever gets clipped.
        self._footer = tk.Frame(self.root, bg=BG)
        self._footer.pack(fill=tk.X, side=tk.BOTTOM)
        self._body = tk.Frame(self.root, bg=BG)
        self._body.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        self._apply_grid()

    def _apply_grid(self) -> None:
        for area, expand in ((self._body, True), (self._footer, False)):
            if area is None:
                continue
            area.grid_columnconfigure(0, weight=1)
            area.grid_columnconfigure(1, minsize=self.lay.content_w, weight=0)
            area.grid_columnconfigure(2, weight=1)
            area.grid_rowconfigure(0, weight=1 if expand else 0)

    def _apply_fonts(self) -> None:
        px = self.lay.font
        self.font_hero.configure(size=-px["hero"])
        self.font_h.configure(size=-px["h"])
        self.font_lead.configure(size=-px["lead"])
        self.font_b.configure(size=-px["b"])
        self.font_bold.configure(size=-px["b"])
        self.font_size_big.configure(size=-px["size_big"])
        self.font_s.configure(size=-px["s"])
        self.font_s_bold.configure(size=-px["s"])
        self.font_tiny.configure(size=-px["tiny"])
        self.font_meta.configure(size=-px["tiny"])
        self.font_btn.configure(size=-px["btn"])
        self.font_mono.configure(size=-px["mono"])
        self.font_mono_bold.configure(size=-px["mono"])
        self.font_mono_sm.configure(size=-px["mono_sm"])
        self.font_entry.configure(size=-px["entry"])
        self.font_stat.configure(size=-px["stat"])
        self.font_brand.configure(size=-px["brand"])

    def _sync_layout(self) -> bool:
        """Match fonts and wrap to the mapped window. Returns True if layout changed."""
        root = getattr(self, "root", None)
        if root is None or not hasattr(root, "winfo_width"):
            if not hasattr(self, "lay"):
                self.lay = layout_for(*DEFAULT_SIZE)
            return False
        try:
            width = root.winfo_width()
            height = root.winfo_height()
        except tk.TclError:
            return False
        if width < 2 or height < 2:
            return False
        new = layout_for(width, height)
        if new.key == self.lay.key:
            self.lay = new
            return False
        self.lay = new
        self._apply_fonts()
        if self._header is not None:
            self._header.configure(height=self.lay.header_h)
        self._apply_grid()
        return True

    def _on_root_configure(self, event) -> None:
        if event.widget is not self.root or self._layout_drawing:
            return
        if self._sync_layout():
            self._layout_drawing = True
            try:
                self._draw()
            finally:
                self._layout_drawing = False

    def _load_image(self, name: str) -> Optional[tk.PhotoImage]:
        try:
            return tk.PhotoImage(master=self.root, file=str(_ASSETS / name))
        except (tk.TclError, RuntimeError):
            # Missing/unreadable file, or no root window yet: the drawn
            # fallback emblem stands in for the brand mark.
            return None

    def _draw_header(self) -> None:
        cv = self._header
        if cv is None:
            return
        width = cv.winfo_width()
        height = cv.winfo_height()
        if width <= 1 or height <= 1:
            return
        cv.delete("all")
        # Quiet white chrome: the navy-on-transparent mark sits on the
        # field, a hairline separates header from body. No navy chip.
        cv.create_rectangle(-2, -2, width + 2, height + 2, fill=BG, outline="")
        cv.create_rectangle(0, height - 1, width, height, fill=BORDER, outline="")
        mid = height / 2.0 - 1
        logo = self._logo_header
        x = 24.0
        if logo is not None:
            cv.create_image(x, mid, image=logo, anchor="w")
            text_x = x + logo.width() + 12
        else:
            _draw_emblem(cv, x + 13, mid, 26)
            text_x = x + 26 + 12
        cv.create_text(
            text_x, mid, anchor="w",
            text=C.APP_NAME, font=self.font_brand, fill=INK,
        )
        # The screen title below names the page. The header names the stage
        # (Preparation, Erase, Result) and never a wipe percent.
        step = _STEP_ORDER.get(self.w.screen, (0, "", ""))
        self._draw_journey(cv, width, step[0])
        label = header_caption(step[0], step[1])
        if label:
            cv.create_text(
                width - 24, mid, anchor="e",
                text=label, font=self.font_meta, fill=MUTED,
            )

    def _draw_journey(self, cv: tk.Canvas, width: int, step: int) -> None:
        # Three named stages, never eight equal pages or success badges.
        if not step or width < 1000:
            return
        start, end = 260, width - 150
        gap = (end - start) / len(C.JOURNEY_LABELS)
        for index, name in enumerate(C.JOURNEY_LABELS, 1):
            cx = start + gap * (index - 0.5)
            active = index == step
            if index < len(C.JOURNEY_LABELS):
                cv.create_line(cx + 13, 18, cx + gap - 13, 18, fill=BORDER, width=1)
            cv.create_oval(cx - 10, 8, cx + 10, 28,
                           fill=PRIMARY if active else SURFACE_ALT,
                           outline=PRIMARY if active else BORDER_STRONG)
            cv.create_text(cx, 18, text=str(index), font=self.font_tiny,
                           fill=SURFACE if active else MUTED)
            cv.create_text(cx, 42, text=name, font=self.font_meta,
                           fill=PRIMARY if active else MUTED)

    def _draw_strip(self) -> None:
        cv = self._strip
        if cv is None:
            return
        cv.delete("all")
        width = cv.winfo_width()
        if width <= 1:
            return
        stage = C.journey_stage(self.w.screen)
        count = len(C.JOURNEY_LABELS)
        gap = 2.0
        segment = (width - gap * (count - 1)) / count
        for index in range(count):
            x0 = index * (segment + gap)
            x1 = x0 + segment
            fill = ACCENT if (index + 1) == stage else TRACK
            _round_rect(cv, x0, 0, x1, 2, 1, fill=fill, outline="")

    def _sync_chrome(self, splash: bool) -> None:
        """The splash drops the header and progress strip so the first
        screen is one plain white field; every other screen shows them.
        Re-pack before the body so the chrome keeps its place on top."""
        if self._header is None or self._strip is None or self._body is None:
            return
        if splash and self._chrome_shown:
            self._header.pack_forget()
            self._strip.pack_forget()
            self._chrome_shown = False
        elif not splash and not self._chrome_shown:
            self._header.pack(fill=tk.X, before=self._body)
            self._strip.pack(fill=tk.X, before=self._body)
            self._chrome_shown = True

    def _column(self, parent: Optional[tk.Widget], *, fill_height: bool, bg: str = BG) -> tk.Frame:
        assert parent is not None
        host = parent
        if parent is self._body and self._body_inner is not None:
            host = self._body_inner
            col = tk.Frame(host, bg=bg)
            col.pack(fill=tk.BOTH if fill_height else tk.X, expand=fill_height)
            return col
        col = tk.Frame(host, bg=bg)
        col.grid(row=0, column=1, sticky="nsew" if fill_height else "ew")
        return col

    def _prepare_body_host(self) -> None:
        self._body_inner = None
        self._body_canvas = None
        if self._body is None or not (self.lay.short or self.w.screen in {Screen.WHAT, Screen.METHOD, Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE, Screen.DIAGNOSTIC}):
            return
        if self.w.screen in {
            Screen.PICK,
            Screen.LIMITS,
            Screen.DISK_HELP,
            Screen.REPORT_HELP,
        }:
            return
        host = tk.Frame(self._body, bg=BG)
        host.grid(row=0, column=1, sticky="nsew")
        canvas = tk.Canvas(host, bg=BG, highlightthickness=0, bd=0)
        scroll = _Scrollbar(host, canvas.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._body.grid_rowconfigure(0, weight=1)
        inner = tk.Frame(canvas, bg=BG)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_inner(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))

        def on_canvas(event) -> None:
            canvas.itemconfigure(window, width=max(1, event.width))

        inner.bind("<Configure>", on_inner)
        canvas.bind("<Configure>", on_canvas)

        def wheel(event) -> str:
            steps = int(-event.delta / 120) if event.delta else 0
            if steps:
                canvas.yview_scroll(steps, "units")
            return "break"

        canvas.bind("<MouseWheel>", wheel)
        inner.bind("<MouseWheel>", wheel)
        canvas.bind("<Button-4>", lambda _e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda _e: canvas.yview_scroll(1, "units"))
        self._body_canvas = canvas
        self._body_inner = inner

    def _clear(self, frame: tk.Frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _nav(self, fn: Callable[[], None]) -> Callable[[], None]:
        expected_screen = self.w.screen
        generation = getattr(self, "_draw_generation", 0)

        def wrapped() -> None:
            if self.w.screen != expected_screen or generation != getattr(self, "_draw_generation", 0):
                return
            fn()
            if self.w.wants_shutdown or self.w.wants_new_session:
                self._teardown()
                return
            self._arm_shutdown_enter_if_idle()
            self._draw()

        return wrapped

    def _arm_shutdown_enter_if_idle(self) -> None:
        if self._return_held or self._space_held:
            return
        if self.w.screen in (Screen.DONE, Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            self.w.arm_done_keyboard()

    def _teardown(self) -> None:
        # In-flight scans finish into the void: polls stop here and any late
        # worker result finds no owner. Workers are daemons; join them only.
        self._ui_dead = True
        self._cancel_pick_restore()
        for attr in ("_return_release_after", "_space_release_after"):
            callback = getattr(self, attr)
            if callback is not None:
                try:
                    self.root.after_cancel(callback)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _tick(self) -> None:
        try:
            prev = self._shown
            self.w.tick()
            if self.w.screen != prev:
                self._arm_shutdown_enter_if_idle()
            if self.w.wants_shutdown or self.w.wants_new_session:
                self._teardown()
                return
            if self.w.screen != prev:
                self._draw()
            elif self.w.screen in {Screen.DONE, Screen.DIAGNOSTIC, Screen.WORKING} and (
                self.w.report_view.revision != self._shown_report_revision
            ):
                self._draw()
            elif self.w.screen == Screen.LAST_CHANCE:
                self._refresh_last_chance()
            elif self.w.screen in {Screen.WORKING, Screen.STOPPING}:
                self._refresh_working()
            power_label = getattr(self, "_power_label", None)
            if power_label is not None:
                power_label.configure(text=self.w.power_text)
            self._after_id = self.root.after(100, self._tick)
        except Exception as exc:
            # Tk otherwise swallows callback exceptions and leaves the timer
            # unscheduled, so a running erase would lose status monitoring.
            self._after_id = None
            self._fatal_ui = True
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("ui", "tk_runtime_failed", type(exc).__name__)
            except Exception:
                pass
            if self.w.screen in {Screen.CHECKING, Screen.WORKING, Screen.STOPPING}:
                try:
                    self.w.interface_failed()
                except Exception as cancel_exc:
                    try:
                        from beamo_wipe.diagnostics import log_diag

                        log_diag("ui", "tk_failure_cancel_failed", type(cancel_exc).__name__)
                    except Exception:
                        pass
            self._teardown()

    def _draw(self) -> None:
        sync = getattr(self, "_sync_layout", None)
        if callable(sync):
            sync()
        self._draw_generation = getattr(self, "_draw_generation", 0) + 1
        assert self._body is not None and self._footer is not None
        if self._pick_canvas is not None:
            try:
                bbox = self._pick_canvas.bbox("all")
                content_h = float(bbox[3]) if bbox else 1.0
                # Save the offset in pixels: the rebuilt list has the same
                # rows, so only a pixel offset survives the content height's
                # transient states while the new layout settles.
                self._pick_scroll = self._pick_canvas.yview()[0] * max(1.0, content_h)
            except tk.TclError:
                pass
            self._cancel_pick_restore()
            self._pick_canvas = None
            self._pick_cards = {}
            self._pick_restore_pending = False
        self._clear(self._body)
        self._clear(self._footer)
        self._support_lead = None
        unbind = getattr(self, "_unbind_support_copy", None)
        if callable(unbind):
            unbind()
        prepare = getattr(self, "_prepare_body_host", None)
        if callable(prepare):
            prepare()
        self._primary = None
        self._countdown_ring = None
        self._countdown_num = None
        self._countdown_label = None
        self._progress_label = None
        self._progress_pct = None
        self._progress_bar = None
        self._match_label = None
        self._match_icon = None
        self._match_pill = None
        self._power_label: Optional[tk.Label] = None
        screen = self.w.screen
        report_view = self.w.report_view if screen == Screen.DONE else None
        working_revision = self.w.report_view.revision if screen == Screen.WORKING else None
        diagnostic_view = self.w.diagnostic_view if screen == Screen.DIAGNOSTIC else None
        self._sync_chrome(screen == Screen.SPLASH)
        self._body.configure(bg=BG)
        dispatch = {
            Screen.SPLASH: self._splash,
            Screen.KEYBOARD: lambda: self._keyboard(),
            Screen.WHAT: self._what,
            Screen.OWNER: self._owner,
            Screen.PICK: self._pick,
            Screen.DISK_HELP: self._disk_help,
            Screen.PICK_BLOCKED: self._blocked,
            Screen.PICK_EMPTY: self._empty,
            Screen.CONFIRM: self._confirm,
            Screen.METHOD: self._method,
            Screen.LAST_CHANCE: self._last,
            Screen.CHECKING: lambda: self._status_screen(
                "info", C.BUSY_CHECKING_TITLE,
                C.BUSY_CHECKING_MESSAGE,
            ),
            Screen.STOPPING: lambda: self._status_screen(
                "warn", C.BUSY_STOPPING_TITLE,
                C.STOPPING_TEXT,
            ),
            Screen.WORKING: self._working,
            Screen.ADVANCED: self._advanced,
            Screen.LIMITS: self._limits,
            Screen.REPORT_HELP: self._report_help,
            Screen.SHUTDOWN_CONFIRM: self._shutdown_confirm,
            Screen.REFRESH_CONFIRM: self._refresh_confirm,
            Screen.REFRESHING: lambda: self._status_screen(
                "info",
                C.BUSY_REFRESHING_TITLE,
                C.BUSY_REFRESHING_MESSAGE,
            ),
        }
        if report_view is not None:
            self._done(report_view)
        elif diagnostic_view is not None:
            self._diagnostic(diagnostic_view)
        else:
            dispatch[screen]()
        self._draw_header()
        self._draw_strip()
        self._shown = screen
        if working_revision is not None:
            self._shown_report_revision = working_revision
        if diagnostic_view is not None:
            self._shown_report_revision = diagnostic_view.revision
        if report_view is not None:
            # Record the exact snapshot rendered above. If a worker published
            # a newer revision mid-draw, _tick will render it on the next pass.
            self._shown_report_revision = report_view.revision
        # Emit only fixed state names after the full screen is rendered. These
        # bounded markers let the isolated QEMU gate synchronize with the real
        # shipped Tk workflow without exposing disk identifiers or log data.
        emit_serial_marker(f"BEAMO_WIPE_SCREEN_{screen.name}")
        if screen == Screen.PICK_BLOCKED:
            # Diagnostics may contain identifiers; only established code
            # values may cross the serial/hosted-log boundary.
            code = "boot_unidentified"
            for candidate in (
                getattr(self.w, "startup_error_code", ""),
                getattr(self.w.discovery, "error_code", ""),
            ):
                if isinstance(candidate, str) and candidate in D.CODES:
                    code = candidate
                    break
            emit_serial_marker(f"BEAMO_WIPE_DISCOVERY_{code.upper()}")
        if report_view is not None:
            emit_serial_marker(f"BEAMO_WIPE_REPORT_{report_view.status.upper()}")

    # -- text / small components --------------------------------------------

    def _h(self, parent: tk.Widget, text: str, *, bg: str = BG, fg: str = INK) -> tk.Label:
        return tk.Label(
            parent, text=text, font=self.font_h, fg=fg, bg=bg,
            wraplength=self.lay.wrap, justify=tk.LEFT,
        )

    def _p(self, parent: tk.Widget, text: str, **kw) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            font=kw.get("font", self.font_lead),
            fg=kw.get("fg", INK),
            bg=kw.get("bg", BG),
            wraplength=kw.get("wraplength", self.lay.wrap),
            justify=kw.get("justify", tk.LEFT),
            anchor=kw.get("anchor", "w"),
        )

    def _title_block(
        self,
        col: tk.Frame,
        title: str,
        subtitle: Optional[str] = None,
        *,
        compact: bool = False,
    ) -> None:
        """The one screen-header pattern: bold title, optional muted subtitle.

        Every working screen opens with the same rhythm so the eye lands in
        the same place on each step. ``compact`` squeezes the method screen
        further; short and narrow windows already use compact layout pads.
        """
        top = min(10, self.lay.title_top) if compact else self.lay.title_top
        bottom = min(6, self.lay.title_bottom) if compact else self.lay.title_bottom
        tk.Label(
            col, text=title, font=self.font_h, fg=INK, bg=BG,
            wraplength=self.lay.wrap, justify=tk.LEFT, anchor="w",
        ).pack(fill=tk.X, pady=(top, 4 if subtitle else bottom))
        if subtitle:
            self._p(col, subtitle, fg=MUTED, font=self.font_b).pack(
                fill=tk.X, pady=(0, bottom)
            )

    def _center_zone(self, col: tk.Frame) -> tk.Frame:
        """Keep supporting content close to its heading, with room below."""
        zone = tk.Frame(col, bg=BG)
        zone.pack(fill=tk.BOTH, expand=True)
        content = tk.Frame(zone, bg=BG)
        content.pack(fill=tk.X, pady=(4, 0))
        return content

    def _reader(
        self,
        parent: tk.Widget,
        *,
        height: int,
        wrap: Literal["none", "char", "word"] = "word",
        bg: str = SURFACE_ALT,
        padx: int = 12,
        pady: int = 8,
    ) -> tk.Text:
        """Flat readable text surface. Replaces native sunken Text chrome."""
        return tk.Text(
            parent,
            wrap=wrap,
            font=self.font_s,
            takefocus=True,
            width=1,
            height=height,
            bg=bg,
            fg=INK,
            relief=tk.FLAT,
            bd=0,
            padx=padx,
            pady=pady,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=FOCUS,
            insertbackground=INK,
            selectbackground=PRIMARY_TINT,
            selectforeground=INK,
            cursor="xterm",
        )

    def _chip(self, parent: tk.Widget, text: str, *, fg: str, bg: str) -> _Box:
        chip = _Box(parent, radius=PILL, fill=bg, outline=None, ow=0, padx=10, pady=2)
        tk.Label(chip.inner, text=text, font=self.font_tiny, fg=fg, bg=bg).pack()
        chip.fit_now()
        return chip

    def _kbd(self, parent: tk.Widget, text: str) -> _Box:
        """A quiet keyboard key-cap. Makes keyboard affordances scannable."""
        cap = _Box(parent, radius=8, fill=SURFACE_ALT, outline=BORDER_STRONG, ow=1, padx=8, pady=2)
        tk.Label(cap.inner, text=text, font=self.font_tiny, fg=INK, bg=SURFACE_ALT).pack()
        cap.fit_now()
        return cap

    def _hint_bar(self, parent: tk.Widget, hint: str) -> tk.Frame:
        """Hint copy with known key names rendered as key-caps."""
        bar = tk.Frame(parent, bg=BG)
        inner = tk.Frame(bar, bg=BG)
        inner.pack(anchor="w")
        pos = 0
        for match in _KEY_TOKEN_RE.finditer(hint):
            if match.start() > pos:
                self._hint_text(inner, hint[pos:match.start()])
            for key in _KEY_TOKEN_KEYS.get(match.group(0), (match.group(0),)):
                self._kbd(inner, key).pack(side=tk.LEFT, padx=(0, 4))
            pos = match.end()
        if pos < len(hint):
            self._hint_text(inner, hint[pos:])
        return bar

    def _hint_text(self, parent: tk.Widget, text: str) -> None:
        if not text:
            return
        tk.Label(
            parent, text=text, font=self.font_s, fg=MUTED, bg=BG, anchor="w",
        ).pack(side=tk.LEFT)

    def _panel(
        self,
        parent: tk.Widget,
        *,
        kind: str,
        text: str,
        extra: Optional[str] = None,
        compact: bool = False,
    ) -> _Box:
        colors = {
            "warn": (WARN_BG, WARN_BORDER),
            "danger": (DANGER_TINT, DANGER_BORDER),
            "info": (SURFACE_ALT, BORDER),
            "ok": (OK_TINT, OK_BORDER),
            "limits": (SURFACE_ALT, BORDER),
        }
        # Severity words: the label line keeps every non-neutral panel
        # readable in monochrome. Neutral info stays unlabeled.
        labels = {
            "warn": (C.SEVERITY_WARNING, WARN),
            "danger": (C.SEVERITY_ERROR, DANGER),
            "ok": (C.SEVERITY_SAVED, OK),
            "limits": (C.SEVERITY_LIMITS, PRIMARY),
        }
        bg, border = colors[kind]
        box = _Box(parent, radius=RADIUS, fill=bg, outline=border, ow=1,
                   padx=16, pady=8 if compact else 13)
        row = tk.Frame(box.inner, bg=bg)
        row.pack(fill=tk.X)
        icon = _icon_alert(row, kind, 28)
        icon.configure(bg=bg)
        icon.pack(side=tk.LEFT, anchor="n", pady=1)
        lines = tk.Frame(row, bg=bg)
        lines.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0))
        if kind in labels:
            word, color = labels[kind]
            tk.Label(lines, text=word, font=self.font_s_bold, fg=color, bg=bg,
                     anchor="w").pack(fill=tk.X, pady=(0, 2))
        # Panels carry disk names, models, and errors: same wrapping as
        # identity labels, including unbroken serials and paths.
        self._wrapping_label(
            lines, text, font=self.font_s if compact else self.font_b, bg=bg,
        ).pack(fill=tk.X)
        if extra:
            self._wrapping_label(
                lines, extra, font=self.font_s, fg=MUTED, bg=bg,
            ).pack(fill=tk.X, pady=(4, 0))
        return box

    def _bind_tree(self, widget: tk.Misc, click) -> None:
        widget.bind("<Button-1>", click)
        for child in widget.winfo_children():
            self._bind_tree(child, click)

    def _bind_hover(
        self,
        widget: tk.Widget,
        on_enter: Callable[[], None],
        on_leave: Callable[[], None],
    ) -> None:
        def collect(w: tk.Misc) -> List[tk.Misc]:
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
                node: Optional[tk.Misc] = ptr
                while node is not None:
                    if node == widget:
                        return
                    node = node.master
                on_leave()

            widget.after(10, check)

        for w in collect(widget):
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _kind_chip(self, parent: tk.Widget, disk: Disk) -> None:
        label = C.kind_label(disk.kind)
        if not label:
            return
        self._chip(parent, label, fg=MUTED, bg=SURFACE_ALT).pack(
            side=tk.LEFT, padx=(10, 0)
        )

    def _recovery_block(
        self,
        parent: tk.Widget,
        sections: RecoverySections,
        *,
        bg: str = BG,
        omit_duplicate_happened: str = "",
    ) -> None:
        """What happened, meaning, next; technical details separately.

        When the screen heading already is What happened, skip a second
        Label with that same text so outcome lookups keep the heading.
        Technical detail is a muted line, not a button: Done tab order
        stays Show more then Save report.
        """
        from beamo_wipe import recovery as Rec

        frame = tk.Frame(parent, bg=bg)
        frame.pack(fill=tk.X, pady=(4, 0), anchor="w")
        for label, body in sections.labeled_pairs():
            skip_body = (
                omit_duplicate_happened
                and label == Rec.RECOVERY_HAPPENED
                and body == omit_duplicate_happened
            )
            if self.lay.short:
                text = label if skip_body else f"{label}: {body}"
                self._p(frame, text, font=self.font_s, bg=bg).pack(
                    fill=tk.X, pady=(4, 0)
                )
                continue
            tk.Label(
                frame,
                text=label,
                font=self.font_s_bold,
                fg=INK,
                bg=bg,
                anchor="w",
            ).pack(fill=tk.X, pady=(8, 0))
            if skip_body:
                continue
            self._p(frame, body, font=self.font_s, bg=bg).pack(fill=tk.X)
        if not sections.technical:
            return
        self._p(
            frame,
            f"{Rec.RECOVERY_TECHNICAL}: {sections.technical}",
            font=self.font_s,
            fg=MUTED,
            bg=bg,
        ).pack(fill=tk.X, pady=(4, 0))

    def _more_link(self, parent: tk.Widget, *, bg: str = BG) -> bool:
        """Optional details use the shared, keyboard-accessible control."""
        open_ = self._show_more

        def toggle() -> None:
            self._show_more = not self._show_more
            self._draw()
            # Rebuilding destroys the old control. Keep keyboard users at
            # the disclosure rather than moving them to Continue.
            self._more_button.focus_set()

        self._more_button = _Button(
            parent, text=C.BTN_LESS if open_ else C.BTN_MORE,
            command=toggle, font=self.font_s_bold, variant="ghost", compact=True,
        )
        self._more_button.pack(anchor="w", pady=(4, 0))
        return open_

    def _wrapping_label(self, parent: tk.Widget, text: str, *, font, bg: str,
                        fg: str = INK) -> tk.Label:
        """Wrap the full identity to its allocated width, never ellipsize it.

        Card interiors are canvas windows. Their width settles after layout,
        so a fixed wrap length still clips valid long models and serials.
        Observe the allocated parent width without feeding the label's
        requested width back into the layout.
        """
        base = max(200, self.lay.wrap - 120)
        def displayed(width):
            # Native word wrapping preserves prose and avoids double wrapping
            # explicit newlines at spaces. Split only when a token cannot fit.
            if all(font.measure(token) <= width for token in text.split()):
                return text
            return _soft_break_tokens(text, font.measure, width)

        label = tk.Label(parent, text=displayed(base),
                         font=font, fg=fg, bg=bg,
                         anchor="w", justify=tk.LEFT, wraplength=base)
        def fit(event) -> None:
            width = max(1, event.width - 4)
            if int(label.cget("wraplength")) != width:
                # Long serials and device paths have no spaces for Tk to
                # wrap at; re-chunk to the actual allocation on resize.
                broken = displayed(width)
                if broken != str(label.cget("text")):
                    label.configure(text=broken)
                label.configure(wraplength=width)
        parent.bind("<Configure>", fit, add="+")
        label.pack(fill=tk.X)
        return label

    def _disk_heading(self, parent: tk.Widget, disk: Disk, bg: str) -> None:
        # Reserve capacity before the expandable model column; long names
        # must not push the capacity or type out of the card.
        view = self.w.disk_view(disk)
        top = tk.Frame(parent, bg=bg)
        top.pack(fill=tk.X)
        tk.Label(top, text=view.capacity, font=self.font_size_big,
                 fg=INK, bg=bg, anchor="e").pack(side=tk.RIGHT, anchor="n", padx=(16, 0))
        name = tk.Frame(top, bg=bg)
        name.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._wrapping_label(name, view.title, font=self.font_bold, bg=bg)

    def _meta_line(self, parent: tk.Widget, disk: Disk, bg: str) -> tk.Frame:
        """Model, capacity, connection, and strongest identifier. Path is not identity."""
        view = self.w.disk_view(disk)
        meta = tk.Frame(parent, bg=bg)
        chip = " · ".join(part for part in (view.kind_chip, view.connection) if part)
        if chip:
            conn = tk.Label(meta, text=chip, font=self.font_s,
                     fg=MUTED, bg=bg, anchor="e")
            conn.pack(side=tk.RIGHT, anchor="n", padx=(16, 0))
            setattr(conn, "_beamo_connection", True)
        identity = tk.Frame(meta, bg=bg)
        identity.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(identity, text=view.id_label, font=self.font_meta,
                 fg=MUTED, bg=bg).pack(side=tk.LEFT, anchor="n", padx=(0, 8), pady=2)
        value = tk.Frame(identity, bg=bg)
        value.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._wrapping_label(value, view.marked_id, font=self.font_mono_bold, bg=bg)
        for note in view.notes:
            self._wrapping_label(value, note, font=self.font_s, fg=MUTED, bg=bg)
        if self._show_more:
            from beamo_wipe.identity import SYSTEM_PATH_NOTE

            self._wrapping_label(
                value,
                f"{SYSTEM_PATH_NOTE}: {view.system_path}",
                font=self.font_mono_sm,
                fg=MUTED,
                bg=bg,
            )
            self._wrapping_label(
                value, C.CAPACITY_UNIT_NOTE, font=self.font_s, fg=MUTED, bg=bg
            )
        return meta

    def _disk_summary(self, parent: tk.Widget, disk: Disk) -> _Box:
        """The selected disk, shared across confirmation, method, and result screens."""
        box = _Box(
            parent, radius=RADIUS, fill=PRIMARY_TINT, outline=PRIMARY, ow=1,
            padx=18, pady=12, shadow=False,
        )
        inner = box.inner
        tk.Label(inner, text=C.SELECTED_DISK, font=self.font_tiny,
                 fg=PRIMARY, bg=PRIMARY_TINT, anchor="w").pack(fill=tk.X, pady=(0, 6))
        self._disk_heading(inner, disk, PRIMARY_TINT)
        self._meta_line(inner, disk, PRIMARY_TINT).pack(fill=tk.X, pady=(4, 0))
        return box

    # -- footer / buttons -----------------------------------------------------

    def _close_label(self) -> str:
        return C.BTN_CLOSE_PREVIEW if self.w.preview else C.BTN_SHUTDOWN

    def _footer_shell(self, hint: str) -> tk.Frame:
        """Assist strip (utilities and keyboard hints) above a hairline;
        navigation is Back/secondary left and the primary action right.
        Buttons pack into ``row._left`` / ``row._right``."""
        assert self._footer is not None
        col = self._column(self._footer, fill_height=False)
        assist = tk.Frame(col, bg=BG)
        assist.pack(fill=tk.X, pady=(0, 4))
        tools = tk.Frame(assist, bg=BG)
        tools.pack(fill=tk.X)

        tool_row = tk.Frame(tools, bg=BG)
        tool_row.pack(anchor="w")
        tool_width = 0

        def utility(text: str, command: Callable[[], None]) -> None:
            nonlocal tool_row, tool_width
            button = _Button(tool_row, text=text, font=self.font_s, command=command,
                             variant="ghost", compact=True)
            width = button.winfo_reqwidth() + 4
            # Enlarged fonts must not expand the fixed footer beyond the
            # window. Keep every utility available in compact stacked rows.
            if tool_width and tool_width + width > self.lay.content_w:
                button.destroy()
                tool_row = tk.Frame(tools, bg=BG)
                tool_row.pack(anchor="w")
                tool_width = 0
                button = _Button(tool_row, text=text, font=self.font_s, command=command,
                                 variant="ghost", compact=True)
            button.pack(side=tk.LEFT, padx=(0, 4))
            tool_width += width

        if self.w.screen == Screen.METHOD:
            utility(C.BTN_ADVANCED, self._nav(self.w.open_advanced))
        if self.w.can_open_keyboard and self.w.screen != Screen.KEYBOARD:
            utility(C.KEYBOARD_UTILITY, self._nav(self.w.open_keyboard))
        if self.w.can_refresh and self.w.screen != Screen.REFRESH_CONFIRM:
            utility(C.BTN_REFRESH_UTILITY, self._click_refresh)
            if self.w.can_open_report_help:
                utility(C.REPORT_HELP_TITLE, self._nav(self.w.open_report_help))
            if sys.platform.startswith("linux"):
                utility(C.SCREEN_READER_VIEW, self._click_accessible)
        if self.w.can_open_diagnostic:
            utility(C.DIAGNOSTIC_TITLE, self._nav(self.w.open_diagnostic))
        if self.w.screen == Screen.DONE and not self.w.preview:
            note = tk.Label(
                assist, text=C.ANOTHER_HINT, font=self.font_s, bg=BG,
                fg=MUTED, wraplength=self.lay.content_w, justify=tk.LEFT,
                anchor="w",
            )
            # width=1 so the unwrapped sentence cannot stretch the footer
            # past an 1024-wide window; fill=X uses the content column.
            note.configure(width=1)
            note.pack(fill=tk.X, pady=(4, 0))
        if self.lay.short:
            self._hint = self._p(assist, hint, font=self.font_s, fg=MUTED,
                                 wraplength=self.lay.content_w - 8)
            self._hint.configure(width=1)
        else:
            self._hint = self._hint_bar(assist, hint)
        self._hint.pack(fill=tk.X, pady=(4, 0))
        tk.Frame(col, bg=BORDER, height=1).pack(fill=tk.X)
        row = tk.Frame(col, bg=BG)
        pad = self.lay.footer_pad_y
        row.pack(fill=tk.X, pady=(max(8, pad - 4), pad))
        # Left first so Tab from Back reaches the primary. Left actions
        # still wrap if they would collide with the reserved primary width.
        # The primary cluster is packed next so it stays on the right edge
        # of the content column. Hints stay in the assist strip so Done's
        # four left actions plus Shut down still fit the 940px column.
        left_host = tk.Frame(row, bg=BG)
        left_host.pack(side=tk.LEFT, anchor="n")
        left = tk.Frame(left_host, bg=BG)
        left.pack(anchor="w")
        right = tk.Frame(row, bg=BG)
        right.pack(side=tk.RIGHT, anchor="n")
        row._left_host = left_host  # type: ignore[attr-defined]
        row._left = left  # type: ignore[attr-defined]
        row._left_width = 0  # type: ignore[attr-defined]
        row._right = right  # type: ignore[attr-defined]
        return row

    def _footer_left_parent(self, row: tk.Frame, width: int) -> tk.Frame:
        """Next left-action row that still leaves room for the primary."""
        budget = max(280, self.lay.content_w - 168)
        used = getattr(row, "_left_width", 0)
        if used and used + width > budget:
            left = tk.Frame(row._left_host, bg=BG)  # type: ignore[attr-defined]
            left.pack(anchor="w")
            row._left = left  # type: ignore[attr-defined]
            row._left_width = 0  # type: ignore[attr-defined]
        row._left_width = getattr(row, "_left_width", 0) + width  # type: ignore[attr-defined]
        return row._left  # type: ignore[attr-defined]

    def _back_btn(self, row: tk.Frame) -> _Button:
        compact = self.lay.compact
        pad_x = 12 if compact else 24
        width = max(112, self.font_btn.measure(C.BTN_BACK) + 2 * pad_x + 6)
        btn = _Button(
            self._footer_left_parent(row, width),
            text=C.BTN_BACK,
            command=self._nav(self.w.back),
            font=self.font_btn,
            variant="secondary",
            compact=compact,
            min_width=112,
        )
        btn.pack(side=tk.LEFT)
        return btn

    def _secondary_btn(
        self,
        row: tk.Frame,
        text: str,
        command: Callable[[], None],
        enabled: bool = True,
    ) -> _Button:
        compact = self.lay.compact
        pad_x = 12 if compact else 24
        width = self.font_btn.measure(text) + 2 * pad_x + 6
        btn = _Button(
            self._footer_left_parent(row, width),
            text=text,
            command=self._nav(command),
            font=self.font_btn,
            variant="secondary",
            enabled=enabled,
            compact=compact,
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
        btn = _Button(
            row._right,  # type: ignore[attr-defined]
            text=text,
            command=self._nav(command),
            font=self.font_btn,
            variant="danger" if danger else "primary",
            enabled=enabled,
            min_width=160,
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
        """The product open: a plain white field, the mark, one action.

        No chrome, no footer, no key-caps, no ornament — the single
        obvious next step is the Continue pill, and the any-key shortcut
        is a quiet caption under it (the global key handlers still skip
        the splash on any key, Enter, or Esc). The navy-on-transparent
        mark sits directly on the field; no navy tile.
        """
        col = self._column(self._body, fill_height=True)
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        logo = self._logo_splash
        if logo is not None:
            mark = tk.Label(col, image=logo, bg=BG, bd=0, highlightthickness=0)
            mark.pack()
        else:
            canvas_mark = tk.Canvas(col, width=70, height=58, bg=BG, highlightthickness=0, bd=0)
            _draw_emblem(canvas_mark, 35.0, 29.0, 54)
            canvas_mark.pack()
        tk.Label(col, text=C.APP_NAME, font=self.font_hero, fg=INK, bg=BG).pack(pady=(16, 0))
        self._p(
            col, C.SPLASH_TAGLINE, fg=MUTED, font=self.font_lead,
            wraplength=620, justify=tk.CENTER, anchor="center",
        ).pack(fill=tk.X, pady=(8, 0))
        self._p(col, C.SPLASH_ROADMAP, fg=MUTED, font=self.font_s,
                justify=tk.CENTER, anchor="center").pack(fill=tk.X, pady=(14, 0))
        hero = _Button(
            col,
            text=C.primary_action(Screen.SPLASH),
            command=self._nav(self.w.skip_splash),
            font=self.font_btn,
            variant="primary",
            large=True,
            min_width=240,
        )
        hero.pack(pady=(24, 0))
        self._primary = hero
        tk.Label(col, text=C.HINT_SPLASH, font=self.font_meta, fg=MUTED, bg=BG).pack(pady=(14, 0))
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        hero.focus_set()

    def _keyboard(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_KEYBOARD, C.KEYBOARD_LEAD)
        zone = self._center_zone(col)
        self._p(zone, C.KEYBOARD_LIMITS, font=self.font_s, fg=MUTED).pack(fill=tk.X)
        for index, layout_id in enumerate(LAYOUT_ORDER, 1):
            spec = _keyboard.LAYOUTS[layout_id]
            selected = self.w.keyboard_layout == layout_id
            fill = PRIMARY_TINT if selected else SURFACE
            outline = PRIMARY if selected else BORDER_STRONG
            card = _Box(
                zone, radius=RADIUS, fill=fill, outline=outline, ow=2 if selected else 1,
                padx=16, pady=10, halo=False,
            )
            card.pack(fill=tk.X, pady=(6, 0))
            inner = card.inner
            top = tk.Frame(inner, bg=fill)
            top.pack(fill=tk.X)
            icon = _icon_radio(top, selected, 22)
            icon.configure(bg=fill)
            icon.pack(side=tk.LEFT, anchor="n", pady=1)
            self._kbd(top, str(index)).pack(side=tk.RIGHT, anchor="n")
            text_col = tk.Frame(top, bg=fill)
            text_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 8))
            tk.Label(
                text_col, text=spec.title, font=self.font_bold, fg=INK, bg=fill, anchor="w",
            ).pack(fill=tk.X)
            tk.Label(
                text_col, text=spec.note, font=self.font_s, fg=MUTED, bg=fill,
                wraplength=max(200, self.lay.wrap - 110), justify=tk.LEFT, anchor="w",
            ).pack(fill=tk.X, pady=(4, 0))

            def _click(_e=None, lid=layout_id):
                self.w.set_keyboard_layout(lid)
                self._draw()
                return "break"

            self._bind_tree(card, _click)
            card.configure(cursor="hand2")
            inner.configure(cursor="hand2")
            if not selected:
                self._bind_hover(
                    card,
                    partial(card.set_style, fill=SURFACE_ALT),
                    partial(card.set_style, fill=SURFACE),
                )
        tk.Label(
            zone, text=C.TITLE_LANGUAGE, font=self.font_bold, fg=INK, bg=BG, anchor="w",
        ).pack(fill=tk.X, pady=(14, 2))
        self._p(zone, C.LANGUAGE_LEAD, font=self.font_s, fg=MUTED).pack(fill=tk.X)
        lang_row = tk.Frame(zone, bg=BG)
        lang_row.pack(fill=tk.X, pady=(6, 0))
        for code in LANGUAGE_ORDER:
            selected = self.w.language == code

            def _pick_language(_e=None, lang_code=code):
                self.w.set_language(lang_code)
                self._draw()
                return "break"

            chip = _Box(
                lang_row, radius=PILL, fill=PRIMARY_TINT if selected else SURFACE,
                outline=PRIMARY if selected else BORDER_STRONG, ow=2 if selected else 1,
                padx=14, pady=6, halo=False,
            )
            chip.pack(side=tk.LEFT, padx=(0, 8))
            tk.Label(
                chip.inner, text=LANGUAGE_NAMES[code], font=self.font_s_bold,
                fg=PRIMARY if selected else INK,
                bg=PRIMARY_TINT if selected else SURFACE,
            ).pack()
            self._bind_tree(chip, _pick_language)
            chip.configure(cursor="hand2")
            chip.inner.configure(cursor="hand2")
        if self.w.error:
            sections = recovery_for_wizard_error(self.w.error)
            if sections:
                self._recovery_block(zone, sections)
            else:
                self._panel(zone, kind="danger", text=self.w.error).pack(fill=tk.X, pady=(12, 0))
        elif self.w.keyboard_message:
            self._panel(zone, kind="warn", text=self.w.keyboard_message).pack(fill=tk.X, pady=(12, 0))
        tk.Label(
            zone, text=C.KEYBOARD_CHECK_LABEL, font=self.font_s, fg=INK, bg=BG, anchor="w",
        ).pack(fill=tk.X, pady=(10, 4))
        shell = _Box(
            zone, radius=RADIUS, fill=SURFACE, outline=BORDER_STRONG, ow=1,
            padx=16, pady=10, ring=True, shadow=False,
        )
        shell.pack(fill=tk.X)
        entry = tk.Entry(
            shell.inner,
            textvariable=self._typing_var,
            font=self.font_entry,
            fg=INK,
            bg=SURFACE,
            insertbackground=INK,
            selectbackground=PRIMARY_TINT,
            selectforeground=INK,
            relief=tk.FLAT,
            highlightthickness=0,
            show="",
            bd=0,
            cursor="xterm",
        )
        self._typing_var.set(self.w.typing_check)
        entry.pack(fill=tk.X, ipady=4)
        entry.bind("<FocusIn>", lambda _e: shell.set_focused(True))
        entry.bind("<FocusOut>", lambda _e: shell.set_focused(False))
        shell.set_focused(True)
        entry.focus_set()
        row = self._footer_shell(C.HINT_KEYBOARD)
        if self.w._keyboard_from:
            self._back_btn(row)
        self._primary_btn(row, C.primary_action(Screen.KEYBOARD), self.w.accept_keyboard)

    def _typing_var_written(self, *_a) -> None:
        if self.w.screen != Screen.KEYBOARD:
            return
        self.w.set_typing_check(self._typing_var.get())

    def _power_notice(self, parent, *, reminder=True, bg: str = BG, indent: int = 0) -> None:
        if reminder:
            self._wrapping_label(parent, C.POWER_KEEP, font=self.font_s_bold, bg=bg)
        label = self._p(parent, self.w.power_text, font=self.font_s, bg=bg)
        label.configure(width=1)
        label.pack(fill=tk.X, padx=(indent, 0), pady=(4 if indent else 0, 0))
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(1, event.width - 4)))
        self._power_label = label

    def _what(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_WHAT, C.WHAT_LEAD)
        zone = self._center_zone(col)
        card = _Box(
            zone, radius=RADIUS, fill=SURFACE, outline=BORDER, ow=1,
            padx=20, pady=14, shadow=False,
        )
        card.pack(fill=tk.X)
        for i, bullet in enumerate(C.WHAT_BULLETS):
            line = tk.Frame(card.inner, bg=SURFACE)
            line.pack(fill=tk.X, pady=(2 if i == 0 else 8, 2 if i == len(C.WHAT_BULLETS) - 1 else 0))
            marker = tk.Canvas(line, width=10, height=26, bg=SURFACE, highlightthickness=0)
            marker.create_oval(1, 9, 8, 16, fill=ACCENT, outline="")
            marker.pack(side=tk.LEFT, anchor="n")
            tk.Label(
                line, text=bullet, font=self.font_lead, fg=INK, bg=SURFACE,
                wraplength=max(200, self.lay.wrap - 80), justify=tk.LEFT, anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        self._panel(
            zone, kind="info", text=C.REPORT_MEDIA_WHAT, compact=True
        ).pack(fill=tk.X, pady=(12, 0))
        power = self._panel(
            zone, kind="info", text=C.POWER_REMINDER, extra=C.POWER_BLANKING
        )
        power.pack(fill=tk.X, pady=(12, 0))
        self._power_notice(power.inner, reminder=False, bg=SURFACE_ALT, indent=40)
        if self._more_link(zone):
            self._panel(
                zone,
                kind="info",
                text=C.this_usb_line(),
                extra=C.SECURE_BOOT_HINT + " " + C.ENGINE_LINE + " " + C.POWER_EVENTS,
            ).pack(fill=tk.X, pady=(12, 0))
        self._support_identity_block(zone)
        row = self._footer_shell(C.HINT_DEFAULT)
        self._secondary_btn(row, self._close_label(), self._click_shutdown)
        self._primary_btn(row, C.primary_action(Screen.WHAT), self.w.accept_what)
        if self._primary is not None:
            self._primary.focus_set()

    def _owner(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._owner_var.set(1 if self.w.owner_ok else 0)
        self._title_block(col, C.TITLE_OWNER, C.OWNER_LEAD)
        zone = self._center_zone(col)
        checked = bool(self.w.owner_ok)
        card = _Box(
            zone,
            radius=RADIUS,
            fill=PRIMARY_TINT if checked else SURFACE,
            outline=PRIMARY if checked else BORDER_STRONG,
            ow=2 if checked else 1,
            padx=16,
            pady=14,
            ring=True,
            halo=False,
        )
        card.pack(fill=tk.X)
        card.configure(cursor="hand2", takefocus=1)
        box = _icon_check_box(card.inner, checked, 28)
        box.configure(bg=card._fill)
        box.pack(side=tk.LEFT, anchor="n", pady=2)
        text = tk.Label(
            card.inner,
            text=C.OWNER_CHECKBOX,
            font=self.font_lead,
            fg=INK,
            bg=card._fill,
            wraplength=max(200, self.lay.wrap - 100),
            justify=tk.LEFT,
            anchor="w",
        )
        text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 0))
        self._bind_tree(card, self._owner_clicked)
        card.bind("<space>", self._owner_key)
        card.bind("<FocusIn>", lambda _e: card.set_focused(True))
        card.bind("<FocusOut>", lambda _e: card.set_focused(False))
        card.focus_set()
        row = self._footer_shell(C.HINT_OWNER)
        self._back_btn(row)
        self._primary_btn(row, C.primary_action(Screen.OWNER), self.w.continue_owner, enabled=self.w.owner_ok)

    def _owner_clicked(self, _event=None) -> str:
        self._owner_var.set(0 if self._owner_var.get() else 1)
        self._owner_toggled()
        return "break"

    def _owner_key(self, _event=None) -> str:
        """Toggle ownership once per physical Space press."""
        if not self._claim_space_press(_event):
            return "break"
        self._space_action_active = True
        try:
            return self._owner_clicked(_event)
        finally:
            self._space_action_active = False

    def _owner_toggled(self) -> None:
        self.w.set_owner(bool(self._owner_var.get()))
        self._draw()
        if self.w.owner_ok:
            emit_serial_marker("BEAMO_WIPE_OWNER_CHECKED")

    def _disk_row(self, parent: tk.Widget, disk: Disk, selected: bool) -> _Box:
        if disk.is_boot:
            fill, outline, ow = USB_BG, USB_BORDER, 1
        elif selected:
            fill, outline, ow = PRIMARY_TINT, PRIMARY, 2
        else:
            fill, outline, ow = SURFACE, BORDER, 1
        card = _Box(
            parent, radius=RADIUS, fill=fill, outline=outline, ow=ow,
            padx=20, pady=12, halo=False,
        )
        card.pack(fill=tk.X, pady=(0, 10), padx=4)
        inner = card.inner
        top = tk.Frame(inner, bg=fill)
        top.pack(fill=tk.X)
        if disk.is_boot:
            icon = _icon_no_entry(top, 22)
        else:
            icon = _icon_radio(top, selected, 22)
        icon.configure(bg=fill)
        icon.pack(side=tk.LEFT, anchor="n", pady=1)
        title_col = tk.Frame(top, bg=fill)
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        if disk.is_boot:
            banner = C.BOOT_USB_BANNER if disk.bus == "USB" else C.BOOT_DISC_BANNER
            self._p(title_col, banner, font=self.font_s_bold, bg=fill,
                    wraplength=max(200, self.lay.wrap - 100)).pack(fill=tk.X, pady=(0, 6))
        self._disk_heading(title_col, disk, fill)
        self._meta_line(title_col, disk, fill).pack(fill=tk.X, pady=(4, 0))
        nested = inventory.card_nesting_text(self.w.nested_components(disk))
        if nested:
            nest = tk.Frame(title_col, bg=fill)
            nest.pack(fill=tk.X, pady=(8, 0))
            setattr(nest, "_beamo_nested", True)
            self._wrapping_label(
                nest, nested, font=self.font_s, bg=fill, fg=MUTED
            )
        if disk.is_boot:
            return card

        def _click(_e, p=disk.path):
            self._click_disk(p)
            return "break"

        self._bind_tree(card, _click)
        card.configure(cursor="hand2")
        inner.configure(cursor="hand2")
        if not selected:
            self._bind_hover(
                card,
                partial(card.set_style, fill=SURFACE_ALT),
                partial(card.set_style, fill=SURFACE),
            )
        return card

    def _pick(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_PICK, C.pick_subtitle())
        _Button(col, text=C.DISK_HELP_BUTTON, command=self._nav(self.w.open_disk_help),
                font=self.font_s_bold, variant="ghost", compact=True).pack(anchor="w", pady=(0, 4))
        if same_size_conflict(self.w.listed_disks):
            self._panel(col, kind="warn", text=C.SAME_SIZE_HINT).pack(fill=tk.X, pady=(0, 12))
        if self.w.error:
            sections = recovery_for_wizard_error(self.w.error)
            if sections:
                self._recovery_block(col, sections)
            else:
                self._panel(col, kind="danger", text=self.w.error).pack(fill=tk.X, pady=(0, 12))
            if error_needs_support(self.w.error):
                self._support_block(col)
        elif any(not self.w.disk_view(disk).confirmable for disk in self.w.selectable):
            from beamo_wipe.identity import AMBIGUOUS_IDENTITY

            self._panel(col, kind="warn", text=AMBIGUOUS_IDENTITY).pack(fill=tk.X, pady=(0, 12))
        if self.w.selected and self.w.selected.kind in (DiskKind.SSD, DiskKind.NVME):
            self._panel(col, kind="limits", text=C.SSD_FOOTER, compact=True).pack(fill=tk.X, pady=(0, 8))
        if self.w.report_wanted:
            self._panel(col, kind="info", text=C.REPORT_MEDIA_WANTED, compact=True).pack(fill=tk.X, pady=(0, 8))
        tools = tk.Frame(col, bg=BG)
        tools.pack(fill=tk.X, pady=(0, 4))
        count = self._p(
            tools,
            self.w.inventory_count,
            font=self.font_s,
            fg=MUTED,
            wraplength=max(160, self.lay.wrap - 160),
        )
        setattr(count, "_beamo_inventory_count", True)
        count.pack(side=tk.LEFT, fill=tk.X, expand=True)
        more = tk.Frame(tools, bg=BG)
        more.pack(side=tk.RIGHT, anchor="n")
        self._more_link(more)
        list_wrap = tk.Frame(col, bg=BG)
        list_wrap.pack(fill=tk.BOTH, expand=True, pady=(2, 4))
        canvas = tk.Canvas(list_wrap, bg=BG, highlightthickness=0)
        cards = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=cards, anchor="nw")

        def _stretch(_event=None) -> None:
            canvas.itemconfigure(window_id, width=max(1, canvas.winfo_width()))
            canvas.configure(scrollregion=canvas.bbox("all"))
            if self._pick_ensure_visible:
                self._pick_restore_pending = True
            self._pick_restore_scroll()

        cards.bind("<Configure>", _stretch)
        canvas.bind("<Configure>", _stretch)

        def _user_scrolled(*args) -> None:
            # The restore window only re-applies the pre-rebuild offset; the
            # first real scroll input ends it so the user owns the position.
            self._pick_restore_pending = False
            self._pick_ensure_visible = False
            self._pick_applied = None
            if args:
                canvas.yview(*args)

        scroll = _Scrollbar(list_wrap, _user_scrolled)
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
            _user_scrolled()
            canvas.yview_scroll(steps, "units")
            return "break"

        for widget in (canvas, cards):
            widget.bind("<MouseWheel>", _wheel)
            widget.bind("<Button-4>", _wheel)
            widget.bind("<Button-5>", _wheel)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        boot_card = self._protected_boot(cards)
        if boot_card is not None:
            def boot_wheel(widget):
                for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    widget.bind(sequence, _wheel)
                for child in widget.winfo_children():
                    boot_wheel(child)
            boot_wheel(boot_card)
        self._comparison(cards)
        items: List = sorted(self.w.selectable, key=lambda d: d.path)
        for disk in items:
            selected = self.w.selected is not None and disk.path == self.w.selected.path
            card = self._disk_row(cards, disk, selected)
            self._pick_cards[disk.path] = card
            # Wrapped identities can reposition a row after the canvas's
            # total bounds have settled. Restore on row geometry too, so a
            # keyboard-selected disk remains visible through that last pass.
            card.bind("<Configure>", _stretch, add="+")
            # Tk wheel events do not bubble from a row's labels to its
            # scrolling canvas. Scroll where the pointer actually rests,
            # without changing the disk selection or moving keyboard focus.
            def bind_wheel(widget):
                for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    widget.bind(sequence, _wheel)
                for child in widget.winfo_children():
                    bind_wheel(child)
            bind_wheel(card)
        self._pick_canvas = canvas
        # Restore only inside a short post-rebuild window. Row boxes and the
        # footer resolve their heights over several Configure/idle passes and
        # the view height can oscillate while settling, clamping any offset
        # applied against a transient geometry — so the window re-applies on
        # a few timed retries, and closes early only when a scroll the
        # restore itself did not make (user wheel/drag) is detected.
        self._pick_restore_pending = True
        self._pick_applied = None
        self._pick_applied_geometry = None
        self._pick_gen += 1
        gen = self._pick_gen
        self._pick_after_ids = [
            canvas.after_idle(lambda: self._pick_restore_tick(gen)),
            canvas.after(30, lambda: self._pick_restore_tick(gen)),
            canvas.after(90, lambda: self._pick_restore_tick(gen)),
            canvas.after(180, lambda: self._pick_restore_tick(gen, final=True)),
        ]
        # Keep the informational inventory in the same scrolling region.
        # It must not consume the picker viewport on short laptop screens.
        self._other_devices(cards)
        row = self._footer_shell(C.HINT_PICK)
        back = self._back_btn(row)
        can = self.w.selected is not None and not self.w.selected.is_boot
        self._primary_btn(row, C.primary_action(Screen.PICK), self.w.continue_pick, enabled=can)
        # Always land keyboard focus somewhere sensible: the obvious next
        # action when a disk is chosen, otherwise the safe way out.
        (self._primary if can and self._primary is not None else back).focus_set()

    def _comparison(self, parent) -> None:
        entries = inventory.comparison_entries(self.w.selectable, peers=self.w.listed_disks)
        if len(entries) < 2:
            return
        section = tk.Frame(parent, bg=BG)
        section.pack(fill=tk.X, pady=(0, 10))
        content = tk.Frame(section, bg=BG)
        opened = tk.BooleanVar(value=False)
        def toggle():
            if opened.get():
                content.pack(fill=tk.X)
            else:
                content.pack_forget()
        toggle_button = _CheckRow(
            section, text=inventory.COMPARE_TITLE, variable=opened,
            command=toggle, font=self.font_s_bold,
        )
        toggle_button.pack(anchor="w")
        intro = self._p(content, inventory.COMPARE_INTRO, font=self.font_s)
        intro.pack(fill=tk.X)
        content.bind("<Configure>", lambda e: intro.configure(wraplength=max(1, e.width - 12)))
        grid = tk.Frame(content, bg=BG)
        grid.pack(fill=tk.X)
        cells = []
        for entry in entries:
            cell = tk.Frame(
                grid, bg=SURFACE_ALT, highlightbackground=BORDER,
                highlightthickness=1, padx=8, pady=8,
            )
            cells.append(cell)
            reader = self._reader(cell, height=8, wrap=tk.CHAR, padx=10)
            reader.insert("1.0", entry)
            reader.configure(state=tk.DISABLED)
            scrollbar = _Scrollbar(cell, reader.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            reader.configure(yscrollcommand=scrollbar.set)
            reader.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            setattr(reader, "_beamo_comparison", True)
            for key, delta in (("Up", -1), ("Down", 1), ("Prior", -6), ("Next", 6)):
                reader.bind(f"<{key}>", lambda e, r=reader, d=delta: (r.yview_scroll(d, "units"), "break")[1])
            for key in ("Return", "KP_Enter", "space"):
                reader.bind(f"<{key}>", lambda e: "break")
            reader.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
            reader.bind("<Shift-Tab>", lambda e: (e.widget.tk_focusPrev().focus_set(), "break")[1])
            def reveal(event):
                canvas = self._pick_canvas
                if canvas is not None and str(event.widget).startswith(str(canvas)):
                    self._pick_restore_pending = False
                    bounds = canvas.bbox("all")
                    if bounds:
                        top = event.widget.winfo_rooty() - canvas.winfo_rooty()
                        if top < 0 or top + event.widget.winfo_height() > canvas.winfo_height():
                            canvas.yview_moveto((canvas.canvasy(0) + top) / max(1, bounds[3]))
            reader.bind("<FocusIn>", reveal)
        def reflow(event):
            columns = 2 if event.width >= 700 else 1
            for column in range(2):
                grid.columnconfigure(column, weight=1 if column < columns else 0, uniform="compare")
            for i, cell in enumerate(cells):
                cell.grid(row=i // columns, column=i % columns, sticky="nsew", padx=6, pady=6)
        grid.bind("<Configure>", reflow)

    def _protected_boot(self, parent):
        if self.w.protected_boot is not None:
            card = self._disk_row(parent, self.w.protected_boot, False)
            setattr(card, "_beamo_protected_boot", True)
            return card
        return None


    def _other_devices(self, col, *, before=None) -> None:
        if not self.w.other_devices:
            return
        section = tk.Frame(col, bg=BG)
        section.pack(fill=tk.X, before=before)
        self._p(section, inventory.TITLE, font=self.font_s_bold).pack(fill=tk.X)
        frame = tk.Frame(section, bg=BG)
        frame.pack(fill=tk.X, pady=(4, 8))
        reader = self._reader(frame, height=2)
        setattr(reader, "_beamo_inventory", True)
        def read_key(event):
            delta = {"Up": -1, "Down": 1, "Prior": -3, "Next": 3}.get(event.keysym, 0)
            if delta:
                reader.yview_scroll(delta, "units")
            return "break"
        for key in ("Up", "Down", "Prior", "Next", "Return", "KP_Enter", "space"):
            reader.bind(f"<{key}>", read_key)
        scroll = _Scrollbar(frame, reader.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        reader.configure(yscrollcommand=scroll.set)
        reader.pack(side=tk.LEFT, fill=tk.X, expand=True)
        reader.insert("1.0", inventory.full_text(self.w.other_devices))
        reader.configure(state=tk.DISABLED)

    def _cancel_pick_restore(self) -> None:
        # Destroying a widget deletes its Tcl commands, but leaves after events
        # queued. Cancel them while the canvas still owns those commands.
        if self._pick_canvas is not None:
            for callback in self._pick_after_ids:
                try:
                    self._pick_canvas.after_cancel(callback)
                except tk.TclError:
                    pass
        self._pick_after_ids = []
        self._pick_restore_pending = False
        self._pick_applied = None
        self._pick_applied_geometry = None

    def _pick_restore_scroll(self) -> None:
        """Keep the rebuilt list where the user left it.

        Redraws destroy and rebuild the list canvas; without this the list
        snapped back to the top on every selection change. After keyboard
        navigation, scroll the selected card into view instead. Runs only
        while a post-rebuild restore is pending (see _pick), and repeats as
        the row boxes settle so the last pass uses final geometry.
        """
        canvas = self._pick_canvas
        if canvas is None or not self._pick_restore_pending:
            return
        try:
            bbox = canvas.bbox("all")
            if not bbox:
                return
            content_h = max(1.0, float(bbox[3]))
            view_h = float(canvas.winfo_height())
            if view_h <= 1.0:
                return
            current_top = canvas.yview()[0] * content_h
            geometry = (content_h, view_h)
            if (
                self._pick_applied is not None
                and self._pick_applied_geometry == geometry
                and abs(current_top - self._pick_applied) > 2
            ):
                # With stable geometry, an external yview call owns the scroll.
                # Layout changes can also move the offset by clamping it; those
                # must keep restoring as the selected row settles. Wheel/drag
                # handlers explicitly end restoration regardless of geometry.
                self._pick_restore_pending = False
                self._pick_applied = None
                return
            selected = self.w.selected
            card = self._pick_cards.get(selected.path) if selected else None
            if self._pick_ensure_visible and card is not None:
                view0 = current_top
                view1 = view0 + view_h
                y0 = float(card.winfo_y())
                y1 = y0 + float(card.winfo_height())
                # Wrapped identity ("Serial number" plus the value) can make
                # a card taller than the picker. Keep the heading in view
                # instead of bottom-aligning, which would hide the serial.
                if y1 - y0 > view_h:
                    canvas.yview_moveto(max(0.0, y0 / content_h))
                elif y0 < view0:
                    canvas.yview_moveto(max(0.0, y0 / content_h))
                elif y1 > view1:
                    canvas.yview_moveto(max(0.0, min(1.0, (y1 - view_h) / content_h)))
            else:
                canvas.yview_moveto(max(0.0, self._pick_scroll / content_h))
            self._pick_applied = canvas.yview()[0] * content_h
            self._pick_applied_geometry = geometry
        except tk.TclError:
            pass

    def _pick_restore_tick(self, gen: int, final: bool = False) -> None:
        """Timed restore retry while a rebuild's geometry settles (see _pick).

        The final tick restores once more — a scroll the user made in the
        meantime is detected by the offset check and left alone — and then
        closes the window.
        """
        if gen != self._pick_gen or not self._pick_restore_pending:
            return
        self._pick_restore_scroll()
        if final:
            self._pick_restore_pending = False
            self._pick_applied = None

    def _click_disk(self, path: str) -> None:
        self._pick_ensure_visible = False
        self.w.select_disk(path)
        self._draw()

    def _unbind_support_copy(self) -> None:
        if not getattr(self, "_support_copy_bound", False):
            return
        self.root.unbind("<Control-c>")
        self.root.unbind("<Control-C>")
        self._support_copy_bound = False

    def _copy_support_destination(self, _event: object = None) -> Optional[str]:
        from beamo_wipe.support_contact import SUPPORT_SHORT

        widget = self.root.focus_get()
        kind = widget.winfo_class() if widget is not None else ""
        if kind in {"Entry", "Text", "TEntry"}:
            return None
        self.root.clipboard_clear()
        self.root.clipboard_append(SUPPORT_SHORT)
        return "break"

    def _support_identity_block(self, parent: Optional[tk.Widget]) -> None:
        """Monospace support code and build id for screenshots and phone readback."""
        ident = self.w.support_identity
        if ident is None:
            return
        assert parent is not None
        frame = tk.Frame(parent, bg=BG)
        rows = [(C.SUPPORT_CODE_LABEL, ident.code)]
        if ident.extra_code:
            rows.append((C.SUPPORT_SAVE_LABEL, ident.extra_code))
        rows.append((C.SUPPORT_BUILD_LABEL, ident.build_id))
        wrap = max(120, self.lay.wrap - 40)
        for label, value in rows:
            line = tk.Frame(frame, bg=BG)
            line.pack(fill=tk.X)
            tk.Label(
                line, text=label, font=self.font_s, fg=MUTED, bg=BG, anchor="w"
            ).pack(side=tk.LEFT)
            tk.Label(
                line,
                text=value,
                font=self.font_mono_bold,
                fg=INK,
                bg=BG,
                anchor="w",
                wraplength=wrap,
                justify=tk.LEFT,
            ).pack(side=tk.LEFT, padx=(12, 0))
        if not self.lay.short:
            self._p(frame, C.SUPPORT_CODE_HINT, font=self.font_s, fg=MUTED, wraplength=wrap).pack(
                fill=tk.X, pady=(4, 0)
            )
        frame.pack(fill=tk.X, pady=(8, 0))

    def _support_block(self, parent: Optional[tk.Widget]) -> None:
        """QR code plus the support destination as real text.

        The text is the offline fallback: the block still helps when the
        QR library is unavailable or the code cannot be scanned. Ctrl+C
        copies the short address. The sentence is not in Tab order so
        Shut down → Show more → Save report stays two Tabs (QEMU).
        """
        from beamo_wipe.support_contact import QR_DISPLAY_SCALE, qr_matrix

        assert parent is not None
        frame = tk.Frame(parent, bg=BG)
        image: Optional[tk.PhotoImage] = None
        try:
            matrix = qr_matrix()
            scale = QR_DISPLAY_SCALE
            rows = []
            for modules in matrix:
                line = " ".join(
                    "#000000" if dark else "#ffffff"
                    for dark in modules
                    for _ in range(scale)
                )
                rows.extend(["{" + line + "}"] * scale)
            image = tk.PhotoImage(
                master=self.root, width=len(matrix) * scale, height=len(matrix) * scale
            )
            image.put(" ".join(rows))
        except Exception:
            image = None
        if image is not None:
            self._support_qr = image
            code = tk.Label(frame, image=image, bg="#ffffff", bd=1, relief=tk.SOLID)
            code.pack(side=tk.LEFT, anchor="n")
        text_wrap = tk.Frame(frame, bg=BG)
        text_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0))
        qr_space = (int(image.width()) + 24) if image is not None else 0
        lead = self._p(
            text_wrap,
            C.support_lead(),
            font=self.font_s,
            wraplength=max(200, self.lay.wrap - qr_space),
        )

        def _rewrap(event: object, lbl: tk.Label = lead) -> None:
            width = int(getattr(event, "width", 0) or 0)
            if width < 180:
                return
            lbl.configure(wraplength=max(200, width - 8))

        text_wrap.bind("<Configure>", _rewrap)
        lead.pack(anchor="w", fill=tk.X)
        self._support_lead = lead
        self.root.bind("<Control-c>", self._copy_support_destination)
        self.root.bind("<Control-C>", self._copy_support_destination)
        self._support_copy_bound = True
        frame.pack(fill=tk.X, pady=(12, 0))

    def _status_screen(self, kind: str, title: str, message: str) -> None:
        """Centered status layout shared by the blocked and empty screens."""
        col = self._column(self._body, fill_height=True)
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        icon = _icon_badge(col, kind, 88)
        icon.configure(bg=BG)
        icon.pack()
        heading = self._h(col, title)
        heading.configure(anchor="center", justify=tk.CENTER)
        heading.pack(fill=tk.X, pady=(22, 8))
        wrap = min(700, self.lay.wrap)
        self._p(
            # Blocked-screen errors carry discovery/exception text, which can
            # hold long device names: same character-level wrapping as identity.
            col, _soft_break_tokens(message, self.font_b.measure, wrap),
            fg=MUTED, font=self.font_b,
            wraplength=wrap, justify=tk.CENTER, anchor="center",
        ).pack(fill=tk.X)
        if self.w.screen in {Screen.CHECKING, Screen.STOPPING}:
            self._power_notice(col)
        if self.w.screen == Screen.STOPPING:
            self._progress_label = self._p(col, self.w.progress_view.timing_text, fg=MUTED)
            self._progress_label.pack(fill=tk.X, pady=(12, 0))
            stopping_disk = self.w.operation_disk
            if stopping_disk is not None:
                self._disk_summary(col, stopping_disk).pack(fill=tk.X, pady=(12, 0))
            elif self.w.operation_identity_text:
                self._p(col, self.w.operation_identity_text, font=self.font_b, fg=MUTED).pack(fill=tk.X, pady=(12, 0))
            self._p(col, self.w.operation_method_text, font=self.font_s, fg=MUTED).pack(fill=tk.X, pady=(12, 0))
        if self.w.screen == Screen.PICK_BLOCKED:
            if error_needs_support(self.w.error):
                self._support_block(col)
            self._support_identity_block(col)
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)

    def _blocked(self) -> None:
        col = self._column(self._body, fill_height=True)
        icon = _icon_badge(col, "danger", 88)
        icon.configure(bg=BG)
        icon.pack(pady=(8, 0))
        heading = self._h(col, C.blocked_title(self.w.error, recovered=self.w._recovered))
        heading.configure(anchor="w", justify=tk.LEFT)
        heading.pack(fill=tk.X, pady=(12, 4))
        self._recovery_block(
            col, recovery_for_blocked(self.w.error, recovered=self.w._recovered)
        )
        count = self._p(col, self.w.inventory_count, font=self.font_s, fg=MUTED)
        setattr(count, "_beamo_inventory_count", True)
        count.pack(fill=tk.X, pady=(8, 0))
        if error_needs_support(self.w.error):
            self._support_block(col)
        self._support_identity_block(col)
        row = self._footer_shell(C.HINT_BLOCKED)
        self._back_btn(row)
        self._primary_btn(row, self._close_label(), self._click_shutdown)
        if self._primary is not None:
            self._primary.focus_set()

    def _empty(self) -> None:
        col = self._column(self._body, fill_height=True)
        _icon_badge(col, "info", 40).pack(anchor="w")
        self._title_block(col, C.TITLE_EMPTY)
        count = self._p(col, self.w.inventory_count, font=self.font_s, fg=MUTED)
        setattr(count, "_beamo_inventory_count", True)
        count.pack(fill=tk.X, pady=(0, 8))
        region = tk.Frame(col, bg=BG)
        region.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(region, bg=BG, highlightthickness=0)
        cards = tk.Frame(canvas, bg=BG)
        window = canvas.create_window((0, 0), window=cards, anchor="nw")
        cards.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda _e: canvas.itemconfigure(window, width=canvas.winfo_width()))
        self._recovery_block(cards, recovery_for_empty())
        self._support_block(cards)
        self._support_identity_block(cards)
        scroll = _Scrollbar(region, canvas.yview, takefocus=True)
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

        def bind_wheel(widget):
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(sequence, _wheel)
            for child in widget.winfo_children():
                bind_wheel(child)

        bind_wheel(canvas)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._protected_boot(cards)
        self._other_devices(cards)
        bind_wheel(cards)
        row = self._footer_shell(C.HINT_BLOCKED)
        self._back_btn(row)
        self._primary_btn(row, self._close_label(), self._click_shutdown)
        if self._primary is not None:
            self._primary.focus_set()

    def _diagnostic(self, view) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, D.report_title(self.w.startup_error_code))
        self._recovery_block(
            col,
            recovery_for_diagnostic(
                self.w.startup_error_code,
                view.message,
                self.w.diagnostic_step,
            ),
        )
        if next_step_needs_support(self.w.diagnostic_message):
            self._support_block(col)
        self._support_identity_block(col)
        row = self._footer_shell(C.NO_OUTCOME_RECORDED)
        self._secondary_btn(row, C.BTN_BACK, self.w.close_diagnostic, enabled=not view.busy)
        self._primary_btn(row, C.SAVE_DIAGNOSTIC_REPORT if view.ready else C.BTN_PREPARE,
                          self._click_diagnostic_action,
                          enabled=not view.busy)

    def _click_diagnostic_action(self) -> None:
        self.w.diagnostic_action(background=True)

    def _confirm(self) -> None:
        disk = self.w.selected
        assert disk is not None
        spec = self.w.confirm
        if spec is None:
            from beamo_wipe.identity import AMBIGUOUS_IDENTITY

            self.w.error = AMBIGUOUS_IDENTITY
            self.w.screen = Screen.PICK
            self._pick()
            return
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_CONFIRM)
        zone = self._center_zone(col)
        self._disk_summary(zone, disk).pack(fill=tk.X)
        self._more_link(zone)
        self._panel(zone, kind="warn", text=self.w.warning_text()).pack(fill=tk.X, pady=(12, 0))
        self._p(
            zone,
            C.CONFIRM_KEYBOARD_LINE.format(
                layout=_keyboard.LAYOUTS[self.w.keyboard_layout].title,
                language=LANGUAGE_NAMES[self.w.language],
            ),
            font=self.font_s,
            fg=MUTED,
        ).pack(fill=tk.X, pady=(8, 0))
        # The prompt can carry a full serial as the typed token: same
        # character-level wrapping as identity labels, never a clipped tail.
        self._wrapping_label(zone, spec.prompt, font=self.font_b, bg=BG).pack(
            fill=tk.X, pady=(14, 8)
        )
        shell = _Box(
            zone, radius=RADIUS, fill=SURFACE, outline=BORDER_STRONG, ow=1,
            padx=16, pady=10, ring=True, shadow=False,
        )
        shell.pack(fill=tk.X)
        entry = tk.Entry(
            shell.inner,
            textvariable=self._confirm_var,
            font=self.font_entry,
            fg=INK,
            bg=SURFACE,
            insertbackground=INK,
            selectbackground=PRIMARY_TINT,
            selectforeground=INK,
            relief=tk.FLAT,
            highlightthickness=0,
            bd=0,
            cursor="xterm",
        )
        self._confirm_var.set(self.w.confirm_input)
        entry.pack(fill=tk.X, ipady=4)
        entry.bind("<FocusIn>", lambda _e: shell.set_focused(True))
        entry.bind("<FocusOut>", lambda _e: shell.set_focused(False))
        shell.set_focused(True)
        entry.focus_set()
        entry.after_idle(lambda: self._ensure_confirm_focus(entry))
        # Token-match state is a pill: calm while waiting, green when it
        # matches, so the gate's answer scans at a glance.
        pill = _Box(
            zone, radius=PILL, fill=SURFACE_ALT, outline=BORDER, ow=1,
            padx=12, pady=6,
        )
        pill.pack(anchor="w", pady=(12, 0))
        self._match_pill = pill
        self._match_icon = tk.Canvas(
            pill.inner, width=22, height=22, highlightthickness=0, bg=SURFACE_ALT
        )
        self._match_icon.pack(side=tk.LEFT)
        self._match_label = tk.Label(
            pill.inner,
            text="",
            font=self.font_s_bold,
            fg=MUTED,
            bg=SURFACE_ALT,
            anchor="w",
        )
        self._match_label.pack(side=tk.LEFT, padx=(8, 0))
        self._paint_match()
        row = self._footer_shell(C.HINT_CONFIRM)
        self._back_btn(row)
        self._primary_btn(row, C.primary_action(Screen.CONFIRM), self.w.continue_confirm, enabled=self.w.token_ok)

    def _paint_match(self) -> None:
        if self._match_icon is None or self._match_label is None:
            return
        cv = self._match_icon
        cv.delete("all")
        if self.w.token_ok:
            if self._match_pill is not None:
                self._match_pill.set_style(fill=OK_TINT, outline=OK)
            cv.configure(bg=OK_TINT)
            cv.create_oval(1, 1, 21, 21, fill=OK, outline="")
            cv.create_line(
                [6, 11.5, 9.5, 15, 16, 7.5],
                fill="#FFFFFF", width=3, capstyle="round", joinstyle="round",
            )
            self._match_label.configure(text=C.CONFIRM_MATCH_OK, fg=OK, bg=OK_TINT)
        else:
            if self._match_pill is not None:
                self._match_pill.set_style(fill=SURFACE_ALT, outline=BORDER)
            cv.configure(bg=SURFACE_ALT)
            cv.create_oval(2, 2, 20, 20, outline=BORDER_STRONG, width=2)
            self._match_label.configure(text=C.CONFIRM_MATCH_WAIT, fg=MUTED, bg=SURFACE_ALT)

    def _ensure_confirm_focus(self, entry: tk.Entry, retries: int = 20) -> None:
        """Recover Entry focus while X11 finishes mapping the no-WM window."""
        try:
            if self.w.screen != Screen.CONFIRM:
                return
            if self.root.focus_get() is not entry:
                entry.focus_force()
            focused = self.root.focus_get() is entry
        except tk.TclError:
            focused = False
        if focused:
            emit_serial_marker("BEAMO_WIPE_CONFIRM_FOCUSED")
            return
        if retries > 0:
            try:
                entry.after(50, lambda: self._ensure_confirm_focus(entry, retries - 1))
                return
            except tk.TclError:
                pass
        emit_serial_marker("BEAMO_WIPE_CONFIRM_UNFOCUSED")

    def _confirm_var_written(self, *_a) -> None:
        if self.w.screen != Screen.CONFIRM:
            return
        self.w.set_confirm_input(self._confirm_var.get())
        self._set_primary_enabled(self.w.token_ok)
        self._paint_match()
        if self.w.token_ok:
            emit_serial_marker("BEAMO_WIPE_CONFIRM_MATCHED")

    def _method_card_wrap(self) -> int:
        """Lead/limits share the title column with the radio and key chip."""
        return max(200, self.lay.wrap - 110)

    def _method_card(self, parent: tk.Widget, method: MethodId) -> None:
        card_copy = C.METHOD_CARDS[method]
        title = str(card_copy["title"])
        blurb = str(card_copy["blurb"])
        pace = str(card_copy["pace"])
        mark = str(card_copy["mark"])
        extra = str(card_copy["extra"])
        lead = str(card_copy["lead"])
        limits_note = str(card_copy["limits"])
        checks = bool(card_copy["checks"])
        key = str(card_copy["key"])
        selected = self.w.method == method
        fill = PRIMARY_TINT if selected else SURFACE
        outline = PRIMARY if selected else BORDER
        card = _Box(
            parent, radius=RADIUS, fill=fill, outline=outline, ow=2 if selected else 1,
            padx=18, pady=8, halo=False,
        )
        card.pack(fill=tk.X, pady=(0, 6), padx=4)
        inner = card.inner
        top = tk.Frame(inner, bg=fill)
        top.pack(fill=tk.X)
        icon = _icon_radio(top, selected, 22)
        icon.configure(bg=fill)
        icon.pack(side=tk.LEFT, anchor="n", pady=1)
        self._kbd(top, key).pack(side=tk.RIGHT, anchor="n", padx=(8, 0))
        # Blurb and pace live in the title column so the card's text shares
        # one left edge instead of stair-stepping under the radio.
        text_col = tk.Frame(top, bg=fill)
        text_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 8))
        title_row = tk.Frame(text_col, bg=fill)
        title_row.pack(fill=tk.X)
        tk.Label(
            title_row, text=title, font=self.font_bold, fg=INK, bg=fill, anchor="w"
        ).pack(side=tk.LEFT)
        if method == DEFAULT_METHOD:
            self._chip(title_row, C.RECOMMENDED_TAG, fg=OK, bg=OK_TINT).pack(
                side=tk.LEFT, padx=(10, 0)
            )
        elif mark:
            fg, bg_chip = (WARN, WARN_BG) if not checks else (MUTED, SURFACE_ALT)
            self._chip(title_row, mark, fg=fg, bg=bg_chip).pack(
                side=tk.LEFT, padx=(10, 0)
            )
        self._wrapping_label(text_col, lead, font=self.font_b, bg=fill)
        tk.Label(
            text_col,
            text=blurb,
            font=self.font_s,
            fg=MUTED,
            bg=fill,
            wraplength=self._method_card_wrap(),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(2, 0))
        pace_row = tk.Frame(text_col, bg=fill)
        pace_row.pack(fill=tk.X, pady=(4, 0))
        if checks:
            clock = _icon_clock(pace_row, 16)
            clock.configure(bg=fill)
            clock.pack(side=tk.LEFT, anchor="n", pady=1)
        tk.Label(
            pace_row,
            text=pace,
            font=self.font_s,
            fg=MUTED,
            bg=fill,
            wraplength=max(200, self.lay.wrap - 110),
            justify=tk.LEFT,
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(7 if checks else 0, 0))
        if extra:
            tk.Label(
                text_col,
                text=extra,
                font=self.font_s,
                fg=MUTED,
                bg=fill,
                wraplength=self._method_card_wrap(),
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, pady=(4, 0))
        if limits_note:
            self._wrapping_label(
                text_col, limits_note, font=self.font_s, bg=fill, fg=MUTED
            )

        def _click(_e, m=method):
            self._choose_method(m)
            return "break"

        self._bind_tree(card, _click)
        card.configure(cursor="hand2")
        inner.configure(cursor="hand2")
        if not selected:
            self._bind_hover(
                card,
                partial(card.set_style, fill=SURFACE_ALT),
                partial(card.set_style, fill=SURFACE),
            )

    def _method(self) -> None:
        col = self._column(self._body, fill_height=True)
        # Identity is informational only; method changes keep the bound target.
        # The shared scrolling body accommodates long identities and small screens.
        self._title_block(col, C.TITLE_METHOD, C.METHOD_LEAD, compact=True)
        if self.w.selected:
            self._disk_summary(col, self.w.selected).pack(fill=tk.X)
            self._more_link(col)
        notice = self.w.storage_notice
        if notice:
            self._panel(col, kind="limits", text=notice, compact=True).pack(
                fill=tk.X, pady=(8, 0)
            )
        _Button(
            col, text=limits.BUTTON, command=self._nav(self.w.open_limits),
            font=self.font_s_bold, variant="ghost", compact=True,
        ).pack(anchor="w", pady=(4, 4))
        zone = self._center_zone(col)
        for method in (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO):
            self._method_card(zone, method)
        row = self._footer_shell(C.HINT_METHOD)
        self._back_btn(row)
        self._primary_btn(row, C.primary_action(Screen.METHOD), self.w.continue_method)
        if self._primary is not None:
            self._primary.focus_set()

    def _shutdown_confirm(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, self.w.exit_confirmation_title, self.w.exit_confirmation_loss)
        if self.w.report_recovery_warning:
            self._p(col, self.w.report_recovery_warning, font=self.font_s).pack(
                fill=tk.X
            )
        self._p(col, C.MEDIA_STEPS_TITLE, font=self.font_s_bold).pack(
            fill=tk.X, pady=(12, 4)
        )
        self._p(col, self.w.exit_media_steps, font=self.font_s).pack(fill=tk.X)
        row = self._footer_shell(C.SHUTDOWN_HINT)
        generation = self.w.shutdown_generation
        self._secondary_btn(
            row,
            self.w.exit_confirmation_discard,
            lambda: self.w.confirm_shutdown_without_saving(generation),
        )
        self._primary_btn(row, C.SHUTDOWN_KEEP, self.w.keep_report_session)
        if self._primary is not None:
            self._primary.focus_set()

    def _refresh_confirm(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_REFRESH, C.REFRESH_LEAD)
        row = self._footer_shell(C.HINT_REFRESH)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_REFRESH, self._click_refresh)
        if self._primary is not None:
            self._primary.focus_set()

    def _report_help(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.REPORT_HELP_TITLE, C.REPORT_MEDIA_NOTE, compact=True)
        frame = tk.Frame(col, bg=BG)
        frame.pack(fill=tk.BOTH, expand=True)
        text = self._reader(frame, height=10, padx=14, pady=12)
        scrollbar = _Scrollbar(frame, text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text.insert("1.0", C.REPORT_HELP_TEXT + ("\n\n" + self.w.report_recovery_warning if self.w.report_recovery_warning else ""))
        text.configure(state=tk.DISABLED)
        choice = tk.BooleanVar(master=self.root, value=self.w.report_wanted)
        wrap = max(200, self.lay.wrap - 40)

        def set_preference():
            previous = self.w.report_recovery_warning
            self.w.set_report_wanted(choice.get())
            if previous != self.w.report_recovery_warning:
                text.configure(state=tk.NORMAL)
                text.delete("1.0", tk.END)
                text.insert("1.0", C.REPORT_HELP_TEXT + ("\n\n" + self.w.report_recovery_warning if self.w.report_recovery_warning else ""))
                text.configure(state=tk.DISABLED)
                text.see(tk.END)

        _CheckRow(
            col, text=C.REPORT_WANTED, variable=choice,
            command=set_preference, font=self.font_s, wraplength=wrap,
        ).pack(anchor="w", fill=tk.X, pady=8)
        share = tk.BooleanVar(master=self.root, value=self.w.report_share_redacted)

        def set_share():
            self.w.set_report_share_redacted(share.get())

        _CheckRow(
            col, text=C.REPORT_SHARE_REDACTED, variable=share,
            command=set_share, font=self.font_s, wraplength=wrap,
        ).pack(anchor="w", fill=tk.X, pady=(0, 8))
        self._back_btn(self._footer_shell(C.HINT_READ_RETURN))
        text.focus_set()

    def _disk_help(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.DISK_HELP_TITLE, C.HINT_READ_KEYS, compact=True)
        frame = tk.Frame(col, bg=BG)
        frame.pack(fill=tk.BOTH, expand=True)
        text = self._reader(frame, height=10, padx=14, pady=12)
        scrollbar = _Scrollbar(frame, text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text.insert("1.0", C.DISK_HELP_TEXT)
        text.configure(state=tk.DISABLED)
        text.focus_set()
        row = self._footer_shell(C.HINT_ESC_NO_SELECTION)
        self._back_btn(row)
        self._secondary_btn(row, C.DISK_HELP_STOP, self.w.shutdown)

    def _limits(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, limits.TITLE, C.HINT_READ_KEYS, compact=True)
        frame = tk.Frame(col, bg=BG)
        frame.pack(fill=tk.BOTH, expand=True)
        text = self._reader(frame, height=10, padx=14, pady=12)
        scrollbar = _Scrollbar(frame, text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text.insert("1.0", limits.full_text())
        text.configure(state=tk.DISABLED)
        text.focus_set()
        row = self._footer_shell(C.HINT_ESC_METHOD)
        self._back_btn(row)

    def _choose_method(self, method: MethodId) -> None:
        self.w.set_method(method)
        self._draw()

    def _last(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_LAST, C.LAST_LEAD)
        review = tk.Frame(col, bg=BG)
        review.pack(fill=tk.X, pady=(8, 0))
        zone = tk.Frame(review, bg=BG)
        details = tk.Frame(review, bg=BG)
        if self.lay.stack_review:
            details.pack(fill=tk.X, anchor="n")
            zone.pack(fill=tk.X, pady=(8, 0), anchor="n")
        else:
            zone.pack(side=tk.RIGHT, padx=(24, 0), anchor="n")
            details.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor="n")
        if self.w.selected is not None:
            self._disk_summary(details, self.w.selected).pack(fill=tk.X)
            self._p(
                details,
                self.w.prepare_text(),
                font=self.font_s,
                bg=BG,
                wraplength=max(200, self.lay.wrap - 120),
            ).pack(fill=tk.X, pady=(8, 0))
        self._wrapping_label(
            details, self.w.operation_summary, font=self.font_bold, bg=BG
        ).pack_configure(pady=(12, 0))
        self._wrapping_label(details, f"{C.SEVERITY_WARNING}: {self.w.erase_label()}",
                             font=self.font_bold, bg=BG, fg=DANGER).pack_configure(pady=(16, 8))
        self._wrapping_label(details, self.w.method_summary, font=self.font_s, bg=BG)
        if self.w.error:
            sections = recovery_for_wizard_error(self.w.error)
            if sections:
                self._recovery_block(col, sections)
            else:
                self._panel(col, kind="danger", text=self.w.error).pack(fill=tk.X, pady=(12, 0))
            self._support_identity_block(col)
        self._power_notice(details)
        ring_px = self.lay.ring
        self._ring_px = ring_px
        ring = tk.Canvas(
            zone, width=ring_px, height=ring_px, bg=BG, highlightthickness=0
        )
        ring.pack()
        self._countdown_ring = ring
        self._countdown_num = tk.Label(
            ring, text="", font=self.font_bold, fg=INK, bg=BG, anchor="center"
        )
        ring.create_window(ring_px / 2, ring_px / 2, window=self._countdown_num)
        self._countdown_label = tk.Label(
            zone, text="", font=self.font_b, fg=MUTED, bg=BG, anchor="center",
            justify=tk.CENTER, wraplength=max(120, ring_px + 40),
        )
        self._countdown_label.pack(fill=tk.X, pady=(12, 0))
        row = self._footer_shell(C.HINT_LAST_CHANCE_TK)
        back = self._back_btn(row)
        self._primary_btn(
            row,
            C.BTN_ERASE,
            self._click_erase,
            enabled=self.w.erase_enabled,
            danger=True,
        )
        # Safe default: focus Back, never the Erase button.
        back.focus_set()
        self._refresh_last_chance()

    def _refresh_last_chance(self) -> None:
        if self._countdown_ring is None or self._countdown_label is None:
            return
        left = self.w.countdown_display
        ring = self._countdown_ring
        size = getattr(self, "_ring_px", RING_SIZE)
        edge0 = RING_PAD
        edge1 = size - RING_PAD
        center = size / 2.0
        # The ring stroke is centered on the oval/arc path, so the tip cap
        # rides the path radius, not the band's inner edge.
        radius = (edge1 - edge0) / 2.0
        ring.delete("arc")
        ring.create_oval(edge0, edge0, edge1, edge1, outline=TRACK, width=RING_W, tags="arc")
        if left > 0:
            frac = min(1.0, max(0.0, self.w.countdown_left / COUNTDOWN_S))
            extent = -359.99 * frac
            ring.create_arc(
                edge0, edge0, edge1, edge1, start=90, extent=extent,
                style=tk.ARC, outline=PRIMARY, width=RING_W, tags="arc",
            )
            # Rounded cap: Tk arcs have square ends, so dot the moving tip.
            tip = math.radians(90 + extent)
            tx = center + radius * math.cos(tip)
            ty = center - radius * math.sin(tip)
            ring.create_oval(tx - 2, ty - 2, tx + 2, ty + 2, fill=PRIMARY, outline="", tags="arc")
            if self._countdown_num is not None:
                self._countdown_num.configure(text=str(left), fg=INK)
            self._countdown_label.configure(text=C.COUNTDOWN_CAPTION, fg=MUTED)
        else:
            ring.create_oval(edge0, edge0, edge1, edge1, outline=PRIMARY, width=RING_W, tags="arc")
            if self._countdown_num is not None:
                self._countdown_num.configure(text="0", fg=PRIMARY)
            self._countdown_label.configure(text=C.COUNTDOWN_READY, fg=INK)
        self._set_primary_enabled(self.w.erase_enabled)

    def _working(self) -> None:
        self._shown_report_revision = self.w.report_view.revision
        col = self._column(self._body, fill_height=True)
        disk = self.w.operation_disk
        if self.w.stop_confirmation is not None:
            confirmation = self.w.stop_confirmation
            self._title_block(col, C.STOP_TITLE)
            self._panel(col, kind="warn", text=C.STOP_LEAD).pack(fill=tk.X, pady=(12, 0))
            if disk is not None:
                self._disk_summary(col, disk).pack(fill=tk.X, pady=(12, 0))
            elif self.w.operation_identity_text:
                self._p(col, self.w.operation_identity_text, font=self.font_b, fg=MUTED).pack(fill=tk.X, pady=(12, 0))
            self._p(col, self.w.operation_method_text, font=self.font_s, fg=MUTED).pack(fill=tk.X, pady=(12, 0))
            row = self._footer_shell(C.POWER_KEEP_CONNECTED)
            keep = self._secondary_btn(row, C.STOP_KEEP, self.w.keep_erasing)
            self._primary_btn(row, C.STOP_CONFIRM, lambda: self.w.confirm_stop(confirmation), danger=True)
            keep.focus_set()
            return
        self._title_block(col, C.VIEWS["stop_unconfirmed"].message
                          if self.w.error == C.VIEWS["stop_unconfirmed"].announcement
                          else C.TITLE_WORKING)
        if self.w.error:
            sections = recovery_for_wizard_error(self.w.error)
            if sections:
                self._recovery_block(col, sections)
            else:
                self._panel(col, kind="danger", text=self.w.error).pack(fill=tk.X, pady=(0, 12))
            if error_needs_support(self.w.error):
                self._support_block(col)
        if disk is not None:
            self._disk_summary(col, disk).pack(fill=tk.X)
            self._more_link(col)
        elif self.w.operation_identity_text:
            self._p(col, self.w.operation_identity_text, font=self.font_b, fg=MUTED).pack(fill=tk.X)
        container = self._center_zone(col)
        progress_card = _Box(container, radius=RADIUS, fill=SURFACE_ALT,
                             outline=BORDER, ow=1, padx=20, pady=16)
        progress_card.pack(fill=tk.X)
        zone = progress_card.inner
        tk.Label(zone, text=C.ERASE_PROGRESS_LABEL, font=self.font_s_bold,
                 fg=MUTED, bg=SURFACE_ALT, anchor="w").pack(fill=tk.X, pady=(0, 8))
        self._progress_pct = tk.Label(
            zone, text="", font=self.font_stat, fg=INK, bg=SURFACE_ALT, anchor="w"
        )
        self._progress_pct.pack(fill=tk.X, pady=(0, 12))
        bar = tk.Canvas(zone, height=BAR_H, bg=SURFACE_ALT, highlightthickness=0)
        bar.pack(fill=tk.X)
        bar.bind("<Configure>", lambda _e: self._refresh_working())
        self._progress_bar = bar
        self._progress_label = self._p(
            zone, C.WORKING_PULSE, fg=MUTED, font=self.font_b, bg=SURFACE_ALT
        )
        self._progress_label.pack(fill=tk.X, pady=(14, 0))
        self._power_notice(zone, reminder=False, bg=SURFACE_ALT)
        self._p(zone, self.w.method_summary, font=self.font_s,
                fg=MUTED, bg=SURFACE_ALT).pack(fill=tk.X, pady=(10, 0))
        if self.w.evidence_warning:
            self._p(col, f"{C.SEVERITY_WARNING}: {self.w.evidence_warning}", font=self.font_s_bold).pack(fill=tk.X, pady=(8, 0))
        if self.w.sound_message:
            self._p(col, self.w.sound_message, font=self.font_s, fg=MUTED).pack(
                fill=tk.X, pady=(8, 0)
            )
        # Stopping is always reachable, with consent before signalling.
        row = self._footer_shell(C.HINT_WORKING)
        self._secondary_btn(row, C.STOP_ASK, self._click_cancel)
        self._secondary_btn(row, self.w.sound_toggle_text, self.w.toggle_sounds)
        self._secondary_btn(row, C.SOUND_HEAR, self.w.hear_both_sounds)
        self._refresh_working()

    def _refresh_working(self) -> None:
        if self._progress_label is None:
            return
        view = self.w.progress_view
        pulse = view.timing_text
        pct = view.percent
        if view.percent_is_old and pct is not None:
            shown = f"{format_progress_percent(pct)} (old)"
        elif pct is None:
            shown = ""
        else:
            shown = format_progress_percent(pct)
        if self._progress_pct is not None and self._progress_pct.cget("text") != shown:
            self._progress_pct.configure(
                text=shown, fg=MUTED if view.percent_is_old else INK
            )
        if self._progress_label.cget("text") != pulse:
            self._progress_label.configure(text=pulse)
        if view.animate:
            # First number has not arrived during the known startup quiet
            # window. Slide only then; silence must not look like live data.
            self._indet = (self._indet + 0.045) % 2.0
            pos = self._indet if self._indet <= 1.0 else 2.0 - self._indet
            self._paint_bar(None, pos)
        elif pct is None:
            self._paint_bar(0.0)
        else:
            self._paint_bar(max(0.02, pct / 100.0))

    def _paint_bar(self, frac: Optional[float], indet_pos: float = 0.0) -> None:
        bar = self._progress_bar
        if bar is None:
            return
        bar.delete("all")
        width = max(bar.winfo_width(), 1)
        height = max(bar.winfo_height(), BAR_H)
        radius = max(2, height // 2)
        _round_rect(bar, 0, 0, width, height, radius, fill=TRACK, outline="")
        if frac is None:
            seg = width * 0.30
            x1 = seg + (width - seg) * indet_pos
            x0 = x1 - seg
            _round_rect(
                bar, max(0, x0), 0, min(width, x1), height, radius,
                fill=PRIMARY, outline="",
            )
            return
        fill_w = width * min(1.0, frac)
        if fill_w > 1:
            _round_rect(
                bar, 0, 0, max(fill_w, height), height, radius,
                fill=PRIMARY, outline="",
            )

    def _done(self, report: ReportView) -> None:
        col = self._column(self._body, fill_height=True)
        self.w.maybe_play_outcome_sound()
        result = self.w.result_view
        # Erase status heading stays independent of report chrome.
        # Cancelled copy remains in result.message ("Stopped by you").
        # The specific outcome is the main heading; the badge carries color.
        title = result.message

        badge_size = 64 if self.lay.short else 72
        icon = (_icon_status(col, True, badge_size) if result.icon == "check"
                else _icon_badge(col, result.icon, badge_size))
        icon.configure(bg=BG)
        icon.pack(pady=(8 if self.lay.short else 12, 0))
        heading = self._h(col, title)
        heading.configure(anchor="center", justify=tk.CENTER)
        heading.pack(fill=tk.X, pady=(8, 4) if self.lay.short else (12, 4))
        self._p(col, self.w.elapsed_text, fg=MUTED, font=self.font_s,
                justify=tk.CENTER, anchor="center").pack(fill=tk.X, pady=(4, 0))
        # Keep the selected-disk summary in the first viewport so Show more
        # stays reachable on short windows; report status follows, still
        # independent of the erase badge.
        if self.w.selected is not None:
            self._disk_summary(col, self.w.selected).pack(
                fill=tk.X, pady=(8 if self.lay.short else 12, 0)
            )
            self._more_link(col)
        if (
            self.w.done_support_needed
            or self.w.evidence_support_needed
            or (report.status == "error" and next_step_needs_support(report.message))
        ):
            self._support_block(col)
        self._support_identity_block(col)
        if may_have_erased(result.code):
            self._p(col, C.POST_ERASE_BOOT, font=self.font_s, fg=MUTED).pack(
                fill=tk.X, pady=(8, 0)
            )
        self._p(col, C.REPORT_STATUS_TITLE, font=self.font_s_bold).pack(
            fill=tk.X, pady=(12, 4)
        )
        detail = (C.REPORT_PREVIEW if self.w.preview else
                  self.w.evidence_warning if report.evidence_error else
                  C.report_aftercare(can_save=report.can_save, status=report.status, message=report.message))
        self._panel(
            col, kind="info" if self.w.preview else report.tone,
            text=C.REPORT_PREVIEW if self.w.preview else report.headline,
            extra=C.REPORT_STATUS_NOTICE + ("" if self.w.preview else " " + detail),
            compact=True,
        ).pack(fill=tk.X)
        self._p(col, self.w.method_summary, font=self.font_s).pack(fill=tk.X, pady=(8, 0))
        sections = recovery_for_view(result)
        if sections:
            self._recovery_block(
                col, sections, omit_duplicate_happened=result.message
            )
        else:
            self._p(col, result.next_step, font=self.font_s).pack(fill=tk.X)
        for alert in self.w.check_alerts:
            self._panel(col, kind="warn", text=alert).pack(fill=tk.X, pady=(8, 0))
        if self.w.sound_message:
            self._p(col, self.w.sound_message, font=self.font_s, fg=MUTED).pack(
                fill=tk.X, pady=(8, 0)
            )
        row = self._footer_shell(C.HINT_DEFAULT if self.w.preview else C.HINT_DONE)
        if self.w.preview:
            self._secondary_btn(row, C.BTN_CLOSE_PREVIEW, self._click_shutdown)
            self._secondary_btn(row, self.w.sound_toggle_text, self.w.toggle_sounds)
            self._secondary_btn(row, C.SOUND_HEAR_AGAIN, self.w.hear_outcome_sound)
            self._primary_btn(row, C.BTN_RUN_AGAIN, self.w.reset_for_preview)
        else:
            if report.evidence_error:
                self._secondary_btn(row, C.RETRY_SAVE, self._click_retry_evidence,
                                    enabled=report.can_retry_evidence)
            self._secondary_btn(
                row,
                C.BTN_SAVE_REPORT,
                self._click_save_report,
                enabled=report.can_save,
            )
            self._secondary_btn(row, self.w.sound_toggle_text, self.w.toggle_sounds)
            self._secondary_btn(row, C.SOUND_HEAR_AGAIN, self.w.hear_outcome_sound)
            another = _Button(
                self._footer_left_parent(
                    row, self.font_s_bold.measure(C.BTN_ERASE_ANOTHER) + 2 * 12 + 6
                ),
                text=C.BTN_ERASE_ANOTHER,
                command=self._nav(self.w.erase_another_disk),
                font=self.font_s_bold, variant="ghost", compact=True,
                enabled=self.w.can_erase_another,
            )
            another.pack(side=tk.LEFT)
            self._primary_btn(
                row,
                C.BTN_SHUTDOWN,
                self._click_shutdown,
                enabled=not report.exporting and not report.saving_evidence,
            )
        if self._primary is not None:
            self._primary.focus_set()

    def _advanced(self) -> None:
        col = self._column(self._body, fill_height=True)
        # Compact header: this is the second-tightest screen after method,
        # and it must keep the footer whole on 800x600 and 1280x720.
        self._title_block(col, C.TITLE_ADVANCED, C.ADVANCED_LEAD, compact=True)
        from beamo_wipe.methods import METHODS

        zone = self._center_zone(col)
        card = _Box(
            zone, radius=RADIUS, fill=SURFACE, outline=BORDER, ow=1,
            padx=20, pady=12, shadow=False,
        )
        card.pack(fill=tk.X)
        for i, spec in enumerate(METHODS.values()):
            if i:
                tk.Frame(card.inner, bg=BORDER, height=1).pack(fill=tk.X)
            tk.Label(
                card.inner,
                text=f"{spec.method_id.value}: nwipe --method={spec.nwipe_method}  ({spec.docs_name})",
                font=self.font_mono_sm,
                fg=INK,
                bg=SURFACE,
                anchor="w",
                # Long method names must wrap inside the card, never clip.
                wraplength=max(200, self.lay.wrap - 40),
                justify=tk.LEFT,
            ).pack(fill=tk.X, pady=(7, 7))
        log = self.w._wipe_request.logfile if self.w._wipe_request else C.NO_WIPE_YET
        log_row = tk.Frame(zone, bg=BG)
        log_row.pack(fill=tk.X, pady=(14, 4))
        tk.Label(
            log_row, text=C.ADVANCED_LOG_LABEL, font=self.font_s,
            fg=MUTED, bg=BG, anchor="w",
        ).pack(side=tk.LEFT)
        tk.Label(
            log_row, text=log, font=self.font_mono_sm, fg=INK, bg=BG, anchor="w"
        ).pack(side=tk.LEFT)
        self._p(zone, C.ADVANCED_LOG_NOTE, fg=MUTED, font=self.font_s).pack(fill=tk.X)
        row = self._footer_shell(C.HINT_ADVANCED)
        self._back_btn(row)
        self._primary_btn(row, C.primary_action(Screen.ADVANCED), self.w.close_advanced)
        if self._primary is not None:
            self._primary.focus_set()

    # -- keyboard ------------------------------------------------------------

    def _on_escape(self, _event=None) -> str:
        if self.w.screen == Screen.SPLASH:
            self.w.skip_splash()
            self._draw()
            return "break"
        if self.w.screen == Screen.WORKING:
            if self.w.stop_confirmation is not None:
                self.w.keep_erasing()
            else:
                self.w.request_stop()
            self._draw()
            return "break"
        if self.w.screen not in (Screen.WHAT, Screen.DONE):
            self.w.back()
            self._draw()
        return "break"

    @staticmethod
    def _key_event_time(event) -> Optional[int]:
        value = getattr(event, "time", None)
        return value if isinstance(value, int) and value > 0 else None

    def _on_return_release(self, _event=None) -> str:
        # X11 autorepeat is a queued KeyRelease/KeyPress pair. Defer clearing
        # until idle for queued pairs. _on_return also recognizes split pairs
        # by server timestamp if this callback has already run.
        if self._return_release_after is not None:
            try:
                self.root.after_cancel(self._return_release_after)
            except tk.TclError:
                pass
        self._return_release_time = self._key_event_time(_event)
        self._return_release_after = self.root.after_idle(self._release_return)
        return "break"

    def _release_return(self) -> None:
        self._return_release_after = None
        self._return_held = False
        self.w.arm_done_keyboard()
        emit_serial_marker("BEAMO_WIPE_KEY_RETURN_RELEASED")

    def _claim_space_press(self, event=None) -> bool:
        """Claim a new physical Space press; suppress X11 repeat pairs."""
        if self._space_release_after is not None:
            try:
                self.root.after_cancel(self._space_release_after)
            except tk.TclError:
                pass
            self._space_release_after = None
        repeat = (self._space_release_time is not None
                  and self._space_release_time == self._key_event_time(event))
        if self._space_held or repeat:
            self._space_held = True
            return False
        self._space_held = True
        self._space_release_time = None
        return True

    def _on_space_release(self, _event=None) -> str:
        # Defer queued X11 repeat pairs; _claim_space_press also rejects a
        # matching server timestamp when the pair spans idle callbacks.
        if self._space_release_after is not None:
            try:
                self.root.after_cancel(self._space_release_after)
            except tk.TclError:
                pass
        self._space_release_time = self._key_event_time(_event)
        self._space_release_after = self.root.after_idle(self._release_space)
        return "break"

    def _release_space(self) -> None:
        self._space_release_after = None
        self._space_held = False
        self.w.arm_done_keyboard()
        emit_serial_marker("BEAMO_WIPE_KEY_SPACE_RELEASED")

    def _click_erase(self) -> None:
        self.w.begin_erase()

    def _click_cancel(self) -> None:
        """Request confirmation; never stop on the initiating click."""
        self.w.request_stop()
        self._draw()

    def _click_retry_evidence(self) -> None:
        self.w.begin_evidence_retry()

    def _click_save_report(self) -> None:
        if self.w.begin_report_export():
            self._draw()

    def _click_shutdown(self) -> None:
        """Button Space/click on Shut down. Ignore until the arriving key is up."""
        if self._return_held or (self._space_held and not self._space_action_active):
            return
        if self.w.screen in (Screen.DONE, Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            if not self.w._done_keyboard_armed:
                return
        self.w.shutdown()

    def _on_return(self, _event=None) -> str:
        # X11 auto-repeat is extra KeyPress events with no KeyRelease. The
        # same physical Enter would skip Confirm → Method → Last chance.
        if self._return_release_after is not None:
            try:
                self.root.after_cancel(self._return_release_after)
            except tk.TclError:
                pass
            self._return_release_after = None
        # X11 repeat Release/Press events have the same server timestamp.
        # They can arrive in separate event-loop batches: after_idle alone
        # then clears the hold too early. Retain that timestamp across idle
        # so the matching repeat can never advance another safety screen.
        repeat = (self._return_release_time is not None
                  and self._return_release_time == self._key_event_time(_event))
        if self._return_held or repeat:
            self._return_held = True
            return "break"
        self._return_held = True
        self._return_release_time = None
        screen = self.w.screen
        before = screen
        focused = self.root.focus_get()
        acted = False
        command_drew = False
        if screen == Screen.SHUTDOWN_CONFIRM:
            # Enter is the safe default: keep the session. Discard requires
            # its own focused Space/click confirmation, not this Return.
            self.w.keep_report_session()
            acted = True
        elif isinstance(focused, _Button) and focused._enabled:
            # Enter activates the focused control. Last-chance Erase still
            # requires the countdown; Done/empty/blocked primary still uses
            # the key-release arming gate instead of the click handler.
            if focused is self._primary and screen == Screen.LAST_CHANCE and not self.w.erase_enabled:
                acted = True
            elif focused is self._primary and screen in (
                Screen.DONE, Screen.PICK_EMPTY, Screen.PICK_BLOCKED,
            ):
                self.w.accept_done_keyboard()
                acted = True
            else:
                focused._command()
                acted = True
                # _nav wrappers and Show more already rebuild. A second
                # _draw() would steal focus from Show less back to Continue.
                command_drew = True
        if not acted:
            if screen == Screen.SHUTDOWN_CONFIRM:
                self.w.keep_report_session()
            elif screen == Screen.SPLASH:
                self.w.skip_splash()
            elif screen == Screen.KEYBOARD:
                self.w.accept_keyboard()
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
            elif screen == Screen.LAST_CHANCE:
                pass
            elif screen == Screen.DONE:
                self.w.accept_done_keyboard()
            elif screen == Screen.ADVANCED:
                self.w.close_advanced()
            elif screen == Screen.REPORT_HELP:
                self.w.close_report_help()
            elif screen == Screen.LIMITS:
                self.w.close_limits()
            elif screen in (Screen.PICK_BLOCKED, Screen.PICK_EMPTY):
                self.w.accept_done_keyboard()
        if self.w.wants_shutdown or self.w.wants_new_session:
            self._teardown()
            return "break"
        # Fixed, identifier-free pre-render state for the isolated QEMU gate.
        # If rendering raises, this still distinguishes the accepted state
        # transition from a missing key event or a fail-closed pick result.
        emit_serial_marker(f"BEAMO_WIPE_RETURN_RESULT_{self.w.screen.name}")
        if not command_drew and (self.w.screen != before or screen != Screen.CONFIRM):
            self._draw()
        return "break"

    def _start_refresh_scan(self, on_done) -> Optional[int]:
        """Begin a scan, paint checking now, run I/O on a worker thread.

        Returns the scan sequence, or None when refresh is not allowed.
        The checking state draws synchronously so the owner sees feedback
        before discovery I/O starts; ``on_done(applied)`` runs on the UI
        thread when this scan's result arrives. A repeat attempt while a
        scan is in flight is refused, so only one scan ever runs.
        """
        seq = self.w.begin_refresh()
        if seq is None:
            return None
        self._draw()
        worker = threading.Thread(
            target=self._refresh_worker, args=(seq,),
            daemon=True, name=f"beamo-refresh-{seq}",
        )
        with self._refresh_lock:
            self._refresh_threads[seq] = worker
        worker.start()
        try:
            self.root.after(50, lambda: self._poll_refresh(seq, on_done))
        except tk.TclError:
            pass
        return seq

    def _refresh_worker(self, seq: int) -> None:
        # Worker discipline: discovery I/O only. No Tk calls, no wizard
        # state — the outcome slot is the only shared touchpoint, and the
        # UI thread owns everything after the poll picks it up.
        try:
            outcome = self.w._run_rediscovery()
        except BaseException as exc:
            outcome = exc
        with self._refresh_lock:
            self._refresh_results[seq] = outcome

    def _poll_refresh(self, seq: int, on_done) -> None:
        if self._ui_dead:
            return
        _missing = object()
        with self._refresh_lock:
            outcome = self._refresh_results.pop(seq, _missing)
        if outcome is _missing:
            try:
                self.root.after(50, lambda: self._poll_refresh(seq, on_done))
            except tk.TclError:
                pass
            return
        applied = False
        if not self._ui_dead:
            applied = self.w.finish_refresh(seq, outcome)
        if self._ui_dead:
            return
        try:
            on_done(applied)
        except tk.TclError:
            pass

    def _redraw_after_refresh(self, applied: bool) -> None:
        # A dropped (stale or post-teardown) result draws nothing.
        if applied and not self._ui_dead:
            self._draw()

    def _open_reader_after_refresh(self, applied: bool) -> None:
        # Same contract as the old synchronous F8: an applied scan — success
        # or fail-closed error — hands off to the screen-reader view, which
        # renders whatever the fresh inventory holds.
        if self._ui_dead or not applied:
            return
        self._accessible_requested = True
        self._teardown()

    def _click_refresh(self) -> None:
        if self.w.screen != Screen.REFRESH_CONFIRM:
            if not self.w.open_refresh_confirm():
                return
            self._draw()
            return
        if self._start_refresh_scan(self._redraw_after_refresh) is None:
            return
        self._show_more = False
        self._pick_scroll = 0.0

    def _on_f5_release(self, _event=None) -> str:
        self._f5_held = False
        return "break"

    def _on_key(self, event) -> Optional[str]:
        if event.keysym == "F8" and sys.platform.startswith("linux") and self.w.can_refresh:
            self._click_accessible()
            return "break"
        if event.keysym == "F5":
            if self._f5_held:
                return "break"
            self._f5_held = True
            if self.w.can_refresh:
                self._click_refresh()
            return "break"
        if self._body_canvas is not None and event.keysym in ("Prior", "Next"):
            self._body_canvas.yview_scroll(-1 if event.keysym == "Prior" else 1, "pages")
            return "break"
        if event.keysym in ("Return", "KP_Enter", "Escape", "Tab"):
            return None
        if event.keysym == "space" and not self._claim_space_press(event):
            return "break"
        if self.w.screen == Screen.SPLASH:
            self.w.skip_splash()
            self._draw()
            return "break"
        if self.w.screen == Screen.OWNER and event.keysym == "space":
            self.w.set_owner(not self.w.owner_ok)
            self._owner_var.set(1 if self.w.owner_ok else 0)
            self._draw()
            return "break"
        if any(getattr(self.root.focus_get(), marker, False)
               for marker in ("_beamo_inventory", "_beamo_comparison")):
            return None
        if self.w.screen == Screen.PICK and event.keysym in ("Up", "Down"):
            self._pick_ensure_visible = True
            self.w.move_selection(-1 if event.keysym == "Up" else 1)
            self._draw()
            return "break"
        if self.w.screen == Screen.KEYBOARD:
            focused = self.root.focus_get()
            if isinstance(focused, tk.Entry):
                return None
            keyboard_mapping = {"1": "us", "2": "fr", "3": "de"}
            if event.keysym in keyboard_mapping:
                self.w.set_keyboard_layout(keyboard_mapping[event.keysym])
                self._draw()
                return "break"
        if self.w.screen == Screen.METHOD:
            if event.keysym.lower() == "l":
                self.w.open_limits()
                self._draw()
                return "break"
            # Some X servers/IMEs deliver keysym with an empty char.
            digit = event.char if event.char in ("1", "2", "3") else event.keysym
            if digit in ("1", "2", "3"):
                mapping = {"1": MethodId.EVERYDAY, "2": MethodId.EXTRA, "3": MethodId.QUICK_ZERO}
                self.w.set_method(mapping[digit])
                self._draw()
                return "break"
            if event.keysym in ("Up", "Down"):
                order = (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO)
                idx = order.index(self.w.method) if self.w.method in order else 0
                delta = -1 if event.keysym == "Up" else 1
                nxt = order[(idx + delta) % len(order)]
                self.w.set_method(nxt)
                self._draw()
                return "break"
        return None

    def _close(self) -> None:
        if self.w.screen == Screen.WORKING:
            self.w.request_stop()
            self._draw()
            return
        self.w.shutdown()
        if self.w.wants_shutdown or self.w.wants_new_session:
            self._teardown()
        else:
            self._draw()

    def run(self) -> int:
        self.root.mainloop()
        return 3 if self._fatal_ui else (4 if self._accessible_requested else 0)

    def _click_accessible(self) -> None:
        if not sys.platform.startswith("linux") or not self.w.can_refresh:
            return
        if self._start_refresh_scan(self._open_reader_after_refresh) is None:
            self._draw()


def run_tk(wizard: Wizard, fullscreen: bool = False) -> int:
    ui = TkWizard(wizard, fullscreen=fullscreen)
    return ui.run()


def _ensure_tk_display() -> None:
    """Raise RuntimeError when no graphical display is reachable.

    Constructing a Tk root with no display aborts the whole interpreter
    (Tcl_Panic), which no caller can catch — so app.py could never fall
    back to the keyboard screens. Probe in a child process instead: a
    crash there becomes a catchable error here and startup stays on the
    existing graphical-failure path.
    """
    import subprocess as _subprocess
    from beamo_wipe.safety import session_exec_env

    try:
        probe = _subprocess.run(
            [sys.executable, "-c", "import tkinter as _t; _t.Tk().destroy()"],
            stdin=_subprocess.DEVNULL,
            stdout=_subprocess.DEVNULL,
            stderr=_subprocess.DEVNULL,
            timeout=30,
            check=False,
            shell=False,
            env=session_exec_env(),
        )
    except (OSError, _subprocess.SubprocessError):
        raise RuntimeError("no graphical display for startup stages")
    if probe.returncode != 0:
        raise RuntimeError("no graphical display for startup stages")


def run_tk_startup(build, *, fullscreen: bool = False,
                   stall_after_s: float | None = None) -> tuple:
    """Show startup stages while ``build()`` runs on a worker thread.

    ``build`` receives a worker-safe ``report(stage_key)`` callback and
    returns the built wizard; anything it raises becomes the failure
    outcome. Returns ("wizard", wizard), ("failed", exc), or
    ("abandoned", None) when the owner closes the splash (Escape or window
    close), mirroring the wizard's close-means-stop contract. Raises
    RuntimeError (never aborts) when no display is reachable.
    """
    from beamo_wipe.startup_stages import STALL_AFTER_S, StartupRun

    _ensure_tk_display()
    run = StartupRun(
        build,
        stall_after_s=STALL_AFTER_S if stall_after_s is None else stall_after_s,
    )
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(f"no graphical display for startup stages: {exc}")
    root.title("Beamo Wipe")
    if fullscreen:
        root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        root.attributes("-fullscreen", True)
    else:
        root.geometry("640x440")
    try:
        root.eval("tk::PlaceWindow . center")
    except tk.TclError:
        pass
    root.configure(bg=BG)
    outcome: list = []

    body = tk.Frame(root, bg=BG)
    body.pack(fill=tk.BOTH, expand=True, padx=48, pady=36)
    rows = []
    for _i in range(3):
        status = tk.Label(body, text="", font=("TkDefaultFont", 13, "bold"),
                          fg=FOCUS, bg=BG, anchor="w")
        title = tk.Label(body, text="", font=("TkDefaultFont", 17, "bold"),
                         fg=INK, bg=BG, anchor="w")
        hint = tk.Label(body, text="", font=("TkDefaultFont", 13),
                        fg=MUTED, bg=BG, anchor="w", justify=tk.LEFT,
                        wraplength=540)
        status.pack(fill=tk.X)
        title.pack(fill=tk.X)
        hint.pack(fill=tk.X, pady=(0, 14))
        rows.append((status, title, hint))
    stall = tk.Label(body, text="", font=("TkDefaultFont", 13, "italic"),
                     fg=MUTED, bg=BG, anchor="w", justify=tk.LEFT,
                     wraplength=540)
    stall.pack(fill=tk.X)

    _STATUS_WORDS = {"pending": C.STARTUP_STATE_WAITING, "active": C.STARTUP_STATE_WORKING, "done": C.STARTUP_STATE_DONE}

    def render() -> None:
        snap = run.drain()
        for (status, title, hint), row in zip(rows, snap):
            status.configure(text=_STATUS_WORDS[row["state"]])
            title.configure(text=row["title"])
            hint.configure(text=row["hint"])
        note = run.stalled_note()
        stall.configure(text=note or "")

    def close() -> None:
        if not outcome:
            outcome.append(("abandoned", None))
        try:
            root.destroy()
        except tk.TclError:
            pass

    def poll_once() -> None:
        if outcome:
            return
        try:
            render()
        except tk.TclError:
            return
        result = run.poll()
        if result is None:
            try:
                if poll is not None:
                    root.after(100, poll)
            except tk.TclError:
                pass
            return
        try:
            # run.poll() applied the final report; paint it before closing
            # so the last frame never shows "Waiting" for finished work.
            render()
        except tk.TclError:
            pass
        outcome.append(result)
        try:
            root.destroy()
        except tk.TclError:
            pass

    poll: Optional[Callable[[], None]] = poll_once
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda _event: close())
    try:
        render()
        run.start()
        root.after(100, poll_once)
        root.mainloop()
    finally:
        # The recursive callback otherwise retains itself and the destroyed
        # Tcl interpreter in a cycle. Worker-thread GC can then finalize Tcl
        # on the wrong thread and abort the process after startup completes.
        poll = None
        try:
            root.destroy()
        except tk.TclError:
            pass
    if outcome:
        return outcome[0]
    return ("abandoned", None)
