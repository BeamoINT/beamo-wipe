"""An eight-column nwipe status row cannot identify colliding disk names."""

from __future__ import annotations

from beamo_wipe.engine_checks import evaluate_engine_checks
from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome


TARGET = "/dev/sdabcdef"  # exactly eight basename characters
FOREIGN = "/dev/sdxsdabcdef"  # valid whole-disk name with the same last eight
STATUS = "********************************* Drive Status *********************************\n"
ERASED_ROW = "  sdabcdef | Erased |  120MB/s | 01:25:04 | QEMU/DISK\n"


def _checks(text):
    return {check.id: check for check in evaluate_engine_checks(text, TARGET)}


def test_foreign_erased_row_does_not_complete_eight_character_target():
    text = f"{FOREIGN}: selected\n" + STATUS + ERASED_ROW
    assert evaluate_nwipe_outcome(0, text, TARGET)[0] is False


def test_foreign_zero_error_row_does_not_pass_target_io_check():
    text = f"{FOREIGN}: selected\nError Summary\n sdabcdef | 0 | 0 | 0\n***\n"
    assert _checks(text)["io_media"].status == "unavailable"


def test_shared_failure_row_is_not_attributed_to_target():
    text = f"{FOREIGN}: selected\n! sdabcdef |-FAILED-|\n"
    assert evaluate_nwipe_outcome(0, text, TARGET)[2] == "completion_missing"
    assert _checks(text)["io_media"].status == "unavailable"


def test_explicit_target_failure_remains_a_failure_with_shared_column():
    text = f"{FOREIGN}: selected\nVerification mismatch on {TARGET}\n"
    assert evaluate_nwipe_outcome(0, text, TARGET)[2] == "verification_failed"
    assert _checks(text)["io_media"].status == "fail"


def test_unshared_eight_character_target_still_accepts_own_rows():
    assert evaluate_nwipe_outcome(0, STATUS + ERASED_ROW, TARGET)[0] is True
    text = "Error Summary\n sdabcdef | 0 | 0 | 0\n***\n"
    assert _checks(text)["io_media"].status == "pass"
