# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #52: refresh claim/apply split for off-UI-thread discovery.

``begin_refresh`` claims the checking state and resets authorization on the
UI thread; I/O runs wherever the caller wants; ``finish_refresh`` applies
the result back on the UI thread and drops stale sequences. The synchronous
``refresh_disks`` keeps its contract for sequential callers. All headless.
"""

import threading

from beamo_wipe.copy import REDISCOVER_ERROR
from beamo_wipe.demo import DEMO_DURATION_S, discovery_for_scenario
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard


def make_wiz(**kwargs):
    kwargs.setdefault("rediscover", lambda: discovery_for_scenario("happy"))
    wiz = Wizard(
        discovery_for_scenario("happy"),
        DryRunRunner(duration_s=DEMO_DURATION_S),
        dry_run=True,
        **kwargs,
    )
    wiz.preview = True
    wiz.skip_intro()
    wiz.accept_what()
    assert wiz.screen == Screen.OWNER
    return wiz


def fresh_wiz(**kwargs):
    """Wizard still on SPLASH, where refresh is refused."""
    kwargs.setdefault("rediscover", lambda: discovery_for_scenario("happy"))
    wiz = Wizard(
        discovery_for_scenario("happy"),
        DryRunRunner(duration_s=DEMO_DURATION_S),
        dry_run=True,
        **kwargs,
    )
    wiz.preview = True
    return wiz


def test_begin_claims_checking_and_resets_authorization():
    wiz = make_wiz()
    wiz.set_owner(True)
    seq = wiz.begin_refresh()
    assert seq is not None
    assert wiz.screen == Screen.REFRESHING
    assert wiz.selected is None
    assert wiz.owner_ok is False
    assert wiz.confirm_input == ""
    assert wiz.error is None


def test_begin_refused_off_screen():
    wiz = fresh_wiz()
    assert wiz.screen == Screen.SPLASH
    assert wiz.begin_refresh() is None
    assert wiz.screen == Screen.SPLASH


def test_duplicate_begin_refused_while_scan_in_flight():
    wiz = make_wiz()
    first = wiz.begin_refresh()
    assert wiz.begin_refresh() is None
    assert wiz.screen == Screen.REFRESHING
    assert wiz.finish_refresh(first, discovery_for_scenario("happy")) is True
    assert wiz.screen == Screen.WHAT
    # Unknown sequences never apply, even on the checking screen.
    second = wiz.begin_refresh()
    assert wiz.finish_refresh(first + 999, discovery_for_scenario("happy")) is False
    assert wiz.screen == Screen.REFRESHING
    # After a completed scan, refresh is available again (retry works).
    assert wiz.finish_refresh(second, discovery_for_scenario("happy")) is True
    assert wiz.screen == Screen.WHAT
    assert (
        wiz.finish_refresh(wiz.begin_refresh(), discovery_for_scenario("happy")) is True
    )
    assert wiz.screen == Screen.WHAT


def test_finish_failure_goes_fail_closed_blocked():
    wiz = make_wiz()
    seq = wiz.begin_refresh()
    assert wiz.finish_refresh(seq, RuntimeError("scan blew up")) is True
    assert wiz.screen == Screen.PICK_BLOCKED
    assert wiz.error == REDISCOVER_ERROR
    assert wiz.selectable == ()


def test_finish_invalid_inventory_goes_fail_closed():
    wiz = make_wiz()
    seq = wiz.begin_refresh()
    assert wiz.finish_refresh(seq, "bogus") is True
    assert wiz.screen == Screen.PICK_BLOCKED
    assert wiz.error == REDISCOVER_ERROR


def test_finish_after_screen_moved_on_drops():
    wiz = make_wiz()
    seq = wiz.begin_refresh()
    with wiz._lock:
        wiz.screen = Screen.WHAT  # some other transition won the race
    assert wiz.finish_refresh(seq, discovery_for_scenario("happy")) is False
    assert wiz.screen == Screen.WHAT


def test_sync_refresh_success_preserved():
    wiz = make_wiz()
    assert wiz.refresh_disks() is True
    assert wiz.screen == Screen.WHAT
    assert wiz.selected is None


def test_sync_refresh_failure_preserved():
    def boom():
        raise RuntimeError("scan blew up")

    wiz = make_wiz(rediscover=boom)
    assert wiz.refresh_disks() is True
    assert wiz.screen == Screen.PICK_BLOCKED
    assert wiz.error == REDISCOVER_ERROR


def test_sync_refresh_refused_off_screen():
    wiz = fresh_wiz()
    assert wiz.refresh_disks() is False
    assert wiz.screen == Screen.SPLASH


def test_run_rediscovery_executes_on_caller_thread():
    seen = []
    wiz = make_wiz(rediscover=lambda: seen.append(threading.get_ident()))
    wiz._run_rediscovery()
    assert seen == [threading.get_ident()]
