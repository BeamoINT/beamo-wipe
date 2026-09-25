"""A retired interface must not accept a delayed erase action."""

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen


def test_interface_failure_before_erase_claim_blocks_late_action(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wizard = make_demo_wizard()
    wizard.preview = False
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    wizard._erase_until = 0
    assert wizard.screen is Screen.LAST_CHANCE
    assert wizard.erase_enabled

    wizard.interface_failed()

    assert not wizard.begin_erase()
    assert not wizard.runner.started
    assert not wizard.erase_enabled
