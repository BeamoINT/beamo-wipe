"""Boot and live-medium proof require actual booleans at safety boundaries."""

from dataclasses import replace

import pytest

from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.safety import (
    SafetyError,
    assert_boot_excluded,
    is_live_environment,
    require_live_or_dry_run,
    selectable_disks,
)


@pytest.mark.parametrize("reported", ["false", 1, object()])
def test_malformed_boot_proof_cannot_expose_any_target(reported):
    discovery = replace(discovery_for_scenario("happy"), boot_identified=reported)
    assert selectable_disks(discovery) == ()
    with pytest.raises(SafetyError, match="cannot tell which disk"):
        assert_boot_excluded(discovery)


def test_malformed_boot_proof_shows_blocked_screen():
    wizard = make_demo_wizard()
    wizard.discovery = replace(wizard.discovery, boot_identified="false")
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    assert wizard.screen is Screen.PICK_BLOCKED


@pytest.mark.parametrize("reported", ["false", 1, object()])
def test_malformed_live_mount_proof_cannot_enable_wipes(reported):
    assert not is_live_environment(cmdline="boot=live", live_medium_mounted=reported)
    with pytest.raises(SafetyError, match="only erases disks"):
        require_live_or_dry_run(
            env={}, cmdline="boot=live", live_medium_mounted=reported,
        )
