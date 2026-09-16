# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #73: wording before refresh, with no reset until confirmed."""

from beamo_wipe import copy as C
from beamo_wipe.gallery import gallery_html
from beamo_wipe.models import MethodId, Screen
from beamo_wipe.ui import console_wizard as console
from test_refresh_disks import authorized


def _state(wiz):
    return (
        wiz.screen,
        wiz.selected.path if wiz.selected else None,
        wiz.owner_ok,
        wiz.confirm_input,
        wiz.method,
        wiz._erase_until,
    )


def test_refresh_copy_names_every_cleared_item():
    """Would fail when F5 had no pre-activation explanation."""
    text = " ".join((C.TITLE_REFRESH, C.REFRESH_LEAD)).lower()
    for phrase in (
        "selected disk",
        "ownership",
        "typed",
        "method",
        "countdown",
        "beginning",
    ):
        assert phrase in text, phrase
    html = gallery_html()
    assert C.TITLE_REFRESH in html
    assert C.REFRESH_LEAD in html


def test_open_refresh_confirm_does_not_clear_authorization():
    wiz = authorized()
    before = _state(wiz)
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.open_refresh_confirm() is True
    assert wiz.screen == Screen.REFRESH_CONFIRM
    assert _state(wiz)[1:] == before[1:]
    assert wiz.selected is not None
    assert wiz.owner_ok
    assert wiz.confirm_input
    assert wiz.method == MethodId.QUICK_ZERO
    assert wiz._erase_until == 0
    assert not wiz.runner.started


def test_cancel_refresh_confirm_keeps_authorization_and_screen():
    wiz = authorized()
    path = wiz.selected.path
    assert wiz.open_refresh_confirm() is True
    wiz.back()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.selected.path == path
    assert wiz.owner_ok
    assert wiz.confirm_input
    assert wiz.method == MethodId.QUICK_ZERO
    assert wiz._erase_until == 0
    assert not wiz.runner.started


def test_confirm_refresh_resets_and_returns_to_preparation():
    wiz = authorized()
    assert wiz.open_refresh_confirm() is True
    assert wiz.confirm_refresh() is True
    assert wiz.screen == Screen.WHAT
    assert wiz.selected is None
    assert not wiz.owner_ok
    assert wiz.confirm_input == ""
    assert wiz.method == MethodId.EVERYDAY
    assert wiz._erase_until is None
    wiz.confirm_erase()
    assert not wiz.runner.started
    wiz.accept_what()
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER


def test_confirm_refresh_refused_until_wording_is_shown():
    wiz = authorized()
    assert wiz.confirm_refresh() is False
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.selected is not None
    assert wiz.owner_ok


def test_repeated_refresh_shows_wording_again():
    wiz = authorized()
    assert wiz.open_refresh_confirm()
    assert wiz.confirm_refresh()
    assert wiz.screen == Screen.WHAT
    assert wiz.open_refresh_confirm()
    assert wiz.screen == Screen.REFRESH_CONFIRM
    wiz.back()
    assert wiz.screen == Screen.WHAT
    assert wiz.selected is None and not wiz.owner_ok


def test_failed_confirm_refresh_leaves_no_stale_target():
    wiz = authorized()

    def boom():
        raise RuntimeError("fake failure")

    wiz._rediscover = boom
    assert wiz.open_refresh_confirm()
    assert wiz.confirm_refresh()
    assert wiz.screen == Screen.PICK_BLOCKED
    assert wiz.selected is None
    assert not wiz.owner_ok
    assert not wiz.selectable
    assert not wiz.erase_enabled


def test_console_refresh_hint_explains_the_reset():
    wiz = authorized()
    extra = " ".join(console._chrome_extra(wiz))
    assert "Check disks again" in extra
    assert "clears preparation" in extra.lower()
    wiz.open_refresh_confirm()
    footer = " ".join(console._primary_footer(wiz, False))
    assert "keep" in footer.lower()
    assert C.TITLE_REFRESH
