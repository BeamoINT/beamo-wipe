"""Fake owner flow across launch, terminal retry, recovery, export, and shutdown."""

import errno
from pathlib import Path

import pytest

from beamo_wipe import evidence
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.session_recovery import SessionStore
from beamo_wipe.wizard import Wizard
from test_session_recovery import BOOT, BUILD
from test_usb_report_workflow import _success_receipt

STATUS = "********************************* Drive Status *********************************\n"


@pytest.mark.parametrize("outcome", ["success", "cancelled"])
def test_fake_owner_can_retry_recover_export_and_shutdown(
    tmp_path, monkeypatch, outcome
):
    directory = tmp_path / "private"
    monkeypatch.setattr("beamo_wipe.safety.DEFAULT_LOG_DIR", directory)
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: directory)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running",
        lambda **_kwargs: False,
    )
    first = SessionStore(directory, boot=BOOT, build=BUILD).open()
    second = SessionStore(directory, boot=BOOT, build=BUILD)
    try:
        discovery = make_demo_wizard().discovery
        wizard = Wizard(discovery, DryRunRunner(duration_s=60), dry_run=True)
        wizard.enable_session_recovery(first)
        wizard.report_wanted = True
        wizard.skip_intro()
        wizard.accept_what()
        wizard.set_owner(True)
        wizard.continue_owner()
        wizard.select_disk(wizard.selectable[0].path)
        wizard.continue_pick()
        wizard.set_confirm_input(wizard.confirm.token)
        wizard.continue_confirm()
        wizard.continue_method()
        wizard._erase_until = 0
        wizard.confirm_erase()
        assert wizard.screen == Screen.WORKING
        request = wizard._wipe_request
        assert request is not None

        original_writer = evidence.write_evidence_atomic
        attempts = 0

        def fail_terminal_once(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError(errno.ENOSPC, "fake evidence write failure")
            return original_writer(*args, **kwargs)

        monkeypatch.setattr(evidence, "write_evidence_atomic", fail_terminal_once)
        if outcome == "cancelled":
            wizard.cancel_wipe()
        else:
            log = (
                STATUS
                + f"{Path(request.device).name} | Erased |  120MB/s | 01:25:04 | QEMU/DISK\n"
            )
            Path(request.logfile).write_text(log)
            Path(request.logfile).chmod(0o600)
            wizard.runner._log_tail = log
            wizard.runner.result = WipeResult(True, 0, "finished", request.logfile)
            wizard.runner._started = None
            wizard.tick()

        assert wizard.screen == Screen.DONE
        assert wizard.evidence_error and wizard.can_retry_evidence
        wizard.shutdown()
        assert not wizard.wants_shutdown
        assert wizard.screen == Screen.SHUTDOWN_CONFIRM
        wizard.keep_report_session()
        assert wizard.retry_evidence_save()
        assert wizard.evidence_status == "saved"
        first.close()

        second.open()
        recovered = Wizard(discovery, DryRunRunner(), dry_run=True)
        recovered.enable_session_recovery(second)
        assert recovered.screen == Screen.DONE
        assert recovered.result_view.success is (outcome == "success")
        assert recovered.can_save_report

        def fail_export(**_kwargs):
            raise OSError("fake export failure")

        recovered._report_exporter = fail_export
        recovered.save_report_to_usb()
        assert recovered.report_status == "error" and recovered.can_save_report
        recovered._report_exporter = _success_receipt
        recovered.save_report_to_usb()
        assert recovered.report_status == "saved"
        recovered.shutdown()
        assert recovered.wants_shutdown and recovered.shutdown_still_safe()
    finally:
        first.close()
        second.close()
