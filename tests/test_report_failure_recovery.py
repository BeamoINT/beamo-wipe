"""Report failures stay recoverable; fake exporters and ordinary files only."""

import errno
import json
import time
from unittest.mock import Mock

import pytest

from beamo_wipe.models import Screen
from beamo_wipe.demo import make_demo_wizard
from test_usb_report_workflow import _done_wizard, _success_receipt


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("number", [errno.EIO, errno.EACCES])
def test_evidence_read_error_is_visible_and_retryable(tmp_path, monkeypatch, background, number):
    exporter = Mock(side_effect=_success_receipt)
    w = _done_wizard(exporter, tmp_path)
    w.report_wanted = True
    result = w.wipe_result
    with monkeypatch.context() as patch:
        patch.setattr("beamo_wipe.evidence.os.read", Mock(side_effect=OSError(number, "private-customer-path")))
        if background:
            assert w.begin_report_export() is False
        else:
            w.save_report_to_usb()
    assert w.screen == Screen.DONE and w.wipe_result is result
    assert w.report_view.status == "error"
    assert "private-customer-path" not in w.report_view.message
    assert not w.report_view.exporting and w.report_view.can_save
    exporter.assert_not_called()
    w.save_report_to_usb()
    assert w.report_status == "saved"
    w.shutdown()
    assert w.wants_shutdown


@pytest.mark.parametrize("code", ["boot_unidentified", "recovery_indeterminate"])
def test_diagnostic_bundle_title_matches_report_context(tmp_path, code):
    from beamo_wipe.diagnostic_report import create_report
    from beamo_wipe.support_export import write_report_bundle

    data = create_report(code, make_demo_wizard().discovery, ui="console", session_started=time.monotonic())
    session, files = write_report_bundle(tmp_path, data, b"", "unavailable")
    payload = json.loads(data)
    assert files["README.txt"].decode().splitlines()[0] == payload["title"]
    assert payload["notice"] in files["README.txt"].decode()
    assert session.startswith("report-")


@pytest.mark.parametrize("phase", ["construct", "start"])
def test_report_worker_creation_failure_releases_claim(tmp_path, monkeypatch, phase):
    exporter = Mock(side_effect=_success_receipt)
    w = _done_wizard(exporter, tmp_path)
    w.report_wanted = True
    error = RuntimeError("worker unavailable; private-customer-path")
    factory = Mock(side_effect=error) if phase == "construct" else Mock(return_value=Mock(start=Mock(side_effect=error)))
    with monkeypatch.context() as patch:
        patch.setattr("beamo_wipe.wizard.threading.Thread", factory)
        assert w.begin_report_export() is False
    assert w.report_view.status == "error"
    assert not w.report_view.exporting and w.report_view.can_save
    assert w._active_report_claim is None
    assert "private-customer-path" not in w.report_message
    exporter.assert_not_called()
    w.shutdown()
    assert w.screen == Screen.SHUTDOWN_CONFIRM
    assert not w.wants_shutdown
    w.keep_report_session()
    w.save_report_to_usb()
    assert w.report_status == "saved"
