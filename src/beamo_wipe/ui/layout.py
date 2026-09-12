# SPDX-License-Identifier: GPL-3.0-or-later
"""Window-size layout for the Tk wizard. No I/O. No product behavior."""

from __future__ import annotations

from dataclasses import dataclass

# Supported live-USB sizes. 800x600 and 1024x600 are real layouts, not
# "degraded with missing actions". Larger windows may enlarge type slightly.
MIN_SIZE = (800, 600)
NETBOOK_SIZE = (1024, 600)
SUPPORTED_SIZE = (1024, 740)
DEFAULT_SIZE = (1280, 820)
LARGE_SIZE = (1600, 1000)

MAX_CONTENT = 940
LARGE_CONTENT = 1080


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
        )


def layout_for(width: int, height: int) -> Layout:
    """Deterministic layout from the mapped window size, not X DPI."""
    width = max(1, int(width))
    height = max(1, int(height))
    narrow = width < 960
    short = height < 680
    compact = narrow or short
    large = width >= 1600 and height >= 900 and not compact
    if compact:
        scale = 0.88
        cap = MAX_CONTENT
        gutter = 16
        header_h = 48
        ring = 96 if short or narrow else 144
        title_top = 8
        title_bottom = 6
        footer_pad_y = 8
    elif large:
        scale = 1.15
        cap = LARGE_CONTENT
        gutter = 48
        header_h = 56
        ring = 144
        title_top = 24
        title_bottom = 14
        footer_pad_y = 16
    else:
        scale = 1.0
        cap = MAX_CONTENT
        gutter = 40
        header_h = 56
        ring = 144
        title_top = 24
        title_bottom = 14
        footer_pad_y = 16
    content_w = min(cap, max(280, width - 2 * gutter))
    wrap = max(200, content_w - (40 if compact else 72))
    font = {
        "hero": _px(52, scale, 32),
        "h": _px(30, scale, 20),
        "lead": _px(18, scale, 14),
        "b": _px(16, scale, 14),
        "size_big": _px(20, scale, 16),
        "s": _px(14, scale, 12),
        "tiny": _px(12, scale, 12),
        "btn": _px(16, scale, 14),
        "mono": _px(14, scale, 12),
        "mono_sm": _px(13, scale, 12),
        "entry": _px(26, scale, 18),
        "stat": _px(56, scale, 32),
        "brand": _px(16, scale, 14),
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
        font=font,
    )
