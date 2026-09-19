# SPDX-License-Identifier: GPL-3.0-or-later
"""Window-size layout breakpoints. No display. Fake geometry only."""

from beamo_wipe.ui.layout import (
    DEFAULT_SIZE,
    LARGE_SIZE,
    MIN_SIZE,
    NETBOOK_SIZE,
    SUPPORTED_SIZE,
    layout_for,
)


def test_user_text_size_scales_fonts_not_window_geometry():
    """Would fail when type was locked to DPI scaling 1.0 with no user size."""
    standard = layout_for(1280, 820, "standard")
    extra = layout_for(1280, 820, "extra")
    bogus = layout_for(1280, 820, "huge")
    compact_extra = layout_for(800, 600, "extra")
    assert extra.font["h"] > standard.font["h"]
    assert extra.font["s"] > standard.font["s"]
    assert extra.font["btn"] > standard.font["btn"]
    assert extra.content_w == standard.content_w
    assert extra.header_h >= standard.header_h
    assert extra.wrap == standard.wrap
    assert extra.ring > standard.ring
    assert extra.stack_review
    assert extra.type_scale == 1.35
    assert extra.text_size == "extra"
    assert bogus.text_size == "standard"
    assert compact_extra.font["tiny"] >= 12
    assert compact_extra.font["btn"] >= 14


def test_minimum_is_800x600():
    assert MIN_SIZE == (800, 600)
    lay = layout_for(*MIN_SIZE)
    assert lay.compact and lay.short and lay.narrow
    assert lay.content_w <= 800 - 32
    assert lay.wrap <= lay.content_w
    assert lay.font["tiny"] >= 12
    assert lay.font["btn"] >= 14
    assert lay.font["b"] >= 14
    assert lay.stack_review
    assert lay.ring <= 96


def test_netbook_1024x600_is_short_not_narrow():
    lay = layout_for(*NETBOOK_SIZE)
    assert lay.short and not lay.narrow
    assert lay.compact
    assert lay.content_w <= 1024
    assert lay.stack_review


def test_supported_1024x740_is_full_layout():
    lay = layout_for(*SUPPORTED_SIZE)
    assert not lay.compact
    assert not lay.short
    assert lay.scale == 1.0
    assert lay.content_w == 940
    assert not lay.stack_review


def test_large_window_enlarges_type_without_dpi():
    compact = layout_for(*MIN_SIZE)
    normal = layout_for(*DEFAULT_SIZE)
    large = layout_for(*LARGE_SIZE)
    assert compact.font["h"] < normal.font["h"] < large.font["h"]
    assert compact.scale < normal.scale < large.scale
    assert large.scale <= 1.2
    assert large.content_w >= normal.content_w
    assert large.wrap >= 200


def test_type_scale_grows_type_not_column_width():
    """Would fail when enlarged type used a fixed wrap and 64px ring."""
    base = layout_for(1024, 740, "standard")
    large = layout_for(1024, 740, "extra")
    assert large.font["h"] > base.font["h"]
    assert large.font["s"] > base.font["s"]
    assert large.content_w == base.content_w
    assert large.wrap == base.wrap
    assert large.ring > base.ring
    assert large.stack_review
    assert large.type_scale == 1.35
    assert layout_for(1024, 740, "huge").type_scale == 1.0
    assert layout_for(1024, 740, "huge").text_size == "standard"


def test_gallery_cards_and_footer_reflow():
    from beamo_wipe.gallery import gallery_html

    html = gallery_html()
    assert "overflow-wrap: anywhere" in html
    assert ".footrow" in html and "flex-wrap: wrap" in html


def test_wrap_never_exceeds_window():
    for size in (MIN_SIZE, NETBOOK_SIZE, SUPPORTED_SIZE, DEFAULT_SIZE, LARGE_SIZE, (640, 480)):
        lay = layout_for(*size)
        assert lay.wrap <= lay.width
        assert lay.content_w <= lay.width
        assert lay.wrap <= lay.content_w
