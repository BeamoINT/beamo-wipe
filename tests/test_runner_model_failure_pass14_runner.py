"""Device-controlled model text cannot masquerade as nwipe failure evidence."""

import pytest

from beamo_wipe.engine_checks import evaluate_engine_checks
from beamo_wipe.nwipe_runner import _target_reported_failure, evaluate_nwipe_outcome

STATUS = "********************************* Drive Status *********************************\n"
ERASED = " sda | Erased | 120MB/s | 01:00:00 | model\n"


def _io_status(log: str) -> str:
    return {check.id: check.status for check in evaluate_engine_checks(log, "/dev/sda")}["io_media"]


def test_failure_phrase_in_erased_disk_model_does_not_override_status():
    log = (
        "Error Summary\n sda | 0 | 0 | 0\n***\n"
        + STATUS + " sda | Erased | 120MB/s | 01:00:00 | model >>> FAILURE! <<<\n"
    )

    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[0] is True
    assert _io_status(log) == "pass"


def test_foreign_failed_row_with_target_name_in_model_is_not_target_failure():
    log = (
        "Error Summary\n sda | 0 | 0 | 0\n***\n"
        + STATUS
        + " sdb |-FAILED-| 120MB/s | 01:00:00 | model /dev/sda\n"
        " sda | Erased | 120MB/s | 01:00:00 | model\n"
    )

    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[0] is True
    assert _io_status(log) == "pass"


@pytest.mark.parametrize(
    "message",
    [
        "/dev/sda is reported as IN USE",
        "/dev/sda is IN USE but --force is not set, not wiping it",
        "Unable to open device '/dev/sda'.",
        "No sane device geometry for '/dev/sda'.",
        "Nwipe was aborted by the user",
    ],
)
def test_model_text_cannot_spoof_skip_or_abort(message):
    log = f"info: Model: {message}\n" + STATUS + ERASED

    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[0] is True


def test_explicit_legacy_pipe_failure_still_blocks_completion():
    log = "|/dev/sda| 100.00% |-FAILED-|\n"

    assert _target_reported_failure(log, "/dev/sda")


def test_model_text_cannot_start_error_summary_for_completion():
    log = "info: Model: Error Summary\n" + STATUS + ERASED

    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[0] is True


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("/dev/sda is reported as IN USE", "occupied"),
        ("/dev/sda is IN USE but --force is not set, not wiping it", "occupied"),
        ("Unable to open device '/dev/sda'.", "open_failed"),
        ("No sane device geometry for '/dev/sda'.", "geometry_unusable"),
        ("Nwipe was aborted by the user", "interrupted"),
        ("/dev/sda: >>> FAILURE! <<<", "engine_failed"),
        ("Verification mismatch on '/dev/sda' at offset 1", "verification_failed"),
    ],
)
def test_prefixed_engine_failure_records_remain_attributed(message, reason):
    log = f"[2026/09/24 12:00:00] warning: {message}\n"

    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[2] == reason
