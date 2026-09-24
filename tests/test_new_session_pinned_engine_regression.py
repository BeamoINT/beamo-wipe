# SPDX-License-Identifier: GPL-3.0-or-later
"""A new owner flow must not outlive an unowned pinned engine."""

import pytest

from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.safety import SafetyError
from beamo_wipe.session_recovery import SessionStore
from test_erase_another import saved
from test_result_presentations import CASES, case_evidence
from test_session_recovery import armed, finish


@pytest.mark.parametrize("probe_error", [False, True])
def test_live_done_refuses_new_session_while_pinned_engine_uncertain(
    monkeypatch, probe_error
):
    def probe(**_kwargs):
        if probe_error:
            raise OSError("fake process table failure")
        return True

    monkeypatch.setattr("beamo_wipe.nwipe_runner.pinned_nwipe_already_running", probe)
    wizard, _, _ = case_evidence(CASES[0])
    wizard.runner = NwipeRunner()
    wizard.dry_run = False
    saved(wizard)

    assert not wizard.can_erase_another
    wizard.erase_another_disk()
    assert not wizard.wants_new_session


def test_live_done_allows_new_session_when_pinned_engine_absent(monkeypatch):
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running",
        lambda **_kwargs: False,
    )
    wizard, _, _ = case_evidence(CASES[0])
    wizard.runner = NwipeRunner()
    wizard.dry_run = False
    saved(wizard)

    assert wizard.can_erase_another
    wizard.erase_another_disk()
    assert wizard.wants_new_session


@pytest.mark.parametrize("probe_error", [False, True])
def test_journal_rotation_refuses_unowned_pinned_engine(
    tmp_path, monkeypatch, probe_error
):
    store = SessionStore(
        tmp_path / "private",
        boot="00000000-0000-0000-0000-000000000001",
        build="a" * 64,
    ).open()
    try:
        discovery, request = armed(store)
        finish(store, discovery, request)
        original = store.record.copy()

        def probe(**_kwargs):
            if probe_error:
                raise OSError("fake process table failure")
            return True

        monkeypatch.setattr(
            "beamo_wipe.nwipe_runner.pinned_nwipe_already_running", probe
        )
        with pytest.raises(SafetyError):
            store.begin_new_session()
        assert store.record == original
    finally:
        store.close()
