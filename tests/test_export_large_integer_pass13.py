"""Malformed lsblk integer fields must fail as an export safety error."""

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import baseline_fingerprints, select_export_volume
from test_usb_report_workflow import _payload


@pytest.mark.parametrize(
    "size", [pytest.param("9" * 5000, id="long-decimal"), pytest.param(1 << 256, id="oversized-int")]
)
def test_excessively_large_size_is_rejected(size):
    payload, disks = _payload()
    payload["blockdevices"][2]["size"] = size

    with pytest.raises(SafetyError, match="size is invalid"):
        select_export_volume(payload, baseline_fingerprints(disks))
