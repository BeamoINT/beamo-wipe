# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #83: spacing follows task density.

These pins fail on origin/main 60d827a, where introductions use a 24px
title pad and the result screen is vertically centered.
"""

import inspect
import re

from beamo_wipe import copy as C
from beamo_wipe.gallery import gallery_html
from beamo_wipe.ui.layout import DEFAULT_SIZE, LARGE_SIZE, MIN_SIZE, layout_for
from beamo_wipe.ui.tk_wizard import TkWizard


def test_default_title_rhythm_leaves_less_unused_intro_space():
    """Would fail when default title_top was 24px."""
    lay = layout_for(*DEFAULT_SIZE)
    assert lay.title_top <= 16
    assert lay.title_bottom <= 10
    compact = layout_for(*MIN_SIZE)
    assert compact.title_top <= 8
    assert compact.title_bottom <= 6
    large = layout_for(*LARGE_SIZE)
    assert large.title_top <= 18
    assert compact.title_top < lay.title_top


def test_result_is_top_aligned_not_vertically_centered():
    """Would fail when _done packed expanding spacers above and below."""
    source = inspect.getsource(TkWizard._done)
    assert "tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)" not in source
    # #95: the Done heading is the outcome message, not a generic title.
    assert "title = result.message" in source
    assert "ERASE_STATUS_TITLE" not in source
    assert "REPORT_STATUS_TITLE" in source
    assert "_disk_summary" in source
    splash = inspect.getsource(TkWizard._splash)
    assert "tk.Frame(col, bg=BG).pack(fill=tk.BOTH, expand=True)" in splash
    html = gallery_html()
    assert ".result " in html or ".result{" in html
    assert "justify-content: center" in html  # blocked/empty/splash keep it
    done_html = html.split('screen === "done"')[1].split("} else if")[0]
    assert "centerstage" not in done_html
    assert done_html.find("summaryCard") < done_html.find("report-status-heading")


def test_method_cards_are_a_tighter_choice_group():
    """Would fail when method cards used 10px gaps and 12px inner pad."""
    source = inspect.getsource(TkWizard._method_card)
    assert "pady=(0, 6)" in source
    assert "pady=8" in source
    html = gallery_html()
    assert "margin-bottom:6px" in html


def test_report_help_sections_have_scan_headings():
    """Would fail when report help was six unlabeled paragraphs."""
    headings = (
        "What you need",
        "When to insert the report USB",
        "If the report USB is already plugged in",
        "What the report contains",
        "Removing the report USB",
        "If the wipe cannot start",
        "Saving in stages",
    )
    assert len(C.REPORT_HELP_SECTIONS) == len(headings)
    for heading, section in zip(headings, C.REPORT_HELP_SECTIONS):
        assert section.startswith(heading)
        assert "\n" in section
        body = section.split("\n", 1)[1]
        assert len(body) > 40
    html = gallery_html()
    assert "What you need" in html
    assert "FAT32" in html
    assert "Diagnostic report" in C.REPORT_HELP_TEXT


def _rule_padding(html, selector):
    match = re.search(
        re.escape(selector) + r" \{[^}]*?padding: (\d+)px (\d+)px;", html
    )
    assert match, f"missing padded rule for {selector}"
    return int(match.group(1)), int(match.group(2))


def test_gallery_selected_states_keep_box_size_stable():
    """Selected/checked rules must shrink padding to offset the 2px border.

    Would fail when .card.sel kept 15/19px against the tighter 14/18px
    base, growing picked cards by a step on selection.
    """
    html = gallery_html()
    for base, active in ((".card", ".card.sel"),
                         (".ownercard", ".ownercard.checked")):
        base_pad = _rule_padding(html, base)
        active_pad = _rule_padding(html, active)
        assert base_pad[0] - active_pad[0] == 1
        assert base_pad[1] - active_pad[1] == 1
