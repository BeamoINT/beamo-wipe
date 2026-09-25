"""A truncated completion tail must not hide target I/O errors."""

from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome

STATUS = "********************************* Drive Status *********************************\n"


def test_error_row_survives_when_tail_loses_table_header():
    # A bounded tail can start after "Error Summary" but still contain its
    # target row followed by the Erased status table.
    tail = (
        "      sda | 1 | 0 | 0\n"
        "********************************************************************************\n"
        + STATUS + "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, tail, "/dev/sda")[0] is False


def test_headerless_zero_row_does_not_block_erased_status():
    tail = (
        "      sda | 0 | 0 | 0\n"
        "********************************************************************************\n"
        + STATUS + "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, tail, "/dev/sda")[0] is True


def test_headerless_foreign_error_row_does_not_block_target():
    tail = (
        "      sdb | 1 | 0 | 0\n"
        "********************************************************************************\n"
        + STATUS + "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, tail, "/dev/sda")[0] is True
