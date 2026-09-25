"""A returning graphical event loop cannot abandon a fake active erase."""

import sys
import types

import pytest

from beamo_wipe import app
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from test_audit_20260907_console_input import _working


@pytest.mark.parametrize("interface", ["tk", "accessible"])
@pytest.mark.parametrize("code", [0, 3])
def test_unexpected_graphical_return_settles_active_fake_engine(
    monkeypatch, tmp_path, interface, code
):
    wizard = _working(monkeypatch, tmp_path)
    args = app._parser().parse_args([])
    module_name = f"beamo_wipe.ui.{interface}_wizard"
    fake_ui = types.ModuleType(module_name)
    setattr(fake_ui, f"run_{interface}", lambda *_args, **_kwargs: code)
    monkeypatch.setitem(sys.modules, module_name, fake_ui)
    if interface == "tk":
        monkeypatch.setattr(app, "_build_wizard_with_tk_stages", lambda *_args: wizard)
    else:
        monkeypatch.setattr(
            app, "_build_wizard_with_accessible_stages", lambda *_args: wizard
        )

    assert (
        app._run_one_session(
            args,
            session_store=None,
            use_console=False,
            want_accessible=interface == "accessible",
            fullscreen=False,
            reader=None,
        )
        == code
    )
    assert wizard.runner.cancelled
    assert wizard.wipe_result is not None
    assert wizard.wipe_result.summary == "interrupted"
    assert wizard.screen == Screen.DONE


@pytest.mark.parametrize("interface", ["tk", "accessible"])
def test_accepted_graphical_shutdown_does_not_settle(monkeypatch, interface):
    wizard = make_demo_wizard()
    wizard.shutdown()
    assert wizard.wants_shutdown
    args = app._parser().parse_args([])
    module_name = f"beamo_wipe.ui.{interface}_wizard"
    fake_ui = types.ModuleType(module_name)
    setattr(fake_ui, f"run_{interface}", lambda *_args, **_kwargs: 0)
    monkeypatch.setitem(sys.modules, module_name, fake_ui)
    if interface == "tk":
        monkeypatch.setattr(app, "_build_wizard_with_tk_stages", lambda *_args: wizard)
    else:
        monkeypatch.setattr(
            app, "_build_wizard_with_accessible_stages", lambda *_args: wizard
        )

    def unexpected_settlement():
        pytest.fail("accepted shutdown is not interface loss")

    monkeypatch.setattr(wizard, "settle_failed_interface", unexpected_settlement)
    assert (
        app._run_one_session(
            args,
            session_store=None,
            use_console=False,
            want_accessible=interface == "accessible",
            fullscreen=False,
            reader=None,
        )
        == 0
    )
