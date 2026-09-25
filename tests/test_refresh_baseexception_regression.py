# SPDX-License-Identifier: GPL-3.0-or-later
"""A failed scan must not strand a cleared authorization in REFRESHING."""

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
import pytest


def test_interrupted_fake_scan_finishes_blocked_and_allows_retry():
    wizard = make_demo_wizard()
    wizard.skip_intro()

    def interrupted():
        raise KeyboardInterrupt()

    wizard._rediscover = interrupted
    try:
        refreshed = wizard.refresh_disks()
    except KeyboardInterrupt:
        pytest.fail("the scan interrupted the UI instead of completing fail closed")
    assert refreshed
    assert wizard.screen == Screen.PICK_BLOCKED
    assert wizard.selectable == ()
    assert wizard.selected is None
    assert not wizard.owner_ok
    assert wizard.can_refresh

    wizard._rediscover = lambda: make_demo_wizard().discovery
    assert wizard.refresh_disks()
    assert wizard.screen == Screen.OWNER
