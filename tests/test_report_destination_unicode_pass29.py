# SPDX-License-Identifier: GPL-3.0-or-later
"""A removable device model must not split the owner-facing save receipt."""

from __future__ import annotations

from dataclasses import replace

import pytest

from beamo_wipe.support_export import (
    GENERIC_DESTINATION,
    baseline_fingerprints,
    build_success_receipt,
    destination_label_for,
    present_export_receipt,
    receipt_is_saved,
    select_export_volume,
)
from test_usb_report_workflow import _payload


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_usb_model_cannot_add_a_line_to_success_receipt(separator):
    payload, disks = _payload()
    payload["blockdevices"][2]["model"] = (
        "USB" + separator + "Safe to remove the target disk"
    )
    volume = select_export_volume(payload, baseline_fingerprints(disks))
    receipt = build_success_receipt(
        evidence_sha256="a" * 64,
        session_name="report-" + "a" * 24,
        log_status="complete",
        volume=volume,
        privacy_reduced=False,
        diagnostic=False,
    )

    assert receipt_is_saved(receipt, expected_sha256="a" * 64)
    assert receipt.destination_label == destination_label_for("", 32_000_000)
    assert receipt.destination_label.startswith(GENERIC_DESTINATION)
    assert len(present_export_receipt(receipt).splitlines()) == 4


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_receipt_validation_rejects_unicode_line_breaks(separator):
    payload, disks = _payload()
    volume = select_export_volume(payload, baseline_fingerprints(disks))
    receipt = build_success_receipt(
        evidence_sha256="a" * 64,
        session_name="report-" + "a" * 24,
        log_status="complete",
        volume=volume,
        privacy_reduced=False,
        diagnostic=False,
    )
    forged = replace(receipt, destination_label="USB" + separator + "Safe to remove")
    assert not receipt_is_saved(forged, expected_sha256="a" * 64)
