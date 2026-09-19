# SPDX-License-Identifier: GPL-3.0-or-later
"""Familiar decimal TB/GB capacity and explicit Type unknown. Fake disks only."""

from __future__ import annotations

from beamo_wipe.copy import KIND_UNKNOWN, kind_label
from beamo_wipe.demo import discovery_for_scenario, make_demo_wizard
from beamo_wipe.discover import classify_kind, size_gb_label
from beamo_wipe.gallery import gallery_html
from beamo_wipe.identity import present_disk
from beamo_wipe.inventory import comparison_text
from beamo_wipe.models import Disk, DiskKind, Screen, capacity_phrase
from beamo_wipe.safety import confirm_spec, listed_disks, same_size_conflict
from beamo_wipe.ui import console_wizard as console


def _disk(size_bytes: int, **changes) -> Disk:
    data = dict(
        path="/dev/sda",
        name="sda",
        model="Example",
        serial="SERIAL1",
        size_bytes=size_bytes,
        size_gb_label=size_gb_label(size_bytes),
        kind=DiskKind.SSD,
        bus="SATA",
        label="",
    )
    data.update(changes)
    if "size_gb_label" not in changes:
        data["size_gb_label"] = size_gb_label(data["size_bytes"])
    return Disk(**data)


def test_unknown_kind_is_labeled_type_unknown():
    assert kind_label(DiskKind.UNKNOWN) == KIND_UNKNOWN
    assert kind_label(DiskKind.HDD) == "Hard disk"
    assert kind_label(DiskKind.SSD) == "SSD"
    assert kind_label(DiskKind.NVME) == "SSD"
    view = present_disk(_disk(16_000_000_000, kind=DiskKind.UNKNOWN))
    assert view.kind_chip == KIND_UNKNOWN
    assert KIND_UNKNOWN in view.announcement
    assert classify_kind("sda", "sata", None) == DiskKind.UNKNOWN
    assert classify_kind("sda", "sata", "bogus") == DiskKind.UNKNOWN


def test_large_disks_use_tb_and_keep_exact_decimal_gb():
    one_tb = _disk(1_000_000_000_000)
    assert one_tb.size_gb_label == "1000"
    assert one_tb.size_phrase == "1 TB (1000 GB)"
    assert present_disk(one_tb).capacity == "1 TB (1000 GB)"
    assert confirm_spec(one_tb, [one_tb]).token == "1000"
    assert "1000" in confirm_spec(one_tb, [one_tb]).prompt

    two_tb = _disk(2_000_000_000_000)
    assert two_tb.size_phrase == "2 TB (2000 GB)"
    assert confirm_spec(two_tb, [two_tb]).token == "2000"

    one_and_half = _disk(1_500_000_000_000)
    assert one_and_half.size_gb_label == "1500"
    assert one_and_half.size_phrase == "1.5 TB (1500 GB)"


def test_boundary_sizes_do_not_collide_after_tb_formatting():
    gb256 = _disk(256_060_514_304)
    gb999 = _disk(999_000_000_000)
    gb1000 = _disk(1_000_000_000_000)
    gb1001 = _disk(1_001_000_000_000)
    gb1999 = _disk(1_999_000_000_000)
    gb2000 = _disk(2_000_000_000_000)
    assert gb256.size_phrase == "256 GB"
    assert gb999.size_phrase == "999 GB"
    assert gb1000.size_phrase == "1 TB (1000 GB)"
    assert gb1001.size_phrase == "1001 GB"
    assert gb1999.size_phrase == "1999 GB"
    assert gb2000.size_phrase == "2 TB (2000 GB)"
    assert gb1000.size_phrase != gb1001.size_phrase
    assert gb1999.size_phrase != gb2000.size_phrase
    assert not same_size_conflict([gb1999, gb2000])
    assert confirm_spec(gb1999, [gb1999, gb2000]).token == "1999"
    assert confirm_spec(gb2000, [gb1999, gb2000]).token == "2000"
    # Binary 10 GiB stays decimal 11 GB, not 10 GB.
    assert _disk(10_737_418_240).size_phrase == "11 GB"


def test_malformed_and_zero_capacity_stay_honest():
    assert capacity_phrase("0") == "0 GB"
    assert capacity_phrase("") == "Capacity unknown"
    assert capacity_phrase("12.5") == "Capacity unknown"
    assert capacity_phrase("1,000") == "Capacity unknown"
    assert capacity_phrase("-3") == "Capacity unknown"
    assert _disk(0).size_phrase == "0 GB"
    assert "GiB" not in capacity_phrase("1000")
    assert "TB" in capacity_phrase("1000") and "1000 GB" in capacity_phrase("1000")


def test_reports_comparison_gallery_and_console_use_the_same_capacity():
    html = gallery_html()
    result = discovery_for_scenario("happy")
    listed = listed_disks(result)
    sda = next(d for d in listed if d.path == "/dev/sda")
    assert sda.size_gb_label == "1000"
    assert sda.size_phrase == "1 TB (1000 GB)"
    text = comparison_text(result.selectable, peers=listed)
    assert "Capacity: 1 TB (1000 GB)" in text
    assert "Capacity: 256 GB" in text
    assert "1 TB (1000 GB)" in html


def test_plain_console_shows_tb_and_type_unknown(monkeypatch, capsys):
    wiz = make_demo_wizard()
    wiz.screen = Screen.PICK
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wiz)
    output = capsys.readouterr().out
    assert "1 TB (1000 GB)" in output
    assert "256 GB" in output
    assert not wiz.runner.started


def test_unknown_kind_does_not_change_eligibility():
    result = discovery_for_scenario("happy")
    before = {d.path for d in result.selectable}
    unknown = present_disk(_disk(16_000_000_000, kind=DiskKind.UNKNOWN, path="/dev/sdz", name="sdz"))
    assert unknown.kind_chip == KIND_UNKNOWN
    assert {d.path for d in result.selectable} == before
