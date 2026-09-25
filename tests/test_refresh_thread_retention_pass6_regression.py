"""Completed Tk refreshes must not retain every finished worker."""

from beamo_wipe.demo import discovery_for_scenario
from beamo_wipe.models import Screen
from test_refresh_scan_flow import _settle, _stub_app


def test_completed_refresh_releases_worker_reference():
    app, calls, _main = _stub_app(lambda: discovery_for_scenario("happy"))
    try:
        for expected_count in range(1, 4):
            app._click_refresh()
            assert app.w.screen == Screen.REFRESH_CONFIRM
            app._click_refresh()
            assert _settle(app) == Screen.OWNER
            assert len(calls) == expected_count
            assert not app._refresh_results
            assert not app._refresh_threads
    finally:
        app._teardown()
