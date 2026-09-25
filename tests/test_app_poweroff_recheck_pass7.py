"""Poweroff must recheck engine ownership after the UI has accepted exit."""

from types import SimpleNamespace

import pytest

from beamo_wipe import app
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen


@pytest.mark.parametrize("use_console", [True, False])
def test_poweroff_rechecks_engine_after_exit_decision(monkeypatch, use_console):
    wizard = make_demo_wizard()
    wizard.dry_run = False
    wizard.preview = False
    wizard.screen = Screen.OWNER
    checks = []
    powered = []

    def engine_busy():
        checks.append(True)
        return len(checks) > 1

    wizard._live_pinned_engine_busy = engine_busy
    monkeypatch.setattr(app, "running_on_live_usb", lambda: False)
    monkeypatch.setattr(app, "_build_wizard_with_console_stages", lambda _args: wizard)
    monkeypatch.setattr(app, "_build_wizard_with_tk_stages", lambda *_args: wizard)
    monkeypatch.setattr(app, "_shutdown", lambda: powered.append(True) or True)

    def accept_exit(active):
        active.shutdown()
        assert active.wants_shutdown
        return 0

    monkeypatch.setattr("beamo_wipe.ui.console_wizard.run_console", accept_exit)
    monkeypatch.setattr("beamo_wipe.ui.tk_wizard.run_tk", lambda active, **_kw: accept_exit(active))
    args = SimpleNamespace(demo=False, lang="en", plain_console=False)
    assert app._run_one_session(
        args,
        session_store=None,
        use_console=use_console,
        want_accessible=False,
        fullscreen=False,
        reader=None,
    ) == 0
    assert len(checks) >= 2
    assert powered == []
