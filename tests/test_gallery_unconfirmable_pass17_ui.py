# SPDX-License-Identifier: GPL-3.0-or-later
"""The click-through must never present a tokenless disk as selectable."""

from beamo_wipe import gallery
from beamo_wipe.safety import SafetyError


def test_gallery_blocks_disk_when_confirmation_spec_cannot_be_built(monkeypatch):
    def refused(*_args, **_kwargs):
        raise SafetyError("ambiguous disk identity")

    monkeypatch.setattr(gallery, "confirm_spec", refused)
    disks = gallery._disks_payload("happy")
    assert any(not disk["isBoot"] for disk in disks)
    assert all(not disk["eligible"] for disk in disks if not disk["isBoot"])


def test_gallery_normal_fake_disks_retain_real_confirmation_tokens():
    disks = gallery._disks_payload("happy")
    eligible = [disk for disk in disks if disk["eligible"]]
    assert eligible
    assert all(disk["token"] and disk["prompt"] for disk in eligible)
