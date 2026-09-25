"""A live recovery refusal has a bounded, non-sensitive serial clue."""

from __future__ import annotations

import pytest

from beamo_wipe import app, diagnostics, session_recovery
from beamo_wipe.safety import SafetyError


@pytest.mark.parametrize(
    "failure, marker",
    [
        (SafetyError(session_recovery.RECOVERY_DIRECTORY_NOT_VOLATILE),
         "BEAMO_WIPE_RECOVERY_TMP_NOT_VOLATILE"),
        (OSError("private path"), "BEAMO_WIPE_RECOVERY_UNAVAILABLE"),
    ],
)
def test_live_recovery_refusal_emits_fixed_marker(monkeypatch, failure, marker):
    markers = []
    closed = []

    class FailedStore:
        def open(self):
            raise failure

        def close(self):
            closed.append(True)

    monkeypatch.setattr(app, "running_on_live_usb", lambda: True)
    monkeypatch.setattr(session_recovery, "SessionStore", FailedStore)
    monkeypatch.setattr(diagnostics, "emit_serial_marker", lambda value: markers.append(value) or True)

    assert app.main([]) == 3
    assert markers == [marker]
    assert closed == [True]
