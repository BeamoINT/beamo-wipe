"""One held Escape must not close an inventory overlay and leave the picker."""

from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import make_demo_wizard
import pytest


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([(0, ord("b")), (0, 27), (0, 27)], Screen.PICK),
        ([(0, ord("b")), (0, 27), (0, -1), (2, -1), (2, 27)], Screen.OWNER),
    ],
)
def test_overlay_escape_requires_a_new_physical_press(monkeypatch, events, expected):
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    assert wizard.screen == Screen.PICK
    assert wizard.protected_boot is not None

    class Terminal:
        def __init__(self):
            self.keys = iter(events)

        def getmaxyx(self):
            return 24, 80

        def getch(self):
            try:
                clock["now"], key = next(self.keys)
                return key
            except StopIteration:
                wizard.wants_shutdown = True
                return -1

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    clock = {"now": 0}
    monkeypatch.setattr(console.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(console, "_add", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(console, "_paint_footer", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(console.time, "sleep", lambda _seconds: None)

    assert console._loop(Terminal(), wizard) == 0
    assert wizard.screen == expected
