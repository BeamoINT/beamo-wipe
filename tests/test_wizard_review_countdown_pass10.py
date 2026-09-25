"""The Last Chance review timer counts visible review time after navigation."""

import pytest

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard


class Clock:
    value = 0.0

    def __call__(self) -> float:
        return self.value


def _at_last_chance():
    clock = Clock()
    wizard = Wizard(
        make_demo_wizard().discovery,
        DryRunRunner(clock=clock),
        clock=clock,
        dry_run=True,
    )
    wizard.skip_intro()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    assert wizard.screen == Screen.LAST_CHANCE
    return wizard, clock


@pytest.mark.parametrize(
    "navigate,return_to_review",
    [
        ("keyboard", "accept_keyboard"),
        ("keyboard", "back"),
        ("advanced", "close_advanced"),
        ("advanced", "back"),
    ],
)
def test_navigation_away_from_last_chance_restarts_visible_review(
    navigate, return_to_review
):
    wizard, clock = _at_last_chance()
    getattr(wizard, f"open_{navigate}")()
    assert wizard.screen != Screen.LAST_CHANCE
    clock.value = 10.0
    getattr(wizard, return_to_review)()
    assert wizard.screen == Screen.LAST_CHANCE
    assert not wizard.erase_enabled
    assert wizard.countdown_left == pytest.approx(5.0)
    clock.value = 15.0
    assert wizard.erase_enabled


@pytest.mark.parametrize(
    "detour,return_to_review",
    [
        ("refresh", "cancel_refresh_confirm"),
        ("refresh", "back"),
        ("diagnostic", "close_diagnostic"),
        ("diagnostic", "back"),
        ("shutdown", "keep_report_session"),
        ("shutdown", "back"),
    ],
)
def test_confirmation_detour_restarts_visible_review(detour, return_to_review):
    wizard, clock = _at_last_chance()
    if detour == "refresh":
        assert wizard.open_refresh_confirm()
        assert wizard.screen == Screen.REFRESH_CONFIRM
    elif detour == "diagnostic":
        wizard.error = "test error"
        wizard.open_diagnostic()
        assert wizard.screen == Screen.DIAGNOSTIC
    else:
        wizard.report_wanted = True
        wizard.shutdown()
        assert wizard.screen == Screen.SHUTDOWN_CONFIRM
    clock.value = 10.0
    getattr(wizard, return_to_review)()
    assert wizard.screen == Screen.LAST_CHANCE
    assert not wizard.erase_enabled
    assert wizard.countdown_left == pytest.approx(5.0)
    clock.value = 15.0
    assert wizard.erase_enabled
