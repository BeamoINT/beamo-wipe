"""A held key must not repeatedly change Tk report preferences."""

from types import SimpleNamespace

import pytest

from beamo_wipe.ui.tk_wizard import TkWizard, _CheckRow


@pytest.mark.parametrize("keysym", ["space", "Return", "KP_Enter"])
def test_checkrow_held_key_toggles_once(keysym):
    class App:
        _key_event_time = staticmethod(TkWizard._key_event_time)
        _space_held = False
        _space_release_after = None
        _space_release_time = None
        _return_held = False
        _return_release_after = None
        _return_release_time = None

        def _claim_space_press(self, event):
            return TkWizard._claim_space_press(self, event)

        def _claim_return_press(self, event):
            return TkWizard._claim_return_press(self, event)

    app = App()
    root = SimpleNamespace(_tk_wizard=app)
    toggles = []
    row = SimpleNamespace(
        winfo_toplevel=lambda: root,
        invoke=lambda: toggles.append(True),
    )
    event = SimpleNamespace(keysym=keysym, time=100)

    assert _CheckRow._activate(row, event) == "break"
    assert _CheckRow._activate(row, event) == "break"
    assert toggles == [True]


@pytest.mark.parametrize("keysym,held,release_time", [
    ("space", "_space_held", "_space_release_time"),
    ("Return", "_return_held", "_return_release_time"),
])
def test_checkrow_x11_release_press_pair_does_not_toggle(keysym, held, release_time):
    class App:
        _key_event_time = staticmethod(TkWizard._key_event_time)
        _space_held = False
        _space_release_after = None
        _space_release_time = None
        _return_held = False
        _return_release_after = None
        _return_release_time = None

        def _claim_space_press(self, event):
            return TkWizard._claim_space_press(self, event)

        def _claim_return_press(self, event):
            return TkWizard._claim_return_press(self, event)

    app = App()
    setattr(app, held, False)
    setattr(app, release_time, 100)
    toggles = []
    row = SimpleNamespace(
        winfo_toplevel=lambda: SimpleNamespace(_tk_wizard=app),
        invoke=lambda: toggles.append(True),
    )

    assert _CheckRow._activate(row, SimpleNamespace(keysym=keysym, time=100)) == "break"
    assert toggles == []


@pytest.mark.parametrize("keysym,held,release_time", [
    ("space", "_space_held", "_space_release_time"),
    ("Return", "_return_held", "_return_release_time"),
])
def test_checkrow_new_physical_press_can_toggle_again(keysym, held, release_time):
    class App:
        _key_event_time = staticmethod(TkWizard._key_event_time)
        _space_held = False
        _space_release_after = None
        _space_release_time = None
        _return_held = False
        _return_release_after = None
        _return_release_time = None

        def _claim_space_press(self, event):
            return TkWizard._claim_space_press(self, event)

        def _claim_return_press(self, event):
            return TkWizard._claim_return_press(self, event)

    app = App()
    toggles = []
    row = SimpleNamespace(
        winfo_toplevel=lambda: SimpleNamespace(_tk_wizard=app),
        invoke=lambda: toggles.append(True),
    )

    assert _CheckRow._activate(row, SimpleNamespace(keysym=keysym, time=100)) == "break"
    setattr(app, held, False)
    setattr(app, release_time, 100)
    assert _CheckRow._activate(row, SimpleNamespace(keysym=keysym, time=200)) == "break"
    assert toggles == [True, True]
