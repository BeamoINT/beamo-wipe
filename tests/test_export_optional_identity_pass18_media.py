"""An already-connected USB cannot become the new report destination by ID drift."""

from types import SimpleNamespace

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import baseline_fingerprints, select_export_volume
from test_usb_report_workflow import _payload


@pytest.mark.parametrize(
    ("old_serial", "old_wwn", "current_serial", "current_wwn"),
    [
        ("REPORT-OLD", "", "REPORT-NEW", ""),
        ("REPORT-1", "old-wwn", "REPORT-1", "report-wwn"),
    ],
)
def test_same_path_optional_usb_with_changed_identifier_is_not_new(
    old_serial, old_wwn, current_serial, current_wwn
):
    payload, disks = _payload()
    current = payload["blockdevices"][2]
    current["serial"] = current_serial
    current["wwn"] = current_wwn
    previously_connected = SimpleNamespace(
        path="/dev/sdc",
        size_bytes=current["size"],
        model=current["model"],
        serial=old_serial,
        wwn=old_wwn,
    )
    baseline = baseline_fingerprints(
        (*disks, previously_connected),
        required_paths={"/dev/sdb", "/dev/nvme0n1"},
    )

    with pytest.raises(SafetyError, match="identity could not be verified"):
        select_export_volume(payload, baseline)
