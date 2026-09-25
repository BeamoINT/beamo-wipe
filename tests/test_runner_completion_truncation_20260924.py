"""Completion evidence must account for the entire nwipe log."""

from pathlib import Path

import pytest

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import (
    NWIPE_COMPLETION_LOG_BYTES,
    NwipeRunner,
    completion_for_method,
)
from beamo_wipe.engine_checks import check_payloads


class ExitedProcess:
    def poll(self):
        return 0


def _poll_log(path):
    runner = NwipeRunner()
    request = WipeRequest(
        device="/dev/sda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sdb",
        logfile=str(path),
    )
    runner._proc = ExitedProcess()
    return runner.poll(request)


PADDING = "ordinary message\n" * (
    NWIPE_COMPLETION_LOG_BYTES // len("ordinary message\n") + 1
)
STATUS = "********************************* Drive Status *********************************\n"
ERASED_ROW = "      sda | Erased |  120MB/s | 01:25:04 | QEMU/DISK\n"


def test_truncated_completion_log_cannot_hide_earlier_target_failure(tmp_path):
    logfile = tmp_path / "nwipe.log"
    logfile.write_text(
        "sda |-FAILED-|\n" + PADDING + STATUS + ERASED_ROW,
        encoding="utf-8",
    )
    assert (
        completion_for_method(
            0, logfile.read_text(encoding="utf-8"), "/dev/sda", MethodId.EVERYDAY
        )[0]
        is False
    )
    result = _poll_log(logfile)
    assert result is not None
    assert result.ok is False
    assert result.reason == "engine_failed"


def test_large_successful_log_retains_explicit_completion(tmp_path):
    logfile = tmp_path / "nwipe.log"
    logfile.write_text(PADDING + STATUS + ERASED_ROW, encoding="utf-8")

    result = _poll_log(logfile)

    assert result is not None
    assert result.ok is True
    assert result.reason == "completed"


def test_large_progress_log_retains_final_verified_pass(tmp_path):
    logfile = tmp_path / "nwipe.log"
    writing = "/dev/sda: 000.00%, round 1 of 1, pass 1 of 1, eta 001:00:00, [writing]\n"
    verified = (
        "/dev/sda: 100.00%, round 1 of 1, pass 1 of 1, eta 000:00:00, [verifying]\n"
    )
    logfile.write_text(
        writing * (NWIPE_COMPLETION_LOG_BYTES // len(writing) + 1) + verified,
        encoding="utf-8",
    )

    result = _poll_log(logfile)

    assert result is not None
    assert result.ok is True
    assert result.reason == "completed"


def test_complete_log_keeps_explicit_success(tmp_path):
    logfile = tmp_path / "nwipe.log"
    logfile.write_text(STATUS + ERASED_ROW, encoding="utf-8")

    result = _poll_log(logfile)

    assert result is not None
    assert result.ok is True
    assert result.reason == "completed"


def test_large_log_preserves_early_hidden_capacity_warning_for_assessment(tmp_path):
    logfile = tmp_path / "nwipe.log"
    logfile.write_text(
        "*** HIDDEN SECTORS DETECTED ! *** on /dev/sda\n"
        + PADDING
        + STATUS + ERASED_ROW,
        encoding="utf-8",
    )
    runner = NwipeRunner()
    runner._proc = ExitedProcess()
    request = WipeRequest(
        device="/dev/sda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sdb",
        logfile=str(logfile),
    )

    result = runner.poll(request)

    assert result is not None and result.ok
    assert (
        check_payloads(runner._assessment_log_text, "/dev/sda")[0]["status"]
        == "warning"
    )
    assert check_payloads(runner._log_tail, "/dev/sda")[0]["status"] == "unavailable"


def test_large_log_preserves_contradictory_hidden_capacity_lines(tmp_path):
    logfile = tmp_path / "nwipe.log"
    logfile.write_text(
        "*** HIDDEN SECTORS DETECTED ! *** on /dev/sda\n"
        + PADDING
        + "No hidden sectors on /dev/sda\n" + STATUS + ERASED_ROW,
        encoding="utf-8",
    )
    runner = NwipeRunner()
    runner._proc = ExitedProcess()
    request = WipeRequest(
        device="/dev/sda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sdb",
        logfile=str(logfile),
    )

    result = runner.poll(request)

    assert result is not None and result.ok
    assert (
        check_payloads(runner._assessment_log_text, "/dev/sda")[0]["status"]
        == "unavailable"
    )
    assert check_payloads(runner._log_tail, "/dev/sda")[0]["status"] == "pass"


@pytest.mark.parametrize(
    "fixture",
    sorted((Path(__file__).parent / "fixtures/nwipe_v042").glob("*.log")),
    ids=lambda path: path.stem,
)
def test_streamed_large_log_matches_full_log_verdict(tmp_path, fixture):
    original = fixture.read_text(encoding="utf-8")
    logfile = tmp_path / "nwipe.log"
    logfile.write_text(PADDING + original, encoding="utf-8")

    runner = NwipeRunner()
    runner._proc = ExitedProcess()
    request = WipeRequest(
        device="/dev/sda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sdb",
        logfile=str(logfile),
    )
    result = runner.poll(request)
    expected = completion_for_method(
        0, PADDING + original, "/dev/sda", MethodId.EVERYDAY
    )

    assert result is not None
    assert (result.ok, result.reason) == (expected[0], expected[2])
    got_checks = check_payloads(runner._assessment_log_text or "", "/dev/sda")
    full_checks = check_payloads(PADDING + original, "/dev/sda")
    assert [(item["id"], item["status"]) for item in got_checks] == [
        (item["id"], item["status"]) for item in full_checks
    ]
