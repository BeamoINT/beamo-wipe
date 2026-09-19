# SPDX-License-Identifier: GPL-3.0-or-later
"""Primary actions name the next step. They never claim the erase started.

Fake disks only.
"""

from __future__ import annotations

import inspect

from beamo_wipe import copy as C
from beamo_wipe.gallery import gallery_html
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.ui import tk_wizard as tkui
from test_tk_runtime import ui, _drive_to, _button_named  # noqa: F401


def test_happy_path_primaries_name_the_next_action_not_continue():
    assert C.primary_action(Screen.PICK) == "Review this disk"
    assert C.primary_action(Screen.CONFIRM) == "Choose erase method"
    assert C.primary_action(Screen.METHOD) == "Review before erasing"
    assert C.primary_action(Screen.OWNER) == "Choose a disk"
    assert C.primary_action(Screen.WHAT) == C.BTN_UNDERSTAND
    for screen in (Screen.OWNER, Screen.PICK, Screen.CONFIRM, Screen.METHOD):
        label = C.primary_action(screen)
        assert label != C.BTN_CONTINUE
        assert label != C.BTN_ERASE
        assert "now" not in label.lower()
        assert "finished" not in label.lower()
        assert "done" not in label.lower()
    assert C.BTN_ERASE == "Erase now"
    assert C.primary_action(Screen.LAST_CHANCE) == C.BTN_CONTINUE  # last chance uses Erase now, not this helper
    assert C.primary_action(Screen.KEYBOARD) == C.BTN_CONTINUE
    assert C.primary_action(Screen.SPLASH) == C.BTN_CONTINUE


def test_tk_gallery_console_share_the_descriptive_labels():
    tk_src = inspect.getsource(tkui.TkWizard)
    assert "primary_action" in tk_src
    html = gallery_html()
    for label in (
        C.BTN_CHOOSE_DISK,
        C.BTN_REVIEW_DISK,
        C.BTN_CHOOSE_METHOD,
        C.BTN_REVIEW_ERASE,
        C.BTN_RETURN_METHODS,
    ):
        assert label in html
    assert "P.buttons.reviewDisk" in html
    assert "P.buttons.chooseMethod" in html
    assert "P.buttons.reviewErase" in html
    console_src = inspect.getsource(console)
    assert "CON_PICK_NAV" in console_src
    assert "CON_METHOD_FOOTER" in console_src
    assert "CON_CONFIRM_FOOTER" in console_src
    assert "reviews this disk" in C.CON_PICK_NAV.lower()
    assert "review before erasing" in C.CON_METHOD_FOOTER.lower()
    assert "choose erase method" in C.CON_CONFIRM_FOOTER.lower()


def test_descriptive_labels_fit_footer_and_do_not_replace_erase_now():
    assert len(C.BTN_REVIEW_ERASE) <= 24
    assert len(C.BTN_CHOOSE_METHOD) <= 24
    assert len(C.BTN_REVIEW_DISK) <= 24
    assert len(C.BTN_CHOOSE_DISK) <= 24
    assert C.BTN_REVIEW_ERASE != C.BTN_ERASE
    last = inspect.getsource(tkui.TkWizard._last)
    assert "BTN_ERASE" in last
    assert "BTN_REVIEW_ERASE" not in last


def test_rendered_pick_confirm_method_show_next_actions(ui):  # noqa: F811
    wiz, app = ui(size=(1280, 820))
    _drive_to(wiz, app, Screen.PICK)
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    app._draw()
    app.root.update()
    assert _button_named(app, C.BTN_REVIEW_DISK)._enabled
    wiz.continue_pick()
    app._draw()
    app.root.update()
    confirm = _button_named(app, C.BTN_CHOOSE_METHOD)
    assert not confirm._enabled
    wiz.set_confirm_input(wiz.confirm.token)
    app._confirm_var.set(wiz.confirm.token)
    app._draw()
    app.root.update()
    assert _button_named(app, C.BTN_CHOOSE_METHOD)._enabled
    wiz.continue_confirm()
    app._draw()
    app.root.update()
    assert _button_named(app, C.BTN_REVIEW_ERASE)._enabled
