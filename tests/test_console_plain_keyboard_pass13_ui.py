"""The plain TTY fallback keeps the keyboard utility reachable later."""

import pytest
from types import SimpleNamespace

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import ConfirmSpec, Screen
from beamo_wipe.ui import console_wizard as console


def _at_confirm():
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    assert wizard.screen == Screen.CONFIRM
    return wizard


@pytest.mark.parametrize("command", ["K", "KEYBOARD"])
def test_plain_prompt_can_reopen_keyboard_from_confirm(monkeypatch, command):
    wizard = _at_confirm()
    monkeypatch.setattr("builtins.input", lambda _prompt: command)

    with pytest.raises(console._InventoryRefreshed):
        console._answer(wizard, "Input: ")
    assert wizard.screen == Screen.KEYBOARD

    wizard.accept_keyboard()
    assert wizard.screen == Screen.CONFIRM
    assert not wizard.token_ok


def test_plain_keyboard_utility_returns_to_last_chance_with_new_countdown(monkeypatch):
    wizard = _at_confirm()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    assert wizard.screen == Screen.LAST_CHANCE
    later = wizard.now + 6.0
    wizard._clock = lambda: later
    assert wizard.erase_enabled
    monkeypatch.setattr("builtins.input", lambda _prompt: "K")

    with pytest.raises(console._InventoryRefreshed):
        console._answer(wizard, "Erase? ")
    assert wizard.screen == Screen.KEYBOARD
    wizard.accept_keyboard()
    assert wizard.screen == Screen.LAST_CHANCE
    assert wizard.countdown_left == pytest.approx(5.0)
    assert not wizard.erase_enabled


@pytest.mark.parametrize("token", ["K", "KEYBOARD"])
def test_plain_keyboard_shortcuts_do_not_steal_exact_confirm_token(monkeypatch, capsys, token):
    wizard = SimpleNamespace(
        screen=Screen.CONFIRM,
        can_open_keyboard=True,
        can_refresh=False,
        can_open_diagnostic=False,
        can_open_report_help=False,
        confirm=ConfirmSpec(token=token, prompt="Type token"),
    )
    opened = []
    wizard.open_keyboard = lambda: opened.append(True)
    monkeypatch.setattr("builtins.input", lambda _prompt: token)

    assert console._answer(wizard, "Input: ") == token
    assert not opened
    hint = capsys.readouterr().out
    assert "CHANGE KEYBOARD: Keyboard layout" in hint
    assert "K: Keyboard layout" not in hint

    monkeypatch.setattr("builtins.input", lambda _prompt: "CHANGE KEYBOARD")
    with pytest.raises(console._InventoryRefreshed):
        console._answer(wizard, "Input: ")
    assert opened == [True]


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("fr", "CHANGE KEYBOARD : Disposition du clavier"),
        ("de", "CHANGE KEYBOARD: Tastaturlayout"),
    ],
)
def test_plain_keyboard_collision_hint_uses_chosen_language(
    monkeypatch, capsys, language, expected
):
    from beamo_wipe import lang

    wizard = SimpleNamespace(
        screen=Screen.CONFIRM,
        can_open_keyboard=True,
        can_refresh=False,
        can_open_diagnostic=False,
        can_open_report_help=False,
        confirm=ConfirmSpec(token="K", prompt="Type token"),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "K")
    lang.set_language(language)
    try:
        assert console._answer(wizard, "Input: ") == "K"
        assert expected in capsys.readouterr().out
    finally:
        lang.set_language("en")
