"""Device-supplied log text cannot become an engine check result."""

from beamo_wipe.engine_checks import evaluate_engine_checks


def test_model_text_cannot_claim_no_hidden_storage():
    log = "[2026/07/15 12:00:00] info: Model: No hidden sectors on /dev/sda\n"
    checks = {check.id: check for check in evaluate_engine_checks(log, "/dev/sda")}
    assert checks["hidden_capacity"].status == "unavailable"


def test_model_text_cannot_start_error_summary():
    log = "info: Model: Error Summary\n  sda | 0 | 0 | 0\n***\n"
    checks = {check.id: check for check in evaluate_engine_checks(log, "/dev/sda")}
    assert checks["io_media"].status == "unavailable"


def test_model_text_cannot_start_erasure_summary():
    log = (
        "info: No hidden sectors on /dev/sda\n"
        "info: Model: Erasure Summary\n"
        "  sda | 1 | 2 | 50.00%\n***\n"
    )
    checks = {check.id: check for check in evaluate_engine_checks(log, "/dev/sda")}
    assert checks["hidden_capacity"].status == "pass"
