"""Contradictory engine activity cannot support a no-erase outcome."""

import pytest

from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome


PROGRESS = "/dev/sda: 5.00%, round 1 of 1, pass 1 of 1, eta 00:30:00, [writing]\n"


@pytest.mark.parametrize(
    "guard,reason",
    [
        (
            "/dev/sda is IN USE but --force is not set, not wiping it\n",
            "occupied",
        ),
        ("Unable to open device '/dev/sda'.\n", "open_failed"),
        ("/dev/sda: No sane device geometry\n", "geometry_unusable"),
    ],
)
def test_progress_prevents_contradictory_no_erase_result(guard, reason):
    ok, _summary, actual = evaluate_nwipe_outcome(0, guard + PROGRESS, "/dev/sda")
    assert not ok
    assert actual == "indeterminate", (reason, actual)


def test_busy_plus_erased_row_does_not_claim_no_erasure():
    text = (
        "/dev/sda is IN USE but --force is not set, not wiping it\n"
        "      sda | Erased |  120MB/s | 01:25:04 | TEST/DISK\n"
    )
    assert evaluate_nwipe_outcome(0, text, "/dev/sda")[2] == "indeterminate"


def test_busy_without_activity_remains_occupied():
    text = "/dev/sda is IN USE but --force is not set, not wiping it\n"
    assert evaluate_nwipe_outcome(0, text, "/dev/sda")[2] == "occupied"
