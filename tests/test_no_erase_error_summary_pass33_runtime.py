"""A no-erase marker cannot override target error or failure evidence."""

import pytest

from beamo_wipe.nwipe_runner import evaluate_nwipe_outcome


@pytest.mark.parametrize(
    "guard",
    [
        "/dev/sda is reported as IN USE\n",
        "Unable to open device '/dev/sda'.\n",
        "No sane device geometry for '/dev/sda'\n",
    ],
)
@pytest.mark.parametrize(
    "contradiction",
    [
        "Error Summary\n      sda | 1 | 0 | 0\n***\n",
        "Verification mismatch on '/dev/sda' at offset 4096\n",
        "/dev/sda: >>> FAILURE! <<<\n",
    ],
)
def test_skip_marker_with_target_failure_is_indeterminate(guard, contradiction):
    assert evaluate_nwipe_outcome(0, guard + contradiction, "/dev/sda")[2] == "indeterminate"
