"""The UI must wait until terminal evidence finishes before powering off."""

import threading

import pytest

from beamo_wipe.models import Screen, WipeResult
from test_refresh_disks import authorized


@pytest.mark.parametrize("report_wanted", [False, True])
def test_shutdown_stays_blocked_between_done_and_evidence_save(report_wanted):
    wizard = authorized()
    wizard.report_wanted = report_wanted
    wizard.confirm_erase()
    entered = threading.Event()
    release = threading.Event()

    def delayed_evidence(*_args, **_kwargs):
        entered.set()
        release.wait(2)

    wizard._write_evidence = delayed_evidence
    worker = threading.Thread(
        target=lambda: wizard._finish(WipeResult(False, 1, "fake failure", "/tmp/fake.log"))
    )
    worker.start()
    try:
        assert entered.wait(2)
        assert wizard.screen == Screen.DONE
        assert wizard._finishing
        assert not wizard._evidence_saving
        wizard.shutdown()
        assert not wizard.wants_shutdown
        assert wizard.screen == Screen.DONE
        assert wizard.report_view.saving_evidence
    finally:
        release.set()
        worker.join(2)


def test_confirm_shutdown_without_saving_waits_for_terminal_evidence():
    wizard = authorized()
    wizard.screen = Screen.SHUTDOWN_CONFIRM
    wizard._shutdown_from = Screen.DONE
    wizard.shutdown_generation = 3
    wizard._finishing = True
    wizard.confirm_shutdown_without_saving(3)
    assert not wizard.wants_shutdown
