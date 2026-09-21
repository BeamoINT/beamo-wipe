# SPDX-License-Identifier: GPL-3.0-or-later
"""Size labels must use decimal GB with half-up rounding, never banker's rounding."""

from beamo_wipe.discover import size_gb_label
from beamo_wipe.models import Disk, DiskKind
from beamo_wipe.safety import confirm_spec, same_size_conflict


def _disk(name: str, size_bytes: int) -> Disk:
    return Disk(
        path=f"/dev/{name}",
        name=name,
        model="Fake disk",
        serial=name.upper(),
        size_bytes=size_bytes,
        size_gb_label=size_gb_label(size_bytes),
        kind=DiskKind.SSD,
        bus="SATA",
        label="",
    )


def test_half_gb_sizes_round_half_up_not_to_even():
    # Python 3 round() is banker's rounding: 2.5 -> 2, 4.5 -> 4.
    # Displayed GB labels and confirm tokens must not inherit that.
    assert size_gb_label(1_500_000_000) == "2"
    assert size_gb_label(2_500_000_000) == "3"
    assert size_gb_label(3_500_000_000) == "4"
    assert size_gb_label(4_500_000_000) == "5"


def test_under_half_gb_is_not_labeled_one_gb():
    """Half-up to 0 must not be forced up to 1 GB.

    A 100 MB disk and a 1.0 GB disk were both shown as "1 GB" and could
    share a size confirmation token.
    """
    assert size_gb_label(1) == "0"
    assert size_gb_label(100_000_000) == "0"
    assert size_gb_label(499_999_999) == "0"
    assert size_gb_label(500_000_000) == "1"
    small = _disk("sda", 100_000_000)
    one_gb = _disk("sdb", 1_000_000_000)
    assert small.size_gb_label != one_gb.size_gb_label
    assert small.size_phrase == "under 1 GB"
    assert one_gb.size_phrase == "1 GB"
    assert not same_size_conflict([small, one_gb])
    assert confirm_spec(small, [small]).token == small.size_gb_label
    assert confirm_spec(one_gb, [one_gb]).token == "1"


def test_existing_decimal_gb_examples_stay_stable():
    assert size_gb_label(256060514304) == "256"
    assert size_gb_label(16_000_000_000) == "16"
    assert size_gb_label(10_737_418_240) == "11"
    assert size_gb_label(10_000_000_000) == "10"
    assert size_gb_label(2_499_999_999) == "2"
    assert size_gb_label(500_000_000) == "1"
    assert size_gb_label(0) == "0"


def test_distinct_near_half_gb_disks_are_not_same_size():
    smaller = _disk("sda", 1_500_000_000)
    larger = _disk("sdb", 2_500_000_000)
    assert smaller.size_gb_label != larger.size_gb_label
    assert not same_size_conflict([smaller, larger])
    assert confirm_spec(smaller, [smaller, larger]).token == "2"
    assert confirm_spec(larger, [smaller, larger]).token == "3"


def test_unique_two_and_a_half_gb_disk_confirms_with_three():
    disk = _disk("sda", 2_500_000_000)
    spec = confirm_spec(disk, [disk])
    assert disk.size_phrase == "3 GB"
    assert spec.token == "3"
    assert "3" in spec.prompt
