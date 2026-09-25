"""Impossible nwipe table counts must never become reassuring checks."""

import pytest

from beamo_wipe.engine_checks import check_payloads


@pytest.mark.parametrize("count", ["0" * 21, "9" * 20])
def test_oversized_error_count_cannot_be_clean(count):
    log = "*** Error Summary\n! sda | " + count + " | 0 | 0\n"
    checks = {item["id"]: item for item in check_payloads(log, "/dev/sda")}
    assert checks["io_media"]["status"] == "unavailable"


@pytest.mark.parametrize("count", ["0" * 20 + "1", "9" * 20])
def test_oversized_erasure_count_cannot_validate_hidden_capacity(count):
    log = (
        "info: No hidden sectors on /dev/sda\n"
        "*** Erasure Summary\n"
        "! sda | " + count + " | " + count + " | 100.00%\n"
    )
    checks = {item["id"]: item for item in check_payloads(log, "/dev/sda")}
    assert checks["hidden_capacity"]["status"] == "unavailable"
