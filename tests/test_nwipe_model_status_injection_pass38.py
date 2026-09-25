"""nwipe 0.42 logs libparted's model verbatim; an internal LF is data."""

from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome


DRIVE_STATUS_HEADER = (
    "********************************* Drive Status "
    "*********************************\n"
)


def test_model_newline_in_device_info_cannot_create_completion_row():
    # An ATA IDENTIFY model can contain this internal LF. Bookworm libparted's
    # strip_name() preserves it, and nwipe's initial device info log does too.
    log = (
        "[2026/09/25 11:00:00]    info: /dev/sda, ATA, X\n"
        "sda | Erased | 0B/s | 00:00:00 | X/Y\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[0] is False


def test_model_newline_in_another_status_row_cannot_complete_target():
    # The Drive Status section itself is authentic, but the second line is
    # part of /dev/sdb's 17-byte model, not a row for /dev/sda.
    log = (
        DRIVE_STATUS_HEADER
        + "      sdb | Erased | 0B/s | 00:00:00 | X\n"
        + "sda | Erased |\n"
        + "********************************************************************************\n"
    )
    assert evaluate_nwipe_outcome(0, log, "/dev/sda")[0] is False


def test_complete_status_row_in_status_section_still_confirms_completion():
    log = (
        DRIVE_STATUS_HEADER
        + "      sda | Erased | 120MB/s | 00:01:00 | QEMU/DISK\n"
        + "********************************************************************************\n"
    )
    assert evaluate_nwipe_outcome(0, log, "/dev/sda") == (
        True, "finished", "completed"
    )
