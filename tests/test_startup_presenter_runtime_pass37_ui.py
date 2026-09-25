# SPDX-License-Identifier: GPL-3.0-or-later
"""Only a missing display may use the splash-free startup path."""

from argparse import Namespace
import sys
import types

import pytest

from beamo_wipe import app
from beamo_wipe.models import Screen
from beamo_wipe.ui import StartupDisplayUnavailable


@pytest.mark.parametrize("surface", ("tk", "accessible"))
def test_presenter_runtime_failure_is_blocked_without_rediscovery(monkeypatch, surface):
    module_name = f"beamo_wipe.ui.{surface}_wizard"
    function_name = f"run_{surface}_startup"
    if surface == "accessible":
        module = types.ModuleType(module_name)
        monkeypatch.setitem(sys.modules, module_name, module)
    else:
        module = __import__(module_name, fromlist=[function_name])

    def fail_presenter(*_args, **_kwargs):
        raise RuntimeError("startup presenter failed")

    monkeypatch.setattr(module, function_name, fail_presenter, raising=False)
    rediscovery = []
    monkeypatch.setattr(
        app, "_build_without_splash",
        lambda _args: rediscovery.append(True),
    )

    build = (
        app._build_wizard_with_tk_stages(Namespace(), False)
        if surface == "tk"
        else app._build_wizard_with_accessible_stages(Namespace(), False)
    )
    assert not rediscovery
    assert build._startup_blocked
    assert build.screen is Screen.PICK_BLOCKED
    assert build.can_open_diagnostic


@pytest.mark.parametrize("surface", ("tk", "accessible"))
def test_missing_display_still_uses_splash_free_startup(monkeypatch, surface):
    module_name = f"beamo_wipe.ui.{surface}_wizard"
    function_name = f"run_{surface}_startup"
    if surface == "accessible":
        module = types.ModuleType(module_name)
        monkeypatch.setitem(sys.modules, module_name, module)
    else:
        module = __import__(module_name, fromlist=[function_name])

    def missing_display(*_args, **_kwargs):
        raise StartupDisplayUnavailable("no display")

    monkeypatch.setattr(module, function_name, missing_display, raising=False)
    expected = object()
    monkeypatch.setattr(app, "_build_without_splash", lambda _args: expected)

    build = (
        app._build_wizard_with_tk_stages(Namespace(), False)
        if surface == "tk"
        else app._build_wizard_with_accessible_stages(Namespace(), False)
    )
    assert build is expected
