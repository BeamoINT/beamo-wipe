"""Placeholder hardware IDs must not identify protected or report USBs."""

from __future__ import annotations

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import DeviceFingerprint, select_export_volume
from test_usb_report_workflow import _partition, _root


def _baseline_boot(*, serial: str = "UNKNOWN", wwn: str = "N/A") -> DeviceFingerprint:
    return DeviceFingerprint(
        path="/dev/sdb",
        size_bytes=8_000_000_000,
        model="USB DISK",
        serial=serial,
        wwn=wwn,
    )


def _target(*, wwn: str = "target-wwn") -> dict:
    return _root(
        "/dev/nvme0n1",
        size=256_000_000_000,
        tran="nvme",
        model="Target",
        serial="TARGET-1",
        wwn=wwn,
    )


def _target_fingerprint(*, wwn: str = "target-wwn") -> DeviceFingerprint:
    return DeviceFingerprint(
        path="/dev/nvme0n1",
        size_bytes=256_000_000_000,
        model="Target",
        serial="TARGET-1",
        wwn=wwn,
    )


def test_relocated_placeholder_boot_usb_cannot_be_selected_as_report_usb():
    # Another same-model stick can inherit /dev/sdb while the real boot USB
    # moves to /dev/sdc. Neither placeholder proves which physical stick is
    # which, even though the reported strings happen to differ.
    payload = {
        "blockdevices": [
            _root(
                "/dev/sdb",
                size=8_000_000_000,
                tran="usb",
                model="USB DISK",
                serial="UNKNOWN",
                wwn="N/A",
                rm=1,
                hotplug=1,
            ),
            _target(),
            _root(
                "/dev/sdc",
                size=8_000_000_000,
                tran="usb",
                model="USB DISK",
                serial="0000",
                wwn="0x0000",
                rm=1,
                hotplug=1,
                children=[_partition()],
            ),
        ]
    }
    baseline = (_baseline_boot(), _target_fingerprint())

    with pytest.raises(SafetyError, match="could not be verified"):
        select_export_volume(payload, baseline)


def test_shared_placeholder_wwn_does_not_make_distinct_disks_duplicate():
    payload = {
        "blockdevices": [
            _root(
                "/dev/sdb",
                size=8_000_000_000,
                tran="usb",
                model="USB DISK",
                serial="BOOT-1",
                wwn="N/A",
                rm=1,
                hotplug=1,
            ),
            _target(wwn="N/A"),
            _root(
                "/dev/sdc",
                size=32_000_000,
                tran="usb",
                model="Report",
                serial="REPORT-1",
                wwn="report-wwn",
                rm=1,
                hotplug=1,
                children=[_partition()],
            ),
        ]
    }
    baseline = (_baseline_boot(serial="BOOT-1"), _target_fingerprint(wwn="N/A"))

    assert select_export_volume(payload, baseline).path == "/dev/sdc1"


def test_report_usb_with_same_missing_wwn_as_boot_is_still_new():
    payload = {
        "blockdevices": [
            _root(
                "/dev/sdb",
                size=8_000_000_000,
                tran="usb",
                model="Boot",
                serial="BOOT-1",
                wwn="N/A",
                rm=1,
                hotplug=1,
            ),
            _target(),
            _root(
                "/dev/sdc",
                size=32_000_000,
                tran="usb",
                model="Report",
                serial="REPORT-1",
                wwn="N/A",
                rm=1,
                hotplug=1,
                children=[_partition()],
            ),
        ]
    }
    baseline = (
        DeviceFingerprint("/dev/sdb", 8_000_000_000, "Boot", "BOOT-1", "N/A"),
        _target_fingerprint(),
    )

    assert select_export_volume(payload, baseline).path == "/dev/sdc1"
