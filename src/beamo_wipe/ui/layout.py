# SPDX-License-Identifier: GPL-3.0-or-later
"""Window-size layout for the Tk wizard. No I/O. No product behavior."""

from __future__ import annotations

from dataclasses import dataclass

# Supported live-USB sizes. 800x600 and 1280x720 are real layouts, not
# "degraded with missing actions". 1024x740 is a comfortable tall layout.
# Larger windows may enlarge type slightly.
MIN_SIZE = (800, 600)
NETBOOK_SIZE = (1024, 600)
LAPTOP_SIZE = (1280, 720)
SUPPORTED_SIZE = (1024, 740)
DEFAULT_SIZE = (1280, 820)
LARGE_SIZE = (1600, 1000)
# Shorter than the old 1024x740 "comfortable" height uses compact pads and
# a scrolling body so 720p laptops and 800x600 panels keep footer actions.
SHORT_HEIGHT = 740

MAX_CONTENT = 940
LARGE_CONTENT = 1080

TEXT_SIZE_STANDARD = "standard"
TEXT_SIZE_LARGE = "large"
TEXT_SIZE_EXTRA = "extra"
TEXT_SIZES = (TEXT_SIZE_STANDARD, TEXT_SIZE_LARGE, TEXT_SIZE_EXTRA)
TEXT_SIZE_SCALE = {
    TEXT_SIZE_STANDARD: 1.0,
    TEXT_SIZE_LARGE: 1.2,
    TEXT_SIZE_EXTRA: 1.35,
}


def _px(base: int, scale: float, floor: int) -> int:
    return max(floor, int(round(base * scale)))


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    compact: bool
    short: bool
    narrow: bool
    large: bool
    content_w: int
    wrap: int
    scale: float
    header_h: int
    ring: int
    title_top: int
    title_bottom: int
    footer_pad_y: int
    stack_review: bool
    text_size: str
    font: dict[str, int]

    @property
    def key(self) -> tuple:
        return (
            self.compact,
            self.short,
            self.narrow,
            self.large,
            self.content_w,
            self.scale,
            self.ring,
            self.stack_review,
            self.text_size,
        )


def opening_size(screen_w: int, screen_h: int) -> tuple[int, int]:
    """Default window that fits the panel. Never below MIN_SIZE."""
    width = min(DEFAULT_SIZE[0], max(MIN_SIZE[0], int(screen_w)))
    height = min(DEFAULT_SIZE[1], max(MIN_SIZE[1], int(screen_h)))
    return width, height


def layout_for(
    width: int, height: int, text_size: str = TEXT_SIZE_STANDARD
) -> Layout:
    """Deterministic layout from the mapped window size, not X DPI.

    ``text_size`` only scales pixel fonts. Window compact/short/gutter stay
    put so Extra large wraps and scrolls instead of clipping the footer.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    if text_size not in TEXT_SIZE_SCALE:
        text_size = TEXT_SIZE_STANDARD
    text_scale = TEXT_SIZE_SCALE[text_size]
    narrow = width < 960
    short = height < SHORT_HEIGHT
    compact = narrow or short
    large = width >= 1600 and height >= 900 and not compact
    if compact:
        scale = 0.88
        cap = MAX_CONTENT
        gutter = 16
        header_h = 48
        ring = 64
        title_top = 8
        title_bottom = 6
        footer_pad_y = 8
    elif large:
        scale = 1.15
        cap = LARGE_CONTENT
        gutter = 48
        header_h = 56
        ring = 64
        title_top = 18
        title_bottom = 12
        footer_pad_y = 16
    else:
        scale = 1.0
        cap = MAX_CONTENT
        gutter = 40
        header_h = 56
        ring = 64
        title_top = 16
        title_bottom = 10
        footer_pad_y = 16
    content_w = min(cap, max(280, width - 2 * gutter))
    wrap = max(200, content_w - (40 if compact else 72))
    font_scale = scale * text_scale
    font = {
        "hero": _px(52, font_scale, 32),
        "h": _px(30, font_scale, 20),
        "lead": _px(18, font_scale, 14),
        "b": _px(16, font_scale, 14),
        "size_big": _px(20, font_scale, 16),
        "s": _px(14, font_scale, 12),
        "tiny": _px(12, font_scale, 12),
        "btn": _px(16, font_scale, 14),
        "mono": _px(14, font_scale, 12),
        "mono_sm": _px(13, font_scale, 12),
        "entry": _px(26, font_scale, 18),
        "stat": _px(56, font_scale, 32),
        "brand": _px(16, font_scale, 14),
    }
    return Layout(
        width=width,
        height=height,
        compact=compact,
        short=short,
        narrow=narrow,
        large=large,
        content_w=content_w,
        wrap=wrap,
        scale=scale,
        header_h=header_h,
        ring=ring,
        title_top=title_top,
        title_bottom=title_bottom,
        footer_pad_y=footer_pad_y,
        stack_review=narrow or short,
        text_size=text_size,
        font=font,
    )
