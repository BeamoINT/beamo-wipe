# SPDX-License-Identifier: GPL-3.0-or-later
"""Combined intro: splash + explanation on the ownership screen.

Fake disks only. Ownership stays explicit, informed, and required.

Baseline (before combining), production first-run actions after splash:
  KEYBOARD Continue, WHAT "I understand", OWNER checkbox, OWNER Continue
  = 3 primary clicks + 1 mandatory check. WHAT was a separate screen.

After: KEYBOARD Continue, combined OWNER (explanation + checkbox + Continue)
  = 2 primary clicks + 1 mandatory check. Splash still auto-advances.
  Keyboard layout stays its own screen. Ownership cannot be skipped.
"""

from __future__ import annotations

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.gallery import gallery_html
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


def _intro():
    wiz = make_demo_wizard()
    wiz.skip_intro()
    return wiz


def test_skip_intro_lands_on_combined_owner_not_a_separate_what_screen():
    wiz = _intro()
    assert wiz.screen == Screen.OWNER
    assert wiz.screen != Screen.WHAT
    assert not wiz.owner_ok


def test_accept_what_does_not_skip_the_ownership_checkbox():
    wiz = _intro()
    wiz.accept_what()
    assert wiz.screen == Screen.OWNER
    assert not wiz.owner_ok
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
    assert not wiz.runner.started


def test_continue_requires_checked_ownership_after_reading_the_explanation():
    wiz = _intro()
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
    wiz.set_owner(True)
    assert wiz.owner_ok
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    assert not wiz.runner.started


def test_unchecking_blocks_continue_again():
    wiz = _intro()
    wiz.set_owner(True)
    wiz.set_owner(False)
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
    assert not wiz.runner.started


def test_back_from_pick_returns_to_owner_and_clears_nothing_unsafe():
    wiz = _intro()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    wiz.back()
    assert wiz.screen == Screen.OWNER
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK


def test_back_from_owner_returns_to_keyboard_not_a_what_screen():
    wiz = _intro()
    wiz.back()
    assert wiz.screen == Screen.KEYBOARD
    wiz.accept_keyboard()
    assert wiz.screen == Screen.OWNER
    assert not wiz.owner_ok


def test_refresh_returns_to_combined_intro_and_clears_ownership():
    wiz = _intro()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    assert wiz.refresh_disks()
    assert wiz.screen == Screen.OWNER
    assert not wiz.owner_ok
    assert wiz.selected is None
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER


def test_plain_console_owner_prints_explanation_and_requires_yes(monkeypatch, capsys):
    wiz = _intro()
    answers = iter(["no", "YES"])

    def fake_input(_prompt=""):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wiz)
    output = capsys.readouterr().out
    for bullet in C.WHAT_BULLETS:
        assert bullet[:40] in output.replace("\n", " ") or bullet in output
    assert C.OWNER_CHECKBOX in output
    assert C.SPLASH_TAGLINE in output or C.WHAT_LEAD in output
    assert wiz.screen == Screen.PICK
    assert wiz.owner_ok
    assert not wiz.runner.started


def test_keyboard_continue_opens_combined_owner_not_what():
    wiz = make_demo_wizard()
    wiz.skip_splash()
    assert wiz.screen == Screen.KEYBOARD
    wiz.accept_keyboard()
    assert wiz.screen == Screen.OWNER
    assert not wiz.owner_ok
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER


def test_gallery_owner_includes_explanation_and_requires_checkbox():
    html = gallery_html()
    assert C.TITLE_OWNER in html
    assert C.TITLE_WHAT in html
    assert C.WHAT_LEAD in html
    for bullet in C.WHAT_BULLETS:
        assert bullet in html
    assert C.OWNER_CHECKBOX in html
    assert C.POWER_REMINDER in html
    assert 'screen = "owner"' in html
    assert "btnsR.append(btn(P.buttons.continue, () => { screen = \"what\"" not in html
    assert "btnsR.append(btn(P.buttons.understand" not in html
    assert C.JOURNEY_LABELS[0] == "Owner"
    assert len(C.JOURNEY_LABELS) == 7
    assert "Step 1 of 7" in html
    assert "Step 1 of 8" not in html


def test_first_run_drops_the_understand_click_but_not_the_checkbox():
    """Measurable action count: skip_intro + check + continue reaches pick."""
    wiz = _intro()
    assert wiz.screen == Screen.OWNER
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK


def test_what_enum_still_exists_for_compat():
    assert Screen.WHAT.value == "what"
    wiz = _intro()
    wiz.screen = Screen.WHAT
    wiz.accept_what()
    assert wiz.screen == Screen.OWNER
    assert not wiz.owner_ok
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER
