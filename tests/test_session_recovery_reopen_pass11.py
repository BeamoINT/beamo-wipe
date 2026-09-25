"""Repeated recovery open must not lose ownership of an existing lock."""

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.session_recovery import SessionStore


BOOT = "00000000-0000-0000-0000-000000000001"
BUILD = "a" * 64


def test_second_open_keeps_first_lock_owned_and_close_releases_it(tmp_path):
    directory = tmp_path / "private"
    store = SessionStore(directory, boot=BOOT, build=BUILD).open()
    owned = (store.fd, store.owner)
    try:
        with pytest.raises(SafetyError, match="already open"):
            store.open()
        assert (store.fd, store.owner) == owned
    finally:
        store.close()

    another = SessionStore(directory, boot=BOOT, build=BUILD).open()
    another.close()
