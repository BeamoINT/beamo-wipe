"""The saved report evaluates a whole-log projection but hashes the exported tail."""

import hashlib

from beamo_wipe.models import WipeResult
from test_evidence_retry import start

STATUS = "********************************* Drive Status *********************************\n"


def test_terminal_evidence_uses_whole_log_assessment_and_keeps_tail_hash(
    tmp_path, monkeypatch
):
    wizard, _clock = start(tmp_path, monkeypatch)
    request = wizard._wipe_request
    assert request is not None
    target = request.device.rsplit("/", 1)[-1]
    tail = STATUS + f"{target} | Erased |  120MB/s | 01:25:04 | QEMU/DISK\n"
    assessment = f"*** HIDDEN SECTORS DETECTED ! *** on {request.device}\n" + tail
    wizard.runner._log_tail = tail
    wizard.runner._assessment_log_text = assessment
    wizard.runner._assessment_ready = True
    wizard._evidence_written_for = None
    result = WipeResult(True, 0, "finished", request.logfile, "completed")
    wizard.wipe_result = result

    wizard._write_evidence(result=result, cancelled=False, interrupted=False)

    evidence = wizard.evidence
    assert evidence is not None
    assert evidence["outcome"] == "verified"
    hidden = next(
        check for check in evidence["checks"] if check["id"] == "hidden_capacity"
    )
    assert hidden["status"] == "warning"
    assert evidence["log_checksum_sha256"] == hashlib.sha256(tail.encode()).hexdigest()


def test_incomplete_whole_log_assessment_cannot_trust_a_successful_tail(
    tmp_path, monkeypatch
):
    wizard, _clock = start(tmp_path, monkeypatch)
    request = wizard._wipe_request
    assert request is not None
    target = request.device.rsplit("/", 1)[-1]
    tail = (
        f"No hidden sectors on {request.device}\n"
        + STATUS + f"{target} | Erased |  120MB/s | 01:25:04 | QEMU/DISK\n"
    )
    wizard.runner._log_tail = tail
    wizard.runner._assessment_log_text = None
    wizard.runner._assessment_ready = True
    wizard._evidence_written_for = None
    result = WipeResult(True, 0, "finished", request.logfile, "completed")
    wizard.wipe_result = result

    wizard._write_evidence(result=result, cancelled=False, interrupted=False)

    evidence = wizard.evidence
    assert evidence is not None
    assert evidence["outcome"] == "failed"
    hidden = next(
        check for check in evidence["checks"] if check["id"] == "hidden_capacity"
    )
    assert hidden["status"] == "unavailable"
