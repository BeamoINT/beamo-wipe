# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #51: long disk identity must wrap, never clip or hide characters.

Tk ``wraplength`` breaks lines at spaces only, so an unbroken serial number
or device path wider than its card used to render past the edge and hide the
distinguishing tail (evidence ``docs/evidence/ux-review-20260908-native.jsonl``,
``long_identifiers``: 1192 px model and 1485 px serial requested, 840 px shown).
``_soft_break_tokens`` pre-breaks only over-wide tokens with explicit newlines.
These tests run headless: the measure callback stands in for ``font.measure``.
"""

from dataclasses import replace

import pytest

from beamo_wipe.demo import DEMO_DURATION_S, discovery_for_scenario
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard

try:
    import tkinter  # noqa: F401
except ImportError:
    pytest.skip("tkinter not available", allow_module_level=True)

from beamo_wipe.ui.tk_wizard import _soft_break_tokens

LONG_MODEL = ("External USB Bridge Adapter " * 5).strip()


def long_serial(tag: str) -> str:
    # Shared "SAME" tail collides the last-4 shortcut across the demo's
    # same-size pair, forcing the full-serial confirm token (the longest
    # prompt the product can show). Full values stay unique per disk.
    return f"SER{tag}-" + "X" * 53 + "-SAME"


def long_identity_discovery():
    """Happy-path discovery with maximum-shape identity on every disk.

    Long spaced model plus long spaceless serial, each disk distinct so
    duplicate/ambiguous-identity safety still resolves. Kernel paths stay
    intact on purpose: ``normalize_whole_disk`` fail-closed rejects anything
    else at the nwipe argv gate, so path-shaped stress belongs to display
    strings (covered above), never to the selection key.
    """
    base = discovery_for_scenario("happy")
    disks, selectable = [], []
    for index, disk in enumerate(base.disks):
        if disk in base.selectable:
            disk = replace(disk, model=LONG_MODEL, serial=long_serial(f"D{index}"))
            selectable.append(disk)
        disks.append(disk)
    return replace(base, disks=tuple(disks), selectable=tuple(selectable))


def px10(text: str) -> int:
    return len(text) * 10


def fits(text: str, measure, width: int) -> bool:
    return all(measure(line) <= width for line in text.split("\n"))


# Exact strings from the dated evidence record.
EVIDENCE_SERIAL = "SERIAL0123456789SERIAL0123456789SERIAL0123456789SERIAL0"
EVIDENCE_MODEL = "External USB Bridge Adapter External USB Bridge Adapter"


def test_spaceless_serial_breaks_to_card_width():
    broken = _soft_break_tokens(EVIDENCE_SERIAL, px10, 200)
    assert "\n" in broken
    assert fits(broken, px10, 200)


def rough_26px(text: str) -> int:
    return len(text) * 26  # ~1485 px serial, ~1326 px model


def test_evidence_measurements_fit_840_card():
    assert fits(_soft_break_tokens(EVIDENCE_SERIAL, rough_26px, 840), rough_26px, 840)
    assert fits(_soft_break_tokens(EVIDENCE_MODEL, rough_26px, 840), rough_26px, 840)


def test_maximum_valid_identifiers_fit_narrow_floor():
    serial64 = "A" * 64
    path127 = "/dev/disk/by-id/usb-LongVendor_" + "B" * 96
    model139 = ("External USB Bridge Adapter " * 5).strip()
    for raw in (serial64, path127, model139):
        broken = _soft_break_tokens(raw, px10, 200)
        assert fits(broken, px10, 200), raw[:20]
        assert broken.replace("\n", "") == raw


def test_short_text_passes_through_untouched():
    for raw in ("Samsung SSD 970 EVO", "S4EVNX0N123456", "931 GB", ""):
        assert _soft_break_tokens(raw, px10, 840) == raw


def test_only_overlong_tokens_split():
    raw = "ok model " + "Z" * 40 + " tail"
    broken = _soft_break_tokens(raw, px10, 200)
    assert fits(broken, px10, 200)
    assert broken.replace("\n", "") == raw
    assert broken.split("\n")[0].startswith("ok model")


def test_existing_paragraphs_preserved():
    raw = "first line\n" + "Q" * 30 + "\nlast"
    broken = _soft_break_tokens(raw, px10, 200)
    assert len(broken.split("\n")) >= 3
    assert broken.replace("\n", "") == raw.replace("\n", "")


def huge_glyph(text: str) -> int:
    return 999 if text else 0


def test_single_glyph_wider_than_max_terminates():
    broken = _soft_break_tokens("ABC", huge_glyph, 10)
    assert broken.replace("\n", "") == "ABC"


def test_overwide_whitespace_run_still_fits():
    broken = _soft_break_tokens("ab      cd", px10, 30)
    assert fits(broken, px10, 30)
    assert broken.replace("\n", "") == "ab      cd"


def test_nonpositive_max_px_clamps_instead_of_hanging():
    broken = _soft_break_tokens("AB", px10, 0)
    assert broken.replace("\n", "") == "AB"


def test_long_identity_stays_usable_through_last_chance():
    """Long names/serials must not break selection, token, or confirm."""
    discovery = long_identity_discovery()
    assert len(discovery.selectable) >= 2
    assert len(LONG_MODEL) == 139
    assert all(
        len(d.serial) == 64 and " " not in d.serial for d in discovery.selectable
    )
    wiz = Wizard(
        discovery,
        DryRunRunner(duration_s=DEMO_DURATION_S),
        dry_run=True,
        rediscover=lambda: discovery,
    )
    wiz.preview = True
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    target = sorted(discovery.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(target.path)
    assert wiz.selected is not None
    assert wiz.selected.serial == target.serial
    wiz.continue_pick()
    # nvme0n1 sorts first and shares its size label: the token is the full
    # 64-char serial, the longest prompt any surface must render unclipped.
    assert wiz.selected.path == "/dev/nvme0n1"
    assert len(wiz.confirm.token) == 64
    wiz.set_confirm_input(wiz.confirm.token)
    assert wiz.token_ok
    wiz.continue_confirm()
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.selected.serial == target.serial
    assert wiz.selected.model == LONG_MODEL
