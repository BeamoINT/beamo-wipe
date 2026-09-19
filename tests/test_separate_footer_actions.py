# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #82: primary navigation stays a consistent row; assist is separate.

These source pins fail on origin/main edd2da3, where _footer_shell still
packs a mid filler between Back and the primary action. Runtime geometry
needs a display.
"""

import inspect
import re

import pytest

from beamo_wipe import copy as C
from beamo_wipe.gallery import gallery_html
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.ui.tk_wizard import TkWizard
from test_tk_runtime import ui  # noqa: F401


def test_tk_footer_keeps_hints_out_of_the_action_row():
    """Would fail when _footer_shell packed hints into mid between left/right."""
    source = inspect.getsource(TkWizard._footer_shell)
    assert "mid.pack(fill=tk.BOTH, expand=True)" not in source
    assert "_hint_bar(mid" not in source
    assert "assist" in source
    for marker in (
        "BTN_ADVANCED",
        "KEYBOARD_UTILITY",
        "BTN_REFRESH_UTILITY",
        "REPORT_HELP_TITLE",
        "SCREEN_READER_VIEW",
        "DIAGNOSTIC_TITLE",
        "ANOTHER_HINT",
    ):
        assert marker in source, marker


def test_gallery_hint_lives_in_assist_not_action_row():
    """Would fail when #hint sat between #btnsL and #btnsR inside .footrow."""
    html = gallery_html()
    assert 'id="hint"' in html
    assert "role=\"region\"" in html
    assert C.ASSIST_LABEL in html
    assert C.NAV_LABEL in html
    assist_html = html.split('class="assist"', 1)[1].split("class=\"footrow\"", 1)[0]
    assert 'id="hint"' in assist_html
    assert 'id="utilities"' in assist_html
    footrow_html = html.split("class=\"footrow\"", 1)[1]
    assert 'id="hint"' not in footrow_html.split("</div></div></div>", 1)[0]
    assert 'id="btnsL"' in footrow_html
    assert 'id="btnsR"' in footrow_html
    assert re.search(r"\.footrow\s*\{[^}]*justify-content:\s*space-between", html)
    assert ".fhint { order: 3" not in html
    assert "utilities.prepend(btn(P.buttons.advanced" in html
    assert 'id="adv"' not in html
    # Recovery/support chrome on main stays in the gallery body, not flattened.
    assert "stop_confirm" in html
    assert "shutdown_confirm" in html
    assert "refresh_confirm" in html
    assert "class=\"recovery\"" in html or ".recovery {" in html


def test_gtk_names_assist_and_navigation_separately():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "beamo_wipe"
        / "ui"
        / "accessible_wizard.py"
    ).read_text(encoding="utf-8")
    assert "ASSIST_LABEL" in source
    assert "NAV_LABEL" in source
    assert "Atk.Role.PANEL" in source


def test_assist_nav_names_do_not_rewrite_result_heading():
    """Would fail if footer grouping ATK names prefixed the result heading."""
    from gi.repository import Atk

    from beamo_wipe.ui.accessible_wizard import AccessibleWizard
    from test_accessible_runtime import drain, widgets
    from test_result_presentations import CASES, case_evidence

    wizard, _, _ = case_evidence(CASES[1])
    app = AccessibleWizard(wizard)
    try:
        app.window.resize(800, 600)
        drain()
        expected = wizard.result_view.announcement
        names = [w.get_accessible().get_name() for w in widgets(app.window)]
        assert expected in names
        assert C.NAV_LABEL in names
        headings = [
            w.get_accessible().get_name()
            for w in widgets(app.window)
            if w.get_accessible().get_role() == Atk.Role.HEADING
        ]
        assert headings[0] == expected
        assert not headings[0].startswith(C.NAV_LABEL)
        assert not headings[0].startswith(C.ASSIST_LABEL)
    finally:
        app.close()
        drain()


def test_console_keeps_extra_chrome_off_the_primary_action_line():
    extra = inspect.getsource(console._chrome_extra)
    primary = inspect.getsource(console._primary_footer)
    lines = inspect.getsource(console._footer_lines)
    assert "CON_DIAGNOSTIC" in extra
    assert "REFRESH_UTILITY_NOTE" in extra
    assert "CON_LAST_ERASE" in primary
    assert "_primary_footer" in lines and "_chrome_extra" in lines
    assert "extra_shown + assist_shown + actions" in lines


@pytest.mark.parametrize("size", [(1280, 820), (1024, 740), (800, 600)])
def test_last_chance_hint_is_above_navigation_not_between_actions(ui, size):  # noqa: F811
    """Would fail at 1280×820 when hints sat between Back and Erase now."""
    from beamo_wipe.ui.tk_wizard import _Button
    from test_tk_runtime import _button_named, _drive_to

    wiz, app = ui(size=size)
    _drive_to(wiz, app, Screen.LAST_CHANCE, size=size)
    wiz._erase_until = 0
    app._refresh_last_chance()
    for _ in range(5):
        app.root.update()
    back = _button_named(app, C.BTN_BACK)
    erase = _button_named(app, C.BTN_ERASE)
    hint = app._hint
    assert hint is not None and hint.winfo_ismapped()
    assert back.winfo_ismapped() and erase.winfo_ismapped()
    assert app.root.focus_get() is back
    nxt = back.tk_focusNext()
    assert nxt is erase
    hint_bottom = hint.winfo_rooty() + hint.winfo_height()
    nav_top = min(back.winfo_rooty(), erase.winfo_rooty())
    assert hint_bottom <= nav_top + 2
    assert abs(back.winfo_rooty() - erase.winfo_rooty()) <= 4
    nav_y = back.winfo_rooty()
    nav_bottom = nav_y + back.winfo_height()
    overlapping = []
    stack = list(app._footer.winfo_children())
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        if not isinstance(widget, _Button) or widget in (back, erase):
            continue
        if not widget.winfo_ismapped():
            continue
        top, bottom = widget.winfo_rooty(), widget.winfo_rooty() + widget.winfo_height()
        if top < nav_bottom and bottom > nav_y:
            overlapping.append(widget.itemcget(widget._label, "text"))
    assert overlapping == []


def test_method_assist_keeps_advanced_refresh_and_report_help(ui):  # noqa: F811
    from test_tk_runtime import _button_named, _drive_to

    wiz, app = ui()
    _drive_to(wiz, app, Screen.METHOD)
    app.root.update()
    advanced = _button_named(app, C.BTN_ADVANCED)
    refresh = _button_named(app, C.BTN_REFRESH_UTILITY)
    report = _button_named(app, C.REPORT_HELP_TITLE)
    back = _button_named(app, C.BTN_BACK)
    primary = app._primary
    assert primary is not None
    for control in (advanced, refresh, report):
        assert control.winfo_ismapped()
        assert control.winfo_rooty() + control.winfo_height() <= back.winfo_rooty() + 2
    nxt = back.tk_focusNext()
    assert nxt is primary
