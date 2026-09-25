"""A failed console startup worker launch should retain the support screen."""

from argparse import Namespace
import sys
import types

import pytest

from beamo_wipe import app
from beamo_wipe.models import Screen
from beamo_wipe.startup_stages import StartupRun


def test_console_startup_worker_launch_failure_stays_blocked(monkeypatch):
    def fail_start(_self):
        raise RuntimeError("worker could not start")

    monkeypatch.setattr(StartupRun, "start", fail_start)
    wizard = app._build_wizard_with_console_stages(Namespace())

    assert wizard._startup_blocked
    assert wizard.screen is Screen.PICK_BLOCKED
    assert wizard.can_open_diagnostic


@pytest.mark.parametrize("surface", ["tk", "accessible"])
def test_graphical_startup_unexpected_failure_stays_blocked(monkeypatch, surface):
    module_name = f"beamo_wipe.ui.{surface}_wizard"
    function_name = f"run_{surface}_startup"
    if surface == "accessible":
        module = types.ModuleType(module_name)
        monkeypatch.setitem(sys.modules, module_name, module)
    else:
        module = __import__(module_name, fromlist=[function_name])

    def fail_startup(*_args, **_kwargs):
        raise OSError("startup worker could not launch")

    monkeypatch.setattr(module, function_name, fail_startup, raising=False)
    args = Namespace()
    build = (
        app._build_wizard_with_tk_stages(args, False)
        if surface == "tk"
        else app._build_wizard_with_accessible_stages(args, False)
    )
    assert build._startup_blocked
    assert build.screen is Screen.PICK_BLOCKED
    assert build.can_open_diagnostic
