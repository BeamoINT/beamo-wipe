# SPDX-License-Identifier: GPL-3.0-or-later
"""Fullscreen Tk wizard. Huge type, one primary button, keyboard-first.

This module is a small design system on plain Tk (no themes): tokens,
canvas-drawn rounded components (buttons, cards, chips, pills, panels,
progress bars, key-caps, a countdown ring), flat chrome, and canvas icons.
The one image asset is the Beamo brand mark (assets/logo-*.png), since Tk
cannot draw the SVG source; if the files are missing the drawn fallback
emblem is used instead. Every screen is built from the same components so
the wizard looks and behaves consistently on the live USB (Linux Tk +
DejaVu) and in ./preview.

The visual language is deliberately calm and flat: old laptop panels in
bright rooms wash out heavy shadows and gradients, and a first-time user
needs hierarchy from spacing and type, not ornament.

Design rules:
- One card pattern: white, rounded, hairline border, flat. A single soft
  multi-layer shadow is reserved for the hero surface on a screen (the
  bullet card, the owner checkbox, the confirm entry, the disk summary);
  stacked list rows stay calm so lists scan cleanly.
- One selectable pattern: radio/checkbox card; selected = primary tint +
  primary ring + a soft primary halo; hover = alt surface; keyboard
  focus = focus ring.
- One alert pattern: filled badge icon + text (warn / danger / info).
- One pill pattern: rounded chip for statuses that must scan at a glance
  (disk kind, the boot-device warning, the token-match state).
- One status pattern: tinted halo badge, title, message (blocked/empty/
  done).
- One screen-header pattern: a bold ink title at a standard rhythm,
  optional muted subtitle, no ornament. Identifiers (serials, paths)
  render in readable mono.
- Chrome is white and quiet: a slim header (transparent brand mark +
  wordmark left, step label right), a hairline progress strip, and a
  single-row footer (secondary actions left, key-hints centered, primary
  action right).
- Content is vertically centered in the body so no screen reads as an
  unfinished white field; scrolling lists keep their own expansion.
- The splash is the quiet product open: a plain white field with no
  chrome, the navy-on-transparent brand mark sitting directly on the
  field, large simple type, and exactly one action (the primary
  Continue pill). The any-key shortcut is a caption, not a second
  competing affordance.
- Keyboard affordances are drawn as quiet key-caps, not buried in prose.
"""

from __future__ import annotations

import math
import re
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Callable, List, Optional

from beamo_wipe import copy as C
from beamo_wipe.methods import DEFAULT_METHOD
from beamo_wipe.models import Disk, DiskKind, MethodId, Screen
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.wizard import COUNTDOWN_S, Wizard, format_progress_percent

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
SURFACE_ALT = "#F4F6FB"
INK = "#0C1728"
MUTED = "#47536B"
BORDER = "#DCE2EC"
# Strong border: also the unchecked radio/checkbox/key-cap outline, so it
# must stay >= 3:1 on every surface (WCAG non-text contrast).
BORDER_STRONG = "#74839F"
NAVY = "#0A1B34"
NAVY_SOFT = "#16315C"
NAVY_MUTED = "#C9D6E8"
NAVY_DEEP = "#071426"  # fallback emblem platter
PRIMARY = "#1D4ED8"
PRIMARY_DARK = "#1A41B8"
PRIMARY_PRESS = "#16337F"
PRIMARY_TINT = "#E9EFFC"
DANGER = "#B3261E"
DANGER_DARK = "#8E1D16"
DANGER_PRESS = "#6E1510"
DANGER_TINT = "#FBEBE9"
DANGER_BORDER = "#E6A79E"
OK = "#17703F"
OK_TINT = "#E7F2EB"
WARN = "#7A5200"
WARN_BG = "#FBF1D5"
WARN_BORDER = "#E3CE96"
USB_BG = "#F4EFE3"
USB_BORDER = "#D9CEB5"
FOCUS = "#1A3FA0"
ACCENT = "#E8A317"
DISABLED_BG = "#E4E8EF"
DISABLED_FG = "#6E7989"
TRACK = "#DFE5EF"
# One soft shadow layer. Tk has no blur, so the single rounded rect is
# offset down a few pixels in a cool gray that stays quiet on BG.
SHADOW = "#D7DEEB"
PREVIEW_BG = "#E8A317"
PREVIEW_FG = "#0A1B34"

CONTENT_W = 940
WRAP = CONTENT_W - 72
RADIUS = 14
PILL = 999  # _rr_points clamps to half the shape: fully rounded ends
SHADOW_H = 8
HALO_INSET = 5  # canvas margin a haloed _Box reserves for its glow

# Countdown ring on the last-chance screen.
RING_SIZE = 190
RING_PAD = 14
RING_W = 11

_STEP_ORDER = {
    Screen.WHAT: (1, "Step 1 of 8", C.TITLE_WHAT),
    Screen.OWNER: (2, "Step 2 of 8", "Ownership"),
    Screen.PICK: (3, "Step 3 of 8", C.TITLE_PICK),
    Screen.PICK_EMPTY: (3, "Step 3 of 8", C.TITLE_PICK),
    Screen.PICK_BLOCKED: (3, "Step 3 of 8", C.TITLE_PICK),
    Screen.CONFIRM: (4, "Step 4 of 8", C.TITLE_CONFIRM),
    Screen.METHOD: (5, "Step 5 of 8", C.TITLE_METHOD),
    Screen.ADVANCED: (5, C.TITLE_ADVANCED, C.TITLE_ADVANCED),
    Screen.LAST_CHANCE: (6, "Step 6 of 8", C.TITLE_LAST),
    Screen.WORKING: (7, "Step 7 of 8", C.TITLE_WORKING),
    Screen.DONE: (8, "Step 8 of 8", C.TITLE_DONE_OK),
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
    pad = 2
    ring = PRIMARY if selected else BORDER_STRONG
    cv.create_oval(pad, pad, size - pad, size - pad, outline=ring, width=2)
    if selected:
        inset = size // 4 + 1
        cv.create_oval(inset, inset, size - inset, size - inset, fill=PRIMARY, outline="")
    return cv


def _icon_check_box(parent: tk.Widget, checked: bool, size: int = 28) -> tk.Canvas:
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    pad = 2
    if checked:
        _round_rect(
            cv, pad, pad, size - pad, size - pad, 7,
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
            cv, pad, pad, size - pad, size - pad, 7,
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
    """Filled badge at (x, y): triangle for warn/danger, circle for info."""
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
    else:
        color = WARN if kind == "warn" else DANGER
        cv.create_polygon(
            x + size / 2, y + 2, x + size - 2, y + size - 3, x + 2, y + size - 3,
            fill=color, outline=color, width=6, joinstyle="round",
        )
        cv.create_line(
            x + size / 2, y + size * 0.36, x + size / 2, y + size * 0.62,
            fill="#FFFFFF", width=3, capstyle="round",
        )
        cv.create_oval(
            x + size / 2 - 2, y + size * 0.72, x + size / 2 + 2, y + size * 0.72 + 4,
            fill="#FFFFFF", outline="",
        )


def _icon_alert(parent: tk.Widget, kind: str, size: int = 34) -> tk.Canvas:
    """Filled badge: triangle for warn/danger, circle for info. White glyph."""
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    _draw_alert_glyph(cv, 0, 0, size, kind)
    return cv


def _icon_badge(parent: tk.Widget, kind: str, size: int = 96) -> tk.Canvas:
    """Status-screen badge: the alert glyph on a tinted halo circle."""
    cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    tint = {"warn": WARN_BG, "danger": DANGER_TINT, "info": SURFACE_ALT}[kind]
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

    Buttons are flat pills: filled primary/danger, bordered white secondary,
    quiet ghost. All enabled buttons show a focus ring on keyboard focus, a
    hover shade under the pointer, and a darker press shade while held, so
    the control always answers the user.
    """

    # bg, fg, hover, press, outline, focus-ring.
    _VARIANTS = {
        "primary": (PRIMARY, "#FFFFFF", PRIMARY_DARK, PRIMARY_PRESS, None, FOCUS),
        "danger": (DANGER, "#FFFFFF", DANGER_DARK, DANGER_PRESS, None, FOCUS),
        "secondary": (SURFACE, INK, SURFACE_ALT, "#E6EAF0", BORDER_STRONG, FOCUS),
        "ghost": (None, PRIMARY, PRIMARY_TINT, "#D9E5F8", None, FOCUS),
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
            pad_x, pad_y = (16, 6) if compact else (24, 10)
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
        # Space activates the focused control. Return/KP_Enter deliberately
        # stay unbound here so Enter always means "this screen's primary
        # action" via the gated global handler, no matter where focus sits.
        self.bind("<space>", self._key)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self._draw()

    def _state_colors(self) -> tuple:
        bg, fg, hover, press, outline, _ring = self._VARIANTS[self._variant]
        if not self._enabled:
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
            app._space_held = True
        if self._enabled and self._command is not None:
            self._command()
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
    """Slim rounded-thumb scrollbar for the disk list.

    Same yview protocol as a stock scrollbar (the list canvas drives it via
    yscrollcommand; drags and track clicks call back into the canvas), drawn
    as a quiet rounded thumb so the list does not carry native chrome.
    """

    WIDTH = 12
    MIN_THUMB = 30

    def __init__(self, parent: tk.Widget, command: Callable) -> None:
        super().__init__(
            parent,
            width=self.WIDTH,
            highlightthickness=0,
            bd=0,
            bg=parent.cget("bg"),
            takefocus=0,
        )
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._drag_off: Optional[float] = None
        self.bind("<Configure>", lambda _e: self._draw_thumb())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)

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
        color = BORDER_STRONG if self._drag_off is not None else _mix(BORDER_STRONG, BG, 0.35)
        _round_rect(
            self, 2, y0 + 2, self.WIDTH - 2, max(y1 - 2, y0 + 4), 5,
            fill=color, outline="", tags="thumb",
        )

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


class TkWizard:
    def __init__(self, wizard: Wizard, fullscreen: bool = False) -> None:
        self.w = wizard
        self.root = tk.Tk()
        self.root._tk_wizard = self  # type: ignore[attr-defined]
        # Pin 1pt = 1px. The layout geometry below is fixed pixels (content
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
        self.root.configure(bg=BG)
        self.root.minsize(1024, 740)
        if fullscreen:
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("1280x820")
        family = _family(self.root)
        mono = _mono_family(self.root)
        # One deliberate type scale: a strong title step, calm body sizes,
        # and small quiet meta steps. Hierarchy comes from the steps between
        # sizes, not from making everything big.
        self.font_hero = tkfont.Font(root=self.root, family=family, size=64, weight="bold")
        self.font_h = tkfont.Font(root=self.root, family=family, size=34, weight="bold")
        self.font_lead = tkfont.Font(root=self.root, family=family, size=18)
        self.font_b = tkfont.Font(root=self.root, family=family, size=16)
        self.font_bold = tkfont.Font(root=self.root, family=family, size=16, weight="bold")
        # The size is the first thing owners scan for on a disk row; it gets
        # its own step on the scale so it wins the row without shouting.
        self.font_size_big = tkfont.Font(root=self.root, family=family, size=20, weight="bold")
        self.font_s = tkfont.Font(root=self.root, family=family, size=14)
        self.font_s_bold = tkfont.Font(root=self.root, family=family, size=14, weight="bold")
        self.font_tiny = tkfont.Font(root=self.root, family=family, size=12, weight="bold")
        self.font_meta = tkfont.Font(root=self.root, family=family, size=12)
        self.font_btn = tkfont.Font(root=self.root, family=family, size=17, weight="bold")
        self.font_mono = tkfont.Font(root=self.root, family=mono, size=14)
        # Serials are the safety disambiguator (the confirm token and the
        # same-size warning both point at them): bold mono, never buried.
        self.font_mono_bold = tkfont.Font(root=self.root, family=mono, size=14, weight="bold")
        self.font_mono_sm = tkfont.Font(root=self.root, family=mono, size=13)
        self.font_entry = tkfont.Font(root=self.root, family=mono, size=26, weight="bold")
        self.font_stat = tkfont.Font(root=self.root, family=family, size=56, weight="bold")
        self.font_brand = tkfont.Font(root=self.root, family=family, size=16, weight="bold")
        # The brand mark ships as PNGs (Tk cannot draw the SVG source).
        # Bound to this app's root explicitly: tests run several roots per
        # process, and an unbound PhotoImage dies with the first root.
        self._logo_header = self._load_image("logo-header.png")
        self._logo_splash = self._load_image("logo-splash.png")
        self._confirm_var = tk.StringVar()
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
        self._primary_cmd: Optional[Callable[[], None]] = None
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
        self._pick_gen = 0
        self._return_held = False
        self._space_held = False
        # Optional extra detail (device path, bus) on existing screens.
        # One flag for the session; not a new wizard step.
        self._show_more = False
        self._build_chrome()
        self._confirm_var.trace_add("write", self._confirm_var_written)
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<KP_Enter>", self._on_return)
        self.root.bind("<Return>", self._on_return)
        self.root.bind("<KeyRelease-Return>", self._on_return_release)
        self.root.bind("<KeyRelease-KP_Enter>", self._on_return_release)
        self.root.bind("<KeyRelease-space>", self._on_space_release)
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
            self.root, height=56, bg=BG, highlightthickness=0, bd=0
        )
        self._header.pack(fill=tk.X)
        self._header.bind("<Configure>", lambda _e: self._draw_header())
        self._strip = tk.Canvas(self.root, height=3, bg=TRACK, highlightthickness=0)
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
        # The screen title below names the step; the header only carries
        # quiet progress text ("STEP 3 OF 8"), never a duplicate title.
        step = _STEP_ORDER.get(self.w.screen, (0, "", ""))
        label = step[1]
        if label:
            cv.create_text(
                width - 24, mid, anchor="e",
                text=label.upper(), font=self.font_tiny, fill=MUTED,
            )

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
            # The progress fill is the brand beam, not the action color.
            _round_rect(cv, 0, 0, max(4.0, width * frac), 3, 1.5, fill=ACCENT, outline="")

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
            self._arm_shutdown_enter_if_idle()
            self._draw()

        return wrapped

    def _arm_shutdown_enter_if_idle(self) -> None:
        if self._return_held or self._space_held:
            return
        if self.w.screen in (Screen.DONE, Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            self.w.arm_done_keyboard()

    def _teardown(self) -> None:
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
            prev = self.w.screen
            self.w.tick()
            if self.w.screen != prev:
                self._arm_shutdown_enter_if_idle()
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
            self._pick_canvas = None
            self._pick_cards = {}
            self._pick_restore_pending = False
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
        self._match_pill = None
        screen = self.w.screen
        self._sync_chrome(screen == Screen.SPLASH)
        self._body.configure(bg=BG)
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
        self._draw_header()
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
        the same place on each step. ``compact`` is for the method screen,
        the tightest layout, which must fit the 1024x740 minimum window.
        """
        top = 10 if compact else 24
        bottom = 6 if compact else 14
        tk.Label(
            col, text=title, font=self.font_h, fg=INK, bg=BG,
            wraplength=WRAP, justify=tk.LEFT, anchor="w",
        ).pack(fill=tk.X, pady=(top, 4 if subtitle else bottom))
        if subtitle:
            self._p(col, subtitle, fg=MUTED, font=self.font_b).pack(
                fill=tk.X, pady=(0, bottom)
            )

    def _center_zone(self, col: tk.Frame) -> tk.Frame:
        """A vertically centered content band between title and footer.

        Short content floating at the top of a tall white body reads as
        unfinished; equal spacers above and below put the content in the
        optical middle instead. Scrolling lists keep their own expansion
        and do not use this.
        """
        zone = tk.Frame(col, bg=BG)
        zone.pack(fill=tk.BOTH, expand=True)
        tk.Frame(zone, bg=BG).pack(fill=tk.BOTH, expand=True)
        content = tk.Frame(zone, bg=BG)
        content.pack(fill=tk.X)
        tk.Frame(zone, bg=BG).pack(fill=tk.BOTH, expand=True)
        return content

    def _chip(self, parent: tk.Widget, text: str, *, fg: str, bg: str) -> _Box:
        chip = _Box(parent, radius=PILL, fill=bg, outline=None, ow=0, padx=10, pady=2)
        tk.Label(chip.inner, text=text, font=self.font_tiny, fg=fg, bg=bg).pack()
        chip.fit_now()
        return chip

    def _kbd(self, parent: tk.Widget, text: str) -> _Box:
        """A quiet keyboard key-cap. Makes keyboard affordances scannable."""
        cap = _Box(parent, radius=6, fill=SURFACE_ALT, outline=BORDER, ow=1, padx=7, pady=1)
        tk.Label(cap.inner, text=text, font=self.font_tiny, fg=INK, bg=SURFACE_ALT).pack()
        cap.fit_now()
        return cap

    def _hint_bar(self, parent: tk.Widget, hint: str) -> tk.Frame:
        """Hint copy with known key names rendered as key-caps, centered."""
        bar = tk.Frame(parent, bg=BG)
        inner = tk.Frame(bar, bg=BG)
        inner.pack(anchor="center", expand=True)
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
    ) -> _Box:
        colors = {
            "warn": (WARN_BG, WARN_BORDER),
            "danger": (DANGER_TINT, DANGER_BORDER),
            "info": (SURFACE_ALT, BORDER),
        }
        bg, border = colors[kind]
        box = _Box(parent, radius=12, fill=bg, outline=border, ow=1, padx=16, pady=13)
        row = tk.Frame(box.inner, bg=bg)
        row.pack(fill=tk.X)
        icon = _icon_alert(row, kind, 28)
        icon.configure(bg=bg)
        icon.pack(side=tk.LEFT, anchor="n", pady=1)
        lines = tk.Frame(row, bg=bg)
        lines.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0))
        tk.Label(
            lines, text=text, font=self.font_b, fg=INK, bg=bg,
            wraplength=WRAP - 110, justify=tk.LEFT, anchor="w",
        ).pack(fill=tk.X)
        if extra:
            tk.Label(
                lines, text=extra, font=self.font_s, fg=MUTED, bg=bg,
                wraplength=WRAP - 110, justify=tk.LEFT, anchor="w",
            ).pack(fill=tk.X, pady=(4, 0))
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

    def _kind_chip(self, parent: tk.Widget, disk: Disk) -> None:
        label = C.kind_label(disk.kind)
        if not label:
            return
        self._chip(parent, label, fg=MUTED, bg=SURFACE_ALT).pack(
            side=tk.LEFT, padx=(10, 0)
        )

    def _more_link(self, parent: tk.Widget, *, bg: str = BG) -> bool:
        """Optional extra detail on this screen. Not a new step."""
        open_ = self._show_more
        link = tk.Label(
            parent,
            text=C.BTN_LESS if open_ else C.BTN_MORE,
            font=self.font_s_bold,
            fg=PRIMARY,
            bg=bg,
            cursor="hand2",
            anchor="w",
        )
        link.pack(anchor="w", pady=(8, 0))

        def toggle(_event=None) -> str:
            self._show_more = not self._show_more
            self._draw()
            return "break"

        link.bind("<Button-1>", toggle)
        return open_

    def _meta_line(self, parent: tk.Widget, disk: Disk, bg: str) -> tk.Frame:
        """Characters they may type, then optional bus · path behind Show more."""
        meta = tk.Frame(parent, bg=bg)
        serial = disk.serial or C.NO_CODE
        tk.Label(meta, text=serial, font=self.font_mono_bold, fg=INK, bg=bg).pack(
            side=tk.LEFT
        )
        if self._show_more:
            tk.Label(meta, text="·", font=self.font_s, fg=BORDER_STRONG, bg=bg).pack(
                side=tk.LEFT, padx=6
            )
            tk.Label(meta, text=disk.bus, font=self.font_s, fg=MUTED, bg=bg).pack(
                side=tk.LEFT
            )
            tk.Label(meta, text="·", font=self.font_s, fg=BORDER_STRONG, bg=bg).pack(
                side=tk.LEFT, padx=6
            )
            tk.Label(
                meta, text=disk.path, font=self.font_mono_sm, fg=MUTED, bg=bg
            ).pack(side=tk.LEFT)
        return meta

    def _disk_summary(self, parent: tk.Widget, disk: Disk) -> _Box:
        """The selected disk, shown the same way on confirm, working, and done."""
        box = _Box(
            parent, radius=RADIUS, fill=SURFACE, outline=BORDER, ow=1,
            padx=20, pady=16, shadow=True,
        )
        inner = box.inner
        top = tk.Frame(inner, bg=SURFACE)
        top.pack(fill=tk.X)
        tk.Label(
            top, text=disk.display_name, font=self.font_bold, fg=INK, bg=SURFACE, anchor="w"
        ).pack(side=tk.LEFT)
        self._kind_chip(top, disk)
        tk.Label(
            top, text=disk.size_phrase, font=self.font_size_big, fg=INK, bg=SURFACE, anchor="e"
        ).pack(side=tk.RIGHT)
        self._meta_line(inner, disk, SURFACE).pack(fill=tk.X, pady=(4, 0))
        return box

    # -- footer / buttons -----------------------------------------------------

    def _close_label(self) -> str:
        return C.BTN_CLOSE_PREVIEW if self.w.preview else C.BTN_SHUTDOWN

    def _footer_shell(self, hint: str) -> tk.Frame:
        """One-row footer: secondary actions left, key hints centered,
        the primary action right. A single hairline separates it from the
        body. Buttons pack into ``row._left`` / ``row._right``."""
        assert self._footer is not None
        col = self._column(self._footer, fill_height=False)
        tk.Frame(col, bg=BORDER, height=1).pack(fill=tk.X)
        row = tk.Frame(col, bg=BG)
        row.pack(fill=tk.X, pady=(12, 16))
        left = tk.Frame(row, bg=BG)
        left.pack(side=tk.LEFT)
        right = tk.Frame(row, bg=BG)
        right.pack(side=tk.RIGHT)
        mid = tk.Frame(row, bg=BG)
        mid.pack(fill=tk.BOTH, expand=True)
        self._hint = self._hint_bar(mid, hint)
        self._hint.pack(fill=tk.BOTH, expand=True)
        row._left = left  # type: ignore[attr-defined]
        row._right = right  # type: ignore[attr-defined]
        return row

    def _back_btn(self, row: tk.Frame) -> _Button:
        btn = _Button(
            row._left,  # type: ignore[attr-defined]
            text=C.BTN_BACK,
            command=self._nav(self.w.back),
            font=self.font_btn,
            variant="secondary",
            min_width=112,
        )
        btn.pack(side=tk.LEFT)
        return btn

    def _secondary_btn(self, row: tk.Frame, text: str, command: Callable[[], None]) -> _Button:
        btn = _Button(
            row._left,  # type: ignore[attr-defined]
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
            mark = tk.Canvas(col, width=70, height=58, bg=BG, highlightthickness=0, bd=0)
            _draw_emblem(mark, 35.0, 29.0, 54)
            mark.pack()
        tk.Label(col, text=C.APP_NAME, font=self.font_hero, fg=INK, bg=BG).pack(pady=(26, 0))
        self._p(
            col, C.SPLASH_TAGLINE, fg=MUTED, font=self.font_lead,
            wraplength=620, justify=tk.CENTER, anchor="center",
        ).pack(fill=tk.X, pady=(12, 0))
        hero = _Button(
            col,
            text=C.BTN_CONTINUE,
            command=self._nav(self.w.skip_splash),
            font=self.font_btn,
            variant="primary",
            large=True,
            min_width=240,
        )
        hero.pack(pady=(34, 0))
        self._primary = hero
        self._primary_cmd = self.w.skip_splash
        tk.Label(col, text=C.HINT_SPLASH, font=self.font_meta, fg=MUTED, bg=BG).pack(pady=(14, 0))
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        hero.focus_set()

    def _what(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_WHAT, C.WHAT_LEAD)
        zone = self._center_zone(col)
        card = _Box(
            zone, radius=RADIUS, fill=SURFACE, outline=BORDER, ow=1,
            padx=24, pady=20, shadow=True,
        )
        card.pack(fill=tk.X)
        for i, bullet in enumerate(C.WHAT_BULLETS):
            line = tk.Frame(card.inner, bg=SURFACE)
            line.pack(fill=tk.X, pady=(2 if i == 0 else 14, 2 if i == len(C.WHAT_BULLETS) - 1 else 0))
            marker = tk.Canvas(line, width=10, height=26, bg=SURFACE, highlightthickness=0)
            marker.create_oval(1, 9, 8, 16, fill=ACCENT, outline="")
            marker.pack(side=tk.LEFT, anchor="n")
            tk.Label(
                line, text=bullet, font=self.font_lead, fg=INK, bg=SURFACE,
                wraplength=WRAP - 120, justify=tk.LEFT, anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        if self._more_link(zone):
            self._panel(
                zone, kind="info", text=C.SECURE_BOOT_HINT, extra=C.ENGINE_LINE
            ).pack(fill=tk.X, pady=(12, 0))
        row = self._footer_shell(C.HINT_DEFAULT)
        self._secondary_btn(row, self._close_label(), self._click_shutdown)
        self._primary_btn(row, C.BTN_UNDERSTAND, self.w.accept_what)
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
            padx=22,
            pady=20,
            ring=True,
            halo=checked,
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
            wraplength=WRAP - 140,
            justify=tk.LEFT,
            anchor="w",
        )
        text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 0))
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

    def _disk_row(self, parent: tk.Widget, disk: Disk, selected: bool) -> _Box:
        if disk.is_boot:
            fill, outline, ow = USB_BG, USB_BORDER, 1
        elif selected:
            fill, outline, ow = PRIMARY_TINT, PRIMARY, 2
        else:
            fill, outline, ow = SURFACE, BORDER, 1
        card = _Box(
            parent, radius=RADIUS, fill=fill, outline=outline, ow=ow,
            padx=18, pady=15, halo=selected and not disk.is_boot,
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
        title_row = tk.Frame(title_col, bg=fill)
        title_row.pack(fill=tk.X)
        tk.Label(
            title_row, text=disk.display_name, font=self.font_bold, fg=INK, bg=fill, anchor="w"
        ).pack(side=tk.LEFT)
        self._kind_chip(title_row, disk)
        tk.Label(
            title_row, text=disk.size_phrase, font=self.font_size_big, fg=INK, bg=fill, anchor="e"
        ).pack(side=tk.RIGHT)
        self._meta_line(title_col, disk, fill).pack(fill=tk.X, pady=(4, 0))
        if disk.is_boot:
            banner = C.BOOT_USB_BANNER if disk.bus == "USB" else C.BOOT_DISC_BANNER
            pill = _Box(
                inner, radius=PILL, fill=DANGER_TINT, outline=DANGER_BORDER,
                ow=1, padx=11, pady=3,
            )
            tk.Label(
                pill.inner, text=banner, font=self.font_s_bold, fg=DANGER, bg=DANGER_TINT
            ).pack()
            pill.fit_now()
            pill.pack(anchor="w", pady=(10, 0), padx=(36, 0))
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
                lambda c=card: c.set_style(fill=SURFACE_ALT),
                lambda c=card: c.set_style(fill=SURFACE),
            )
        return card

    def _pick(self) -> None:
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_PICK, C.pick_subtitle())
        if same_size_conflict(self.w.listed_disks):
            self._panel(col, kind="warn", text=C.SAME_SIZE_HINT).pack(fill=tk.X, pady=(0, 12))
        if self.w.selected and self.w.selected.kind in (DiskKind.SSD, DiskKind.NVME):
            self._panel(col, kind="info", text=C.SSD_FOOTER).pack(fill=tk.X, pady=(0, 12))
        self._more_link(col)
        list_wrap = tk.Frame(col, bg=BG)
        list_wrap.pack(fill=tk.BOTH, expand=True, pady=(2, 4))
        canvas = tk.Canvas(list_wrap, bg=BG, highlightthickness=0)
        cards = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=cards, anchor="nw")

        def _stretch(_event=None) -> None:
            canvas.itemconfigure(window_id, width=max(1, canvas.winfo_width()))
            canvas.configure(scrollregion=canvas.bbox("all"))
            self._pick_restore_scroll()

        cards.bind("<Configure>", _stretch)
        canvas.bind("<Configure>", _stretch)

        def _user_scrolled(*args) -> None:
            # The restore window only re-applies the pre-rebuild offset; the
            # first real scroll input ends it so the user owns the position.
            self._pick_restore_pending = False
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
        items: List = sorted(self.w.listed_disks, key=lambda d: (d.is_boot, d.path))
        for disk in items:
            selected = self.w.selected is not None and disk.path == self.w.selected.path
            self._pick_cards[disk.path] = self._disk_row(cards, disk, selected)
        self._pick_canvas = canvas
        # Restore only inside a short post-rebuild window. Row boxes and the
        # footer resolve their heights over several Configure/idle passes and
        # the view height can oscillate while settling, clamping any offset
        # applied against a transient geometry — so the window re-applies on
        # a few timed retries, and closes early only when a scroll the
        # restore itself did not make (user wheel/drag) is detected.
        self._pick_restore_pending = True
        self._pick_applied = None
        self._pick_gen += 1
        gen = self._pick_gen
        canvas.after_idle(self._pick_restore_scroll)
        canvas.after(30, lambda: self._pick_restore_tick(gen))
        canvas.after(90, lambda: self._pick_restore_tick(gen))
        canvas.after(180, lambda: self._pick_restore_tick(gen, final=True))
        row = self._footer_shell(C.HINT_PICK)
        back = self._back_btn(row)
        can = self.w.selected is not None and not self.w.selected.is_boot
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_pick, enabled=can)
        # Always land keyboard focus somewhere sensible: the obvious next
        # action when a disk is chosen, otherwise the safe way out.
        (self._primary if can and self._primary is not None else back).focus_set()

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
            if self._pick_applied is not None and abs(current_top - self._pick_applied) > 2:
                # The offset moved without this restore doing it: a wheel,
                # a drag, or a direct yview call. That party owns the scroll
                # position now; the window closes without re-applying.
                self._pick_restore_pending = False
                self._pick_applied = None
                return
            selected = self.w.selected
            card = self._pick_cards.get(selected.path) if selected else None
            if self._pick_ensure_visible and card is not None:
                view0 = current_top
                view1 = view0 + view_h
                y0 = float(card.winfo_y())
                y1 = y0 + card.winfo_height()
                if y0 < view0:
                    canvas.yview_moveto(max(0.0, y0 / content_h))
                elif y1 > view1:
                    canvas.yview_moveto(max(0.0, min(1.0, (y1 - view_h) / content_h)))
            else:
                canvas.yview_moveto(max(0.0, self._pick_scroll / content_h))
            self._pick_applied = canvas.yview()[0] * content_h
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
        self._p(
            col, message, fg=MUTED, font=self.font_b,
            wraplength=700, justify=tk.CENTER, anchor="center",
        ).pack(fill=tk.X)
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)

    def _blocked(self) -> None:
        self._status_screen("warn", C.TITLE_BLOCKED, self.w.error or C.IDENTIFY_ERROR)
        row = self._footer_shell(C.HINT_BLOCKED)
        self._back_btn(row)
        self._primary_btn(row, self._close_label(), self._click_shutdown)
        if self._primary is not None:
            self._primary.focus_set()

    def _empty(self) -> None:
        self._status_screen("info", C.TITLE_EMPTY, C.EMPTY_DISKS)
        row = self._footer_shell(C.HINT_BLOCKED)
        self._back_btn(row)
        self._primary_btn(row, self._close_label(), self._click_shutdown)
        if self._primary is not None:
            self._primary.focus_set()

    def _confirm(self) -> None:
        disk = self.w.selected
        assert disk is not None
        spec = self.w.confirm
        assert spec is not None
        col = self._column(self._body, fill_height=True)
        self._title_block(col, C.TITLE_CONFIRM)
        zone = self._center_zone(col)
        self._disk_summary(zone, disk).pack(fill=tk.X)
        self._more_link(zone)
        self._panel(zone, kind="warn", text=self.w.warning_text()).pack(fill=tk.X, pady=(12, 0))
        self._p(zone, spec.prompt, font=self.font_b).pack(fill=tk.X, pady=(14, 8))
        shell = _Box(
            zone, radius=12, fill=SURFACE, outline=BORDER_STRONG, ow=1,
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
        entry.pack(fill=tk.X, ipady=4)
        entry.bind("<FocusIn>", lambda _e: shell.set_focused(True))
        entry.bind("<FocusOut>", lambda _e: shell.set_focused(False))
        shell.set_focused(True)
        entry.focus_set()
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
        self._primary_btn(row, C.BTN_CONTINUE, self.w.continue_confirm, enabled=self.w.token_ok)

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
                6, 11.5, 9.5, 15, 16, 7.5,
                fill="#FFFFFF", width=3, capstyle="round", joinstyle="round",
            )
            self._match_label.configure(text=C.CONFIRM_MATCH_OK, fg=OK, bg=OK_TINT)
        else:
            if self._match_pill is not None:
                self._match_pill.set_style(fill=SURFACE_ALT, outline=BORDER)
            cv.configure(bg=SURFACE_ALT)
            cv.create_oval(2, 2, 20, 20, outline=BORDER_STRONG, width=2)
            self._match_label.configure(text=C.CONFIRM_MATCH_WAIT, fg=MUTED, bg=SURFACE_ALT)

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
            padx=18, pady=13, halo=selected,
        )
        card.pack(fill=tk.X, pady=(0, 10), padx=4)
        inner = card.inner
        top = tk.Frame(inner, bg=fill)
        top.pack(fill=tk.X)
        icon = _icon_radio(top, selected, 22)
        icon.configure(bg=fill)
        icon.pack(side=tk.LEFT, anchor="n", pady=1)
        # Blurb and pace live in the title column so the card's text shares
        # one left edge instead of stair-stepping under the radio.
        text_col = tk.Frame(top, bg=fill)
        text_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))
        title_row = tk.Frame(text_col, bg=fill)
        title_row.pack(fill=tk.X)
        self._kbd(title_row, card_copy["key"]).pack(side=tk.LEFT)
        tk.Label(
            title_row, text=card_copy["title"], font=self.font_bold, fg=INK, bg=fill, anchor="w"
        ).pack(side=tk.LEFT, padx=(10, 0))
        if method == DEFAULT_METHOD:
            self._chip(title_row, C.RECOMMENDED_TAG, fg=OK, bg=OK_TINT).pack(
                side=tk.LEFT, padx=(10, 0)
            )
        tk.Label(
            text_col,
            text=card_copy["blurb"],
            font=self.font_s,
            fg=MUTED,
            bg=fill,
            wraplength=WRAP - 130,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))
        pace_row = tk.Frame(text_col, bg=fill)
        pace_row.pack(fill=tk.X, pady=(4, 0))
        clock = _icon_clock(pace_row, 16)
        clock.configure(bg=fill)
        clock.pack(side=tk.LEFT, anchor="n", pady=1)
        tk.Label(
            pace_row,
            text=card_copy["pace"],
            font=self.font_s,
            fg=MUTED,
            bg=fill,
            wraplength=WRAP - 160,
            justify=tk.LEFT,
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(7, 0))

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
        self._title_block(col, C.TITLE_METHOD, C.METHOD_LEAD, compact=True)
        zone = self._center_zone(col)
        for method in (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO):
            self._method_card(zone, method)
        adv = _Button(
            zone,
            text=C.BTN_ADVANCED,
            command=self._nav(self.w.open_advanced),
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
        self._title_block(col, C.TITLE_LAST, C.LAST_LEAD)
        self._panel(col, kind="danger", text=self.w.erase_label()).pack(fill=tk.X)
        if self.w.error:
            self._panel(col, kind="danger", text=self.w.error).pack(fill=tk.X, pady=(12, 0))
        zone = self._center_zone(col)
        ring = tk.Canvas(
            zone, width=RING_SIZE, height=RING_SIZE, bg=BG, highlightthickness=0
        )
        ring.pack()
        self._countdown_ring = ring
        self._countdown_num = tk.Label(
            ring, text="", font=self.font_stat, fg=INK, bg=BG, anchor="center"
        )
        ring.create_window(RING_SIZE / 2, RING_SIZE / 2 - 3, window=self._countdown_num)
        self._countdown_label = tk.Label(
            zone, text="", font=self.font_b, fg=MUTED, bg=BG, anchor="center", justify=tk.CENTER
        )
        self._countdown_label.pack(fill=tk.X, pady=(12, 0))
        row = self._footer_shell(C.HINT_LAST_CHANCE)
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
        edge0 = RING_PAD
        edge1 = RING_SIZE - RING_PAD
        center = RING_SIZE / 2.0
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
            ring.create_oval(tx - 6.5, ty - 6.5, tx + 6.5, ty + 6.5, fill=PRIMARY, outline="", tags="arc")
            if self._countdown_num is not None:
                self._countdown_num.configure(text=str(left), fg=INK)
            self._countdown_label.configure(text=C.COUNTDOWN_CAPTION, fg=MUTED)
        else:
            ring.create_oval(edge0, edge0, edge1, edge1, outline=OK, width=RING_W, tags="arc")
            if self._countdown_num is not None:
                self._countdown_num.configure(text="✓", fg=OK)
            self._countdown_label.configure(text=C.COUNTDOWN_READY, fg=OK)
        self._set_primary_enabled(self.w.erase_enabled)

    def _working(self) -> None:
        col = self._column(self._body, fill_height=True)
        disk = self.w.selected
        self._title_block(col, C.TITLE_WORKING)
        if disk is not None:
            self._disk_summary(col, disk).pack(fill=tk.X)
            self._more_link(col)
        card_copy = C.METHOD_CARDS[self.w.method]
        zone = self._center_zone(col)
        self._progress_pct = tk.Label(
            zone, text="", font=self.font_stat, fg=INK, bg=BG, anchor="w"
        )
        self._progress_pct.pack(fill=tk.X, pady=(0, 12))
        bar = tk.Canvas(zone, height=14, bg=BG, highlightthickness=0)
        bar.pack(fill=tk.X)
        bar.bind("<Configure>", lambda _e: self._refresh_working())
        self._progress_bar = bar
        self._progress_label = self._p(
            zone, f"{card_copy['title']}.  {C.WORKING_PULSE}", fg=MUTED, font=self.font_b
        )
        self._progress_label.pack(fill=tk.X, pady=(14, 0))
        # Cancel is a secondary action: visible but not primary to avoid
        # accidental clicks. Always shown so interruption is reachable.
        row = self._footer_shell(C.HINT_WORKING)
        # Left side: Cancel; Right side empty (no primary while working)
        # HINT_WORKING already says "Leave this USB in…" but we add explicit hint
        self._secondary_btn(row, "Cancel erase", self._click_cancel)
        self._refresh_working()

    def _refresh_working(self) -> None:
        if self._progress_label is None:
            return
        pulse = f"{C.METHOD_CARDS[self.w.method]['title']}.  {C.WORKING_PULSE}"
        pct = self.w.progress
        if pct is None:
            # nwipe has not reported a number yet: slide a segment back and
            # forth so the screen never looks frozen.
            if self._progress_pct is not None:
                self._progress_pct.configure(text="")
            self._progress_label.configure(text=pulse)
            self._indet = (self._indet + 0.045) % 2.0
            pos = self._indet if self._indet <= 1.0 else 2.0 - self._indet
            self._paint_bar(None, pos)
        else:
            if self._progress_pct is not None:
                self._progress_pct.configure(text=format_progress_percent(pct))
            self._progress_label.configure(text=pulse)
            self._paint_bar(max(0.02, pct / 100.0))

    def _paint_bar(self, frac: Optional[float], indet_pos: float = 0.0) -> None:
        bar = self._progress_bar
        if bar is None:
            return
        bar.delete("all")
        width = max(bar.winfo_width(), 1)
        _round_rect(bar, 0, 0, width, 14, 7, fill=TRACK, outline="")
        if frac is None:
            seg = width * 0.30
            x1 = seg + (width - seg) * indet_pos
            x0 = x1 - seg
            _round_rect(bar, max(0, x0), 0, min(width, x1), 14, 7, fill=PRIMARY, outline="")
            return
        fill_w = width * min(1.0, frac)
        if fill_w > 1:
            _round_rect(bar, 0, 0, max(fill_w, 14), 14, 7, fill=PRIMARY, outline="")

    def _done(self) -> None:
        col = self._column(self._body, fill_height=True)
        ok = self.w.done_ok
        title = C.TITLE_DONE_OK if ok else C.TITLE_DONE_FAIL
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        icon = _icon_status(col, ok, 96)
        icon.configure(bg=BG)
        icon.pack()
        heading = self._h(col, title)
        heading.configure(anchor="center", justify=tk.CENTER)
        heading.pack(fill=tk.X, pady=(22, 8))
        if self.w.preview:
            msg = C.DONE_OK_PREVIEW if ok else C.DONE_FAIL_PREVIEW
        else:
            msg = C.DONE_OK if ok else C.DONE_FAIL
        # The badge carries the state color; the message stays readable ink.
        self._p(
            col, msg, font=self.font_b, wraplength=700, justify=tk.CENTER, anchor="center"
        ).pack(fill=tk.X)
        if self.w.selected is not None:
            self._disk_summary(col, self.w.selected).pack(fill=tk.X, pady=(24, 0))
            self._more_link(col)
        tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)
        row = self._footer_shell(C.HINT_DEFAULT if self.w.preview else C.HINT_DONE)
        if self.w.preview:
            self._secondary_btn(row, C.BTN_CLOSE_PREVIEW, self._click_shutdown)
            self._primary_btn(row, C.BTN_RUN_AGAIN, self.w.reset_for_preview)
        else:
            self._primary_btn(row, C.BTN_SHUTDOWN, self._click_shutdown)
        if self._primary is not None:
            self._primary.focus_set()

    def _advanced(self) -> None:
        col = self._column(self._body, fill_height=True)
        # Compact header: this is the second-tightest screen after method,
        # and it must fit the 1024x740 minimum window with the footer whole.
        self._title_block(col, C.TITLE_ADVANCED, C.ADVANCED_LEAD, compact=True)
        from beamo_wipe.methods import METHODS

        zone = self._center_zone(col)
        card = _Box(
            zone, radius=RADIUS, fill=SURFACE, outline=BORDER, ow=1,
            padx=20, pady=12, shadow=True,
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
                wraplength=WRAP - 60,
                justify=tk.LEFT,
            ).pack(fill=tk.X, pady=(7, 7))
        log = self.w._wipe_request.logfile if self.w._wipe_request else "(no wipe yet)"
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
        row = self._footer_shell(C.HINT_DEFAULT)
        self._back_btn(row)
        self._primary_btn(row, C.BTN_CONTINUE, self.w.close_advanced)
        if self._primary is not None:
            self._primary.focus_set()

    # -- keyboard ------------------------------------------------------------

    def _on_escape(self, _event=None) -> str:
        if self.w.screen == Screen.SPLASH:
            self.w.skip_splash()
            self._draw()
            return "break"
        if self.w.screen == Screen.WORKING:
            # Working: Esc triggers visible cancel (fail-safe interruption)
            try:
                self.w.cancel_wipe()
            except Exception as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("ui", "escape_cancel_failed", type(exc).__name__)
                except Exception:
                    pass
            self._draw()
            return "break"
        if self.w.screen not in (Screen.WHAT, Screen.DONE):
            self.w.back()
            self._draw()
        return "break"

    def _on_return_release(self, _event=None) -> str:
        self._return_held = False
        self.w.arm_done_keyboard()
        return "break"

    def _on_space_release(self, _event=None) -> str:
        self._space_held = False
        self.w.arm_done_keyboard()
        return "break"

    def _click_cancel(self) -> None:
        """Visible cancel on WORKING. Never silently ignored."""
        try:
            self.w.cancel_wipe()
        except Exception as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("ui", "cancel_click_failed", type(exc).__name__)
            except Exception:
                pass
        self._draw()

    def _click_shutdown(self) -> None:
        """Button Space/click on Shut down. Ignore until the arriving key is up."""
        if self.w.screen in (Screen.DONE, Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            if not self.w._done_keyboard_armed:
                return
        self.w.shutdown()

    def _on_return(self, _event=None) -> str:
        # X11 auto-repeat is extra KeyPress events with no KeyRelease. The
        # same physical Enter would skip Confirm → Method → Last chance.
        if self._return_held:
            return "break"
        self._return_held = True
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
            self.w.accept_done_keyboard()
        elif screen == Screen.ADVANCED:
            self.w.close_advanced()
        elif screen in (Screen.PICK_BLOCKED, Screen.PICK_EMPTY):
            self.w.accept_done_keyboard()
        if self.w.wants_shutdown:
            self._teardown()
            return "break"
        if self.w.screen != before or screen != Screen.CONFIRM:
            self._draw()
        return "break"

    def _on_key(self, event) -> Optional[str]:
        if event.keysym in ("Return", "KP_Enter", "Escape", "Tab"):
            return None
        if event.keysym == "space":
            self._space_held = True
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
            self._pick_ensure_visible = True
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
        if self.w.screen == Screen.WORKING and not self.w.preview:
            # Window close on WORKING is now an explicit cancel (visible
            # evidence with "interrupted" outcome) instead of silently blocked.
            try:
                self.w.cancel_wipe()
            except Exception as exc:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("ui", "close_cancel_failed", type(exc).__name__)
                except Exception:
                    pass
            self._draw()
            return
        self.w.shutdown()
        self._teardown()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def run_tk(wizard: Wizard, fullscreen: bool = False) -> int:
    ui = TkWizard(wizard, fullscreen=fullscreen)
    return ui.run()
