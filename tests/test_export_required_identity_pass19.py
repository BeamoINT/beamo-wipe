"""Report export must preserve every known required-disk identity field."""

from types import SimpleNamespace

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import baseline_fingerprints, select_export_volume
from test_usb_report_workflow import _payload


@pytest.mark.parametrize(
    ("disk_index", "old_serial", "old_wwn", "old_model"),
    [
        (1, "TARGET-1", "", "Target"),
        (1, "", "target-wwn", "Target"),
        (0, "BOOT-1", "", "Beamo Wipe"),
        (0, "", "boot-wwn", "Beamo Wipe"),
        (1, "TARGET-1", "target-wwn", ""),
        (0, "BOOT-1", "boot-wwn", ""),
        (1, "target-1", "target-wwn", "Target"),
        (0, "boot-1", "boot-wwn", "Beamo Wipe"),
        (1, "TARGET-1", "target-wwn", "target"),
        (0, "BOOT-1", "boot-wwn", "beamo wipe"),
    ],
)
def test_required_disk_cannot_gain_a_different_identity_at_same_path(
    disk_index: int, old_serial: str, old_wwn: str, old_model: str
) -> None:
    payload, disks = _payload()
    selected = disks[disk_index]
    prior = SimpleNamespace(
        path=selected.path,
        size_bytes=selected.size_bytes,
        model=old_model,
        serial=old_serial,
        wwn=old_wwn,
    )
    prior_disks = list(disks)
    prior_disks[disk_index] = prior
    baseline = baseline_fingerprints(prior_disks)

    with pytest.raises(SafetyError, match="Leave the Beamo"):
        select_export_volume(payload, baseline)
