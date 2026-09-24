"""A refused journal open must not strand the single-interface lock."""

from __future__ import annotations

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.session_recovery import SessionStore


BOOT = "00000000-0000-0000-0000-000000000001"
BUILD = "a" * 64


def test_invalid_identity_releases_interface_lock_for_corrected_retry(tmp_path):
    directory = tmp_path / "private"
    first = SessionStore(directory, boot="not-a-boot-id", build=BUILD)
    second = SessionStore(directory, boot=BOOT, build=BUILD)
    try:
        with pytest.raises(SafetyError, match="identity"):
            first.open()
        assert first.fd == first.owner == first.quiescent == -1
        assert second.open() is second
        assert second.record["phase"] == "preflight"
    finally:
        first.close()
        second.close()
