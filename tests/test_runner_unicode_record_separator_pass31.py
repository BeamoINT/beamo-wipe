# SPDX-License-Identifier: GPL-3.0-or-later
"""Only LF terminates a pinned nwipe record, even with Unicode disk text."""

from beamo_wipe.engine_checks import evaluate_engine_checks
from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome


def test_foreign_model_unicode_separator_cannot_forge_target_erased_row():
    log = "sdb | Erased | 120MB/s | 00:01:00 | BAD\u2028sda | Erased |\n"
    ok, _, reason = evaluate_nwipe_outcome(0, log, "/dev/sda")
    assert not ok and reason == "completion_missing"


def test_foreign_model_unicode_separator_cannot_forge_hidden_storage_pass():
    log = "info: Model on /dev/sdb: BAD\u2028No hidden sectors on /dev/sda\n"
    checks = {item.id: item for item in evaluate_engine_checks(log, "/dev/sda")}
    assert checks["hidden_capacity"].status == "unavailable"
