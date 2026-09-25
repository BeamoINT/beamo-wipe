# SPDX-License-Identifier: GPL-3.0-or-later
"""A real disk confirmation token must win over plain-console utilities."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.safety import confirm_spec
from beamo_wipe.ui import console_wizard as console


@pytest.mark.parametrize("token", ["REPORT", "DIAGNOSTIC"])
def test_plain_confirm_accepts_token_matching_utility_word(monkeypatch, token):
    demo = make_demo_wizard()
    target = demo.selectable[0]
    peer = next(d for d in demo.selectable if d.path != target.path and d.size_gb_label == target.size_gb_label)
    target = replace(target, serial=token, wwn="")
    peer = replace(peer, serial=token[-4:], wwn="")
    # A same-size peer can force a legitimate full-serial token. The prompt
    # must accept it even when it names a utility command.
    spec = confirm_spec(target, [target, peer])
    assert spec.token == token
    wizard = SimpleNamespace(
        screen=Screen.CONFIRM,
        confirm=spec,
        can_open_keyboard=False,
        can_open_report_help=True,
        can_open_diagnostic=True,
        can_refresh=False,
    )
    opened = []
    wizard.open_report_help = lambda: opened.append("report")
    wizard.open_diagnostic = lambda: opened.append("diagnostic")
    monkeypatch.setattr("builtins.input", lambda _prompt: token)

    assert console._answer(wizard, "Input: ") == token
    assert opened == []
