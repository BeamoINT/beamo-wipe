# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #79: session text size, not DPI scaling."""

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.gallery import gallery_html
from beamo_wipe.models import MethodId, Screen
from test_refresh_disks import authorized


def test_text_size_default_and_rejects_unknown():
    wiz = make_demo_wizard()
    assert wiz.text_size == "standard"
    assert wiz.text_scale == 1.0
    assert wiz.set_text_size("huge") is False
    assert wiz.text_size == "standard"
    assert wiz.set_text_size("extra") is True
    assert wiz.text_size == "extra"
    assert wiz.text_scale > 1.0
    assert wiz.cycle_text_size() == "standard"


def test_text_size_survives_refresh_and_keyboard_layout():
    wiz = authorized()
    assert wiz.set_text_size("large")
    wiz.set_keyboard_layout("fr")
    assert wiz.text_size == "large"
    assert wiz.open_refresh_confirm()
    assert wiz.confirm_refresh()
    assert wiz.screen == Screen.OWNER and not wiz.owner_ok
    assert wiz.text_size == "large"
    assert wiz.method == MethodId.EVERYDAY
    assert wiz.selected is None
    wiz.reset_for_preview()
    assert wiz.text_size == "standard"
    assert wiz.text_scale == 1.0


def test_gallery_offers_early_text_size():
    html = gallery_html()
    assert C.TEXT_SIZE_LEAD in html
    assert C.TEXT_SIZE_STANDARD in html
    assert C.TEXT_SIZE_LARGE in html
    assert C.TEXT_SIZE_EXTRA in html
    assert "data-text" in html
    assert "textSizes" in html


def test_tk_still_pins_dpi_scaling():
    import inspect
    from beamo_wipe.ui import tk_wizard as tkui

    src = inspect.getsource(tkui.TkWizard.__init__)
    assert 'tk.call("tk", "scaling", 1.0)' in src
    assert "_apply_text_size" in inspect.getsource(tkui.TkWizard)
    keyboard = inspect.getsource(tkui.TkWizard._keyboard)
    assert "TEXT_SIZE_LEAD" in keyboard
    assert "TEXT_SIZE_LABELS" in keyboard
