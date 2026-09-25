"""Regression checks for report USB discovery around existing media readers."""

from __future__ import annotations

import pytest

from beamo_wipe import support_export as export
from beamo_wipe.safety import SafetyError
from test_usb_report_workflow import _discovery, _payload, _root


def test_empty_optical_reader_does_not_block_new_report_usb_selection():
    payload, existing = _payload()
    empty_reader = _root(
        "/dev/sr0",
        size=0,
        tran="sata",
        model="Optical reader",
        serial="",
    )
    empty_reader["type"] = "rom"
    payload["blockdevices"].append(empty_reader)

    selected = export.select_export_volume(
        payload, export.baseline_fingerprints(existing)
    )

    assert selected.path == "/dev/sdc1"


def test_empty_optical_reader_does_not_block_diagnostic_baseline(monkeypatch):
    payload, existing = _payload()
    empty_reader = _root(
        "/dev/sr0", size=0, tran="sata", model="Optical reader", serial=""
    )
    empty_reader["type"] = "rom"
    initial = {"blockdevices": [*payload["blockdevices"][:2], empty_reader]}
    monkeypatch.setattr(
        "beamo_wipe.discover.discover", lambda **_kw: _discovery(existing)
    )
    rdevs = {"/dev/sdb": 11, "/dev/nvme0n1": 12}
    monkeypatch.setattr(export, "_block_rdev", rdevs.__getitem__)

    baseline = export.capture_diagnostic_baseline(scan=lambda: initial)

    assert {item.path for item in baseline} == set(rdevs)


def test_zero_size_disk_and_duplicate_empty_reader_still_fail_closed():
    payload, existing = _payload()
    payload["blockdevices"][0]["size"] = 0
    with pytest.raises(SafetyError):
        export.select_export_volume(payload, export.baseline_fingerprints(existing))

    payload, existing = _payload()
    reader = _root(
        "/dev/sr0", size=0, tran="sata", model="Optical reader", serial=""
    )
    reader["type"] = "rom"
    payload["blockdevices"].extend((reader, dict(reader)))
    with pytest.raises(SafetyError, match="duplicate"):
        export.select_export_volume(payload, export.baseline_fingerprints(existing))


@pytest.mark.parametrize("size", [0.0, False])
def test_malformed_zero_size_optical_reader_is_not_skipped(size):
    payload, existing = _payload()
    reader = _root(
        "/dev/sr0", size=size, tran="sata", model="Optical reader", serial=""
    )
    reader["type"] = "rom"
    payload["blockdevices"].append(reader)

    with pytest.raises(SafetyError):
        export.select_export_volume(payload, export.baseline_fingerprints(existing))
