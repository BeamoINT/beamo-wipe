# SPDX-License-Identifier: GPL-3.0-or-later
"""Test-session safety: pytest is never a live wipe and never execs pinned nwipe."""

from __future__ import annotations

import os

import pytest

# Default dry-run so collecting tests on a live USB cannot start the engine.
os.environ.setdefault("BEAMO_WIPE_DRY_RUN", "1")


@pytest.fixture(autouse=True)
def _never_a_live_wipe_session(monkeypatch):
    monkeypatch.setattr("beamo_wipe.app.running_on_live_usb", lambda: False)
