# SPDX-License-Identifier: GPL-3.0-or-later
"""Tk setup choices must be reachable without a pointer."""

import inspect
from types import SimpleNamespace

from beamo_wipe.ui.tk_wizard import TkWizard


def test_setup_layout_and_language_cards_are_keyboard_controls():
    source = inspect.getsource(TkWizard._keyboard)
    assert 'card.configure(cursor="hand2", takefocus=1)' in source
    assert 'chip.configure(cursor="hand2", takefocus=1)' in source
    assert 'card.bind("<space>"' in source
    assert 'card.bind("<Return>"' in source
    assert 'chip.bind("<space>"' in source
    assert 'chip.bind("<Return>"' in source


def test_setup_choice_claims_one_physical_key_press():
    app = object.__new__(TkWizard)
    activations = []
    app._claim_space_press = lambda event: event.time == 1
    app._claim_return_press = lambda event: event.time == 3
    for keysym, when in (("space", 1), ("space", 2), ("Return", 3), ("Return", 4)):
        app._keyboard_option_key(
            SimpleNamespace(keysym=keysym, time=when),
            activate=lambda: activations.append((keysym, when)),
        )
    assert activations == [("space", 1), ("Return", 3)]
