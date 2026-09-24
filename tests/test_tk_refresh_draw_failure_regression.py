"""A one-time Tk paint failure must not strand a claimed fake refresh."""

from beamo_wipe.copy import REDISCOVER_ERROR
from beamo_wipe.demo import discovery_for_scenario
from beamo_wipe.models import Screen
from test_refresh_scan_flow import _stub_app


def test_refresh_paint_failure_finishes_without_starting_discovery():
    app, calls, _main = _stub_app(lambda: discovery_for_scenario("happy"))
    try:
        app._click_refresh()
        assert app.w.screen == Screen.REFRESH_CONFIRM
        draw = app._draw
        failed = False

        def fail_once():
            nonlocal failed
            if app.w.screen == Screen.REFRESHING and not failed:
                failed = True
                raise RuntimeError("simulated one-time Tk paint failure")
            draw()

        app._draw = fail_once
        app._click_refresh()

        assert failed
        assert app.w.screen == Screen.PICK_BLOCKED
        assert app.w.error == REDISCOVER_ERROR
        assert app.w.can_refresh
        assert app.draws[-1][1] == Screen.PICK_BLOCKED
        assert not app._refresh_threads and not calls
    finally:
        app._teardown()
