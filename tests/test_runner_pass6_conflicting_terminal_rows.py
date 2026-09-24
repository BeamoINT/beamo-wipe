"""Conflicting nwipe terminal rows must never become an erase success."""

from beamo_wipe.methods import MethodId
from beamo_wipe.nwipe_runner import completion_for_method, evaluate_nwipe_outcome


def test_shared_failed_status_blocks_final_progress_success():
    target = "/dev/sdabcdef"
    foreign = "/dev/sdxsdabcdef"
    log = (
        f"{foreign}: selected\n"
        f"{target}: 100.00%, round 1 of 1, pass 1 of 1, "
        "eta 00:00:00, [verifying]\n"
        "! sdabcdef |-FAILED-|\n"
    )
    assert completion_for_method(0, log, target, MethodId.EVERYDAY)[0] is False


def test_nonzero_error_summary_blocks_erased_status_success():
    target = "/dev/sda"
    log = (
        "Error Summary\n"
        "      sda | 1 | 0 | 0\n"
        "***\n"
        "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, log, target)[0] is False


def test_shared_nonzero_error_count_blocks_final_progress_success():
    target = "/dev/sdabcdef"
    foreign = "/dev/sdxsdabcdef"
    log = (
        f"{foreign}: selected\n"
        f"{target}: 100.00%, round 1 of 1, pass 1 of 1, "
        "eta 00:00:00, [verifying]\n"
        "Error Summary\n"
        " sdabcdef | 1 | 0 | 0\n"
        "***\n"
    )
    assert completion_for_method(0, log, target, MethodId.EVERYDAY)[0] is False


def test_zero_error_summary_keeps_erased_status_success():
    target = "/dev/sda"
    log = (
        "Error Summary\n"
        "      sda | 0 | 0 | 0\n"
        "***\n"
        "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, log, target) == (
        True,
        "finished",
        "completed",
    )


def test_malformed_target_error_row_cannot_be_overruled_by_erased_status():
    log = (
        "Error Summary\n"
        "      sda | unknown | 0 | 0\n"
        "***\n"
        "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[2] == "indeterminate"


def test_foreign_error_row_does_not_override_target_erased_status():
    log = (
        "Error Summary\n"
        "      sdb | 1 | 0 | 0\n"
        "***\n"
        "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[0] is True


def test_oversized_error_count_is_indeterminate_instead_of_crashing():
    log = (
        "Error Summary\n"
        f"      sda | {'9' * 5000} | 0 | 0\n"
        "***\n"
        "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[2] == "indeterminate"
