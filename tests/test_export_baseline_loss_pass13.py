"""A baseline USB that loses its only ID cannot be silently ignored."""

from types import SimpleNamespace

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import baseline_fingerprints, select_export_volume
from test_usb_report_workflow import _payload, _root


@pytest.mark.parametrize(
    ("old_serial", "old_wwn", "current_serial", "current_wwn"),
    [
        ("OPTIONAL-OLD", "", "", ""),
        ("REUSED", "5000c500aabbccdd", "REUSED", ""),
    ],
)
def test_optional_baseline_losing_identifier_makes_export_uncertain(
    old_serial, old_wwn, current_serial, current_wwn
):
    payload, disks = _payload()
    payload["blockdevices"].append(
        _root(
            "/dev/sda", size=32_000_000, tran="usb", model="Old USB",
            serial=current_serial, wwn=current_wwn, rm=1, hotplug=1,
        )
    )
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Old USB",
        serial=old_serial, wwn=old_wwn,
    )
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    with pytest.raises(SafetyError, match="could not be verified"):
        select_export_volume(payload, baseline)


def test_optional_baseline_keeps_matching_wwn_when_serial_is_missing():
    payload, disks = _payload()
    payload["blockdevices"].append(
        _root(
            "/dev/sda", size=32_000_000, tran="usb", model="Old USB",
            serial="", wwn="5000c500aabbccdd", rm=1, hotplug=1,
        )
    )
    old = SimpleNamespace(
        path="/dev/sda", size_bytes=32_000_000, model="Old USB",
        serial="OPTIONAL-OLD", wwn="0x5000c500aabbccdd",
    )
    baseline = baseline_fingerprints(
        (*disks, old), required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    assert select_export_volume(payload, baseline).path == "/dev/sdc1"
