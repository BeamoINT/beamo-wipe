"""A malformed Erasure Summary cannot certify the hidden-capacity check."""

from beamo_wipe.engine_checks import evaluate_engine_checks


def _hidden_status(rows: str) -> str:
    log = (
        "info: No hidden sectors on /dev/sda\n"
        "************************ Erasure Summary ************************\n"
        "! Device | Bytes Erased | Bytes Total | Percentage Erased\n"
        + rows
        + "*****************************************************************\n"
    )
    return evaluate_engine_checks(log, "/dev/sda")[0].status


def test_conflicting_target_rows_cannot_pass_hidden_capacity() -> None:
    assert _hidden_status(
        "  sda | 100 | 100 | 100.00%\n"
        "! sda | 50 | 100 | 50.00%\n"
    ) == "unavailable"


def test_erased_bytes_exceeding_total_cannot_pass_hidden_capacity() -> None:
    assert _hidden_status("  sda | 200 | 100 | 200.00%\n") == "unavailable"


def test_invalid_target_percentage_cannot_pass_hidden_capacity() -> None:
    assert _hidden_status("  sda | 100 | 100 | 50.00%\n") == "unavailable"
    assert _hidden_status("  sda | 100 | 100 | unknown\n") == "unavailable"


def test_single_valid_complete_and_short_rows_keep_meaning() -> None:
    assert _hidden_status("  sda | 100 | 100 | 100.00%\n") == "pass"
    assert _hidden_status("! sda | 50 | 100 | 50.00%\n") == "warning"
