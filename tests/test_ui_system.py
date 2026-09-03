# SPDX-License-Identifier: GPL-3.0-or-later
"""Structural tests for the shared UI design system.

The Tk wizard, the web click-through, and the boot-helper page are three
renderings of one design. These tests pin the shared tokens and components
so the three cannot silently drift apart.
"""

import inspect
import re
from pathlib import Path

from beamo_wipe import copy as C
from beamo_wipe.gallery import gallery_html
from beamo_wipe.ui import tk_wizard as tkui

ROOT = Path(__file__).resolve().parents[1]

# Tokens that must render identically on every surface.
SHARED_TOKENS = (
    "BG",
    "SURFACE",
    "SURFACE_ALT",
    "INK",
    "MUTED",
    "BORDER",
    "BORDER_STRONG",
    "NAVY",
    "NAVY_SOFT",
    "NAVY_MUTED",
    "PRIMARY",
    "PRIMARY_DARK",
    "PRIMARY_TINT",
    "DANGER",
    "DANGER_TINT",
    "OK",
    "OK_TINT",
    "WARN",
    "WARN_BG",
    "FOCUS",
    "ACCENT",
    "TRACK",
)


def _css_hex(token: str) -> str:
    return getattr(tkui, token).lower()


def test_gallery_uses_the_same_color_tokens():
    html = gallery_html().lower()
    for token in SHARED_TOKENS:
        assert _css_hex(token) in html, f"gallery is missing token {token}"


def test_helper_page_uses_the_same_color_tokens():
    html = (ROOT / "helper" / "index.html").read_text(encoding="utf-8").lower()
    for token in ("BG", "SURFACE", "INK", "MUTED", "NAVY", "PRIMARY", "DANGER", "ACCENT"):
        assert _css_hex(token) in html, f"helper page is missing token {token}"


def test_every_hint_key_name_renders_as_a_key_cap():
    hints = (
        C.HINT_DEFAULT,
        C.HINT_PICK,
        C.HINT_OWNER,
        C.HINT_METHOD,
        C.HINT_CONFIRM,
        C.HINT_LAST_CHANCE,
        C.HINT_BLOCKED,
        C.HINT_DONE,
        C.HINT_SPLASH,
    )
    for hint in hints:
        for word in ("Enter", "Esc", "Space", "Up/Down", "1, 2, or 3", "any key"):
            if word in hint:
                assert tkui._KEY_TOKEN_RE.search(hint), hint
                assert word in tkui._KEY_TOKEN_RE.pattern
    # Multi-key tokens expand to individual caps in both renderers.
    assert tkui._KEY_TOKEN_KEYS["Up/Down"] == ("↑", "↓")
    assert tkui._KEY_TOKEN_KEYS["1, 2, or 3"] == ("1", "2", "3")
    html = gallery_html()
    assert "1, 2, or 3" in html and "Up/Down" in html


def test_box_component_supports_shadows_and_sync_fit():
    sig = inspect.signature(tkui._Box.__init__)
    assert "shadow" in sig.parameters
    assert "ring" in sig.parameters
    assert hasattr(tkui._Box, "fit_now")
    assert hasattr(tkui._Box, "set_focused")
    assert hasattr(tkui._Box, "set_style")


def test_button_variants_and_keyboard_activation():
    sig = inspect.signature(tkui._Button.__init__)
    assert "compact" in sig.parameters
    for variant in ("primary", "danger", "secondary", "ghost"):
        assert variant in tkui._Button._VARIANTS
    source = inspect.getsource(tkui._Button)
    assert "<FocusIn>" in source and "<FocusOut>" in source
    assert "takefocus=1" in source


def test_badge_and_status_icons_exist():
    assert callable(tkui._icon_alert)
    assert callable(tkui._icon_status)
    assert callable(tkui.TkWizard._kbd)
    assert callable(tkui.TkWizard._hint_bar)
    assert callable(tkui._icon_check_box)
    html = gallery_html()
    assert "function badge(kind" in html


def test_gallery_mirrors_wizard_components():
    html = gallery_html()
    for marker in (
        "renderHint",  # key-cap hint bar
        "entryshell",  # confirm entry shell card
        "ringwrap",  # countdown ring
        "countdownReady",
        "applyHash",  # deep links for screenshot verification
        "bootUsb",
        "moreLink",  # optional extra detail, not a new screen
    ):
        assert marker in html


def test_gallery_and_tk_share_plain_titles_and_more_detail():
    html = gallery_html()
    source = inspect.getsource(tkui.TkWizard)
    for text in (C.TITLE_WHAT, C.TITLE_OWNER, C.TITLE_PICK, C.TITLE_CONFIRM,
                 C.BTN_MORE, C.BTN_LESS, C.WHAT_LEAD, C.CONFIRM_LEAD):
        assert text in html, text
    assert "_more_link" in source
    assert "TITLE_WHAT" in source
    assert "BTN_MORE" in source
    assert "SECURE_BOOT_HINT" in source
    assert "SPLASH_META" not in source
    assert "kind_label" in inspect.getsource(tkui)


def test_gallery_step_order_matches_tk():
    html = gallery_html()
    for _screen, (_n, step, _label) in tkui._STEP_ORDER.items():
        assert step in html


def test_no_forbidden_claims_in_any_surface():
    forbidden = (
        "plug and play",
        "no technical skills",
        "military certified",
        "dod certified",
        "nsa certified",
        "blancco replacement",
        "impossible to recover",
        "we invented",
        "works on any computer",
        "works on any mac",
        "did not write",
        "beamo did not",
        "erasure engine",
    )
    surfaces = [
        gallery_html().lower(),
        (ROOT / "helper" / "index.html").read_text(encoding="utf-8").lower(),
        inspect.getsource(tkui).lower(),
    ]
    for text in surfaces:
        for phrase in forbidden:
            assert phrase not in text


def test_helper_page_renders_boot_keys_as_key_caps():
    html = (ROOT / "helper" / "index.html").read_text(encoding="utf-8")
    keys = re.findall(r'class="kbd">([^<]+)<', html)
    assert "F12" in keys and "Esc" in keys and "F9" in keys


def test_helper_page_documents_secure_boot_path():
    """The unsigned stick is refused by Secure Boot firmware, so the
    helper must tell owners how to allow it in their own settings."""
    html = (ROOT / "helper" / "index.html").read_text(encoding="utf-8").lower()
    assert "secure boot" in html
    assert "firmware" in html
    assert "disabled" in html


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(fg: str, bg: str) -> float:
    lf, lb = _luminance(fg), _luminance(bg)
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


# WCAG 2.1 AA: 4.5:1 for text, 3:1 for non-text UI (focus rings, control
# borders). The gallery and helper page share these tokens (pinned above),
# so checking the Tk palette covers all three surfaces. Many users run the
# wizard on old laptop panels in bright rooms — this bar is not negotiable.
TEXT_PAIRS = (
    ("INK", "BG"),
    ("INK", "SURFACE"),
    ("INK", "SURFACE_ALT"),
    ("INK", "PRIMARY_TINT"),
    ("MUTED", "BG"),
    ("MUTED", "SURFACE"),
    ("MUTED", "PRIMARY_TINT"),
    ("NAVY_MUTED", "NAVY"),
    ("PRIMARY", "SURFACE"),
    ("PRIMARY", "BG"),
    ("PRIMARY", "PRIMARY_TINT"),
    ("DANGER", "DANGER_TINT"),
    ("WARN", "WARN_BG"),
    ("OK", "OK_TINT"),
)
WHITE_TEXT_PAIRS = (("PRIMARY",), ("DANGER",), ("NAVY",))
NON_TEXT_PAIRS = (
    ("FOCUS", "SURFACE"),
    ("FOCUS", "BG"),
    ("BORDER_STRONG", "SURFACE"),
)


def test_text_contrast_meets_wcag_aa():
    for fg, bg in TEXT_PAIRS:
        ratio = _contrast(getattr(tkui, fg), getattr(tkui, bg))
        assert ratio >= 4.5, f"{fg} on {bg} is {ratio:.2f}:1 (< 4.5:1)"
    for (bg,) in WHITE_TEXT_PAIRS:
        ratio = _contrast("#FFFFFF", getattr(tkui, bg))
        assert ratio >= 4.5, f"white on {bg} is {ratio:.2f}:1 (< 4.5:1)"


def test_non_text_contrast_meets_wcag_aa():
    for fg, bg in NON_TEXT_PAIRS:
        ratio = _contrast(getattr(tkui, fg), getattr(tkui, bg))
        assert ratio >= 3.0, f"{fg} on {bg} is {ratio:.2f}:1 (< 3:1)"



def test_light_surfaces_do_not_wrap_the_logo_in_a_navy_tile():
    """The mark is navy-on-transparent on white chrome. Favicon may tile."""
    header = inspect.getsource(tkui.TkWizard._draw_header)
    splash = inspect.getsource(tkui.TkWizard._splash)
    assert "fill=NAVY" not in header
    assert "fill=NAVY" not in splash
    assert "_TILE_" not in inspect.getsource(tkui.TkWizard)
    html = gallery_html()
    brandchip = re.search(r"\.brandchip\s*\{[^}]+\}", html)
    marktile = re.search(r"\.marktile\s*\{[^}]+\}", html)
    assert brandchip and "background: var(--navy)" not in brandchip.group(0)
    assert marktile and "background: var(--navy)" not in marktile.group(0)
    # Inline splash/header marks use navy B; the favicon keeps a navy tile.
    from beamo_wipe import gallery as G
    assert 'fill="#0A1B34"' in html
    assert 'rx="14" fill="#0A1B34"' in inspect.getsource(G._favicon_uri)
    helper = (ROOT / "helper" / "index.html").read_text(encoding="utf-8")
    chip = re.search(r"header \.brandchip\s*\{[^}]+\}", helper)
    assert chip and "background: var(--navy)" not in chip.group(0)


def test_logo_pngs_are_rgba_with_alpha():
    import struct

    for name, min_w, min_h in (("logo-header.png", 32, 24), ("logo-splash.png", 64, 48)):
        data = (ROOT / "src" / "beamo_wipe" / "assets" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[12:16] == b"IHDR"
        width, height, _bit, color = struct.unpack(">IIBB", data[16:26])
        assert width >= min_w and height >= min_h
        assert color == 6  # RGBA — not an opaque black rectangle
