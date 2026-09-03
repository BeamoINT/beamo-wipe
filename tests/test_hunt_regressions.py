# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for independently validated hunt findings.

Fake data only. Fail-closed boundaries pinned alongside each fix so a
future change cannot silently weaken them.
"""

from __future__ import annotations

from beamo_wipe.discover import _as_bool, classify_bus, classify_kind
from beamo_wipe.models import DiskKind


def test_bus_fallback_never_carries_control_chars_or_unbounded_length():
    bus = classify_bus("usb\x1b[31m")
    assert "\x1b" not in bus
    assert all(ord(ch) >= 0x20 and ord(ch) != 0x7F for ch in bus)
    long_bus = classify_bus("x" * 256)
    assert len(long_bus) <= 32
    assert classify_bus(" mystery ") == "MYSTERY"


def test_bus_fallback_stays_load_bearing_for_remote_detection():
    """is_remote_disk depends on the upper() fallback via casefold.

    A fallback of UNKNOWN/"other" would make iSCSI/FC/NBD wipeable.
    """
    from beamo_wipe.models import Disk
    from beamo_wipe.safety import REMOTE_BUS_TOKENS, is_remote_disk

    for token in sorted(REMOTE_BUS_TOKENS):
        disk = Disk(
            path="/dev/sdx",
            name="sdx",
            model="M",
            serial="S",
            size_bytes=1000,
            size_gb_label="1",
            kind=DiskKind.UNKNOWN,
            bus=classify_bus(token),
            label="",
        )
        assert is_remote_disk(disk), token


def test_as_bool_accepts_padded_and_case_variants_without_widening():
    assert _as_bool(" 1") is True
    assert _as_bool("TRUE") is True
    assert _as_bool("True ") is True
    assert _as_bool(" 0 ") is False
    assert _as_bool("FALSE") is False
    # Same accepted set as before, only normalized: no new coercions.
    assert _as_bool("yes") is None
    assert _as_bool("no") is None
    assert _as_bool("") is None
    assert _as_bool(None) is None
    assert _as_bool(2) is None
    assert classify_kind("sda", "sata", " 1") == DiskKind.HDD
    assert classify_kind("sda", "sata", " 0 ") == DiskKind.SSD
    assert classify_kind("sda", "sata", "bogus") == DiskKind.UNKNOWN


def test_countdown_display_never_zero_while_gate_blocks():
    from beamo_wipe.demo import make_demo_wizard

    wiz = make_demo_wizard(scenario="happy")
    wiz.preview = False
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    base = wiz.now
    wiz._clock = lambda: base
    wiz._erase_until = base + 0.001
    assert not wiz.erase_enabled
    assert wiz.countdown_display >= 1
    wiz._erase_until = base - 0.001
    assert wiz.erase_enabled
    assert wiz.countdown_display == 0
