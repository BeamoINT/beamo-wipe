"""A graphical control interruption must settle an owned erase first."""

import sys
import types

import pytest

from beamo_wipe import app
from beamo_wipe.models import Screen
from test_audit_20260907_console_input import _working


@pytest.mark.parametrize("interface", ["tk", "accessible"])
def test_graphical_control_interrupt_settles_fake_engine(
    monkeypatch, tmp_path, interface
):
    wizard = _working(monkeypatch, tmp_path)
    args = app._parser().parse_args([])
    fake_ui = types.ModuleType(f"beamo_wipe.ui.{interface}_wizard")

    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    setattr(fake_ui, f"run_{interface}", interrupted)
    monkeypatch.setitem(sys.modules, fake_ui.__name__, fake_ui)
    if interface == "tk":
        monkeypatch.setattr(app, "_build_wizard_with_tk_stages", lambda *_args: wizard)
    else:
        monkeypatch.setattr(
            app, "_build_wizard_with_accessible_stages", lambda *_args: wizard
        )

    with pytest.raises(KeyboardInterrupt):
        app._run_one_session(
            args,
            session_store=None,
            use_console=False,
            want_accessible=interface == "accessible",
            fullscreen=False,
            reader=None,
        )

    assert wizard.runner.cancelled
    assert wizard.wipe_result is not None
    assert wizard.wipe_result.summary == "interrupted"
    assert wizard.screen == Screen.DONE
