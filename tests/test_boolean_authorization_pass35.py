"""Malformed truthy values cannot stand in for owner consent or elapsed review."""

import pytest

from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.models import MethodId, Screen
from beamo_wipe.safety import SafetyError, assert_ready_to_wipe


@pytest.mark.parametrize("checked", ["false", "no", 1, object()])
def test_owner_checkbox_accepts_only_a_boolean(checked):
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    assert wizard.screen is Screen.OWNER

    wizard.set_owner(checked)
    wizard.continue_owner()

    assert wizard.owner_ok is False
    assert wizard.screen is Screen.OWNER


def test_malformed_checkbox_update_revokes_prior_consent():
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    assert wizard.owner_ok is True

    wizard.set_owner("false")
    wizard.continue_owner()

    assert wizard.owner_ok is False
    assert wizard.screen is Screen.OWNER


@pytest.mark.parametrize(
    "owner_ok,countdown_complete,message",
    [
        ("false", True, "Owner checkbox is required"),
        (1, True, "Owner checkbox is required"),
        (True, "ready", "Erase delay has not finished"),
        (True, 1, "Erase delay has not finished"),
    ],
)
def test_preflight_rejects_nonboolean_authorization(
    owner_ok, countdown_complete, message, monkeypatch,
):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    discovery = discovery_for_scenario("happy")
    disk = discovery.selectable[0]
    from beamo_wipe.safety import confirm_spec, listed_disks

    token = confirm_spec(disk, listed_disks(discovery)).token
    with pytest.raises(SafetyError, match=message):
        assert_ready_to_wipe(
            owner_ok=owner_ok,
            disk=disk,
            discovery=discovery,
            typed_token=token,
            countdown_complete=countdown_complete,
            method=MethodId.EVERYDAY,
        )
