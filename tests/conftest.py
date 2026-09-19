# SPDX-License-Identifier: GPL-3.0-or-later
"""Test-session safety: pytest is never a live wipe and never execs pinned nwipe."""

from __future__ import annotations

import os

import pytest

@pytest.fixture(autouse=True)
def _isolate_beamo_env(monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.delenv("BEAMO_WIPE_LIVE", raising=False)


@pytest.fixture(autouse=True)
def _never_a_live_wipe_session(monkeypatch):
    monkeypatch.setattr("beamo_wipe.app.running_on_live_usb", lambda: False)


@pytest.fixture(autouse=True)
def _reset_ui_language():
    yield
    from beamo_wipe import lang

    lang.set_language("en")


def pytest_collection_modifyitems(config, items):
    """Run the Orca child before other GTK tests drown Bookworm AT-SPI."""
    if os.environ.get("BEAMO_HOSTED_ORCA_SEPARATE") == "1":
        items[:] = [
            item for item in items if item.name != "test_orca_announces_every_result"
        ]
        return
    orca = [item for item in items if item.name == "test_orca_announces_every_result"]
    rest = [item for item in items if item.name != "test_orca_announces_every_result"]
    items[:] = orca + rest
