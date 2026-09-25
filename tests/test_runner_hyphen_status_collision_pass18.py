"""A hyphenated device path can share nwipe's eight-character status cell."""

from beamo_wipe.engine_checks import evaluate_engine_checks
from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome


TARGET = "/dev/dm-12345670"
FOREIGN = "/dev/md-12345670"


def test_foreign_hyphenated_erased_row_cannot_complete_target():
    log = f"{FOREIGN}: selected\n 12345670 | Erased |\n"
    assert evaluate_nwipe_outcome(0, log, TARGET)[0] is False


def test_foreign_hyphenated_error_row_cannot_pass_target_io_check():
    log = f"{FOREIGN}: selected\nError Summary\n 12345670 | 0 | 0 | 0\n***\n"
    checks = {check.id: check for check in evaluate_engine_checks(log, TARGET)}
    assert checks["io_media"].status == "unavailable"
