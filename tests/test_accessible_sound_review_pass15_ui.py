"""A sound check over final review must not consume its visible countdown."""

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


def _review():
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


def test_sound_overlay_requires_fresh_visible_review_after_close():
    wizard, clock = _review()
    wizard.begin_review_overlay()
    clock.value = 10.0
    assert not wizard.erase_enabled
    wizard.end_review_overlay()
    assert not wizard.erase_enabled
    assert wizard.countdown_left == 5.0
    clock.value = 15.0
    assert wizard.erase_enabled
