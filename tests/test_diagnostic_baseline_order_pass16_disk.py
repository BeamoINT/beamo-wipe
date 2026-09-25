"""A reordered lsblk inventory is not a physical baseline change."""

import copy

import pytest

from beamo_wipe import support_export as export
from beamo_wipe.safety import SafetyError


@pytest.mark.parametrize("identity_changed", (False, True))
def test_diagnostic_baseline_compares_identity_independent_of_row_order(
    monkeypatch, identity_changed
):
    boot = {
        "name": "sdb", "path": "/dev/sdb", "type": "disk", "size": 16_000_000_000,
        "tran": "usb", "model": "Beamo", "serial": "BOOT",
        "mountpoint": None, "mountpoints": [None],
        "children": [{
            "name": "sdb1", "path": "/dev/sdb1", "type": "part",
            "pkname": "sdb", "size": 15_000_000_000,
            "mountpoint": "/run/live/medium", "mountpoints": ["/run/live/medium"],
        }],
    }
    target = {
        "name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk",
        "size": 512_000_000_000, "tran": "nvme", "model": "Target",
        "serial": "TARGET", "mountpoint": None, "mountpoints": [None],
    }
    changed_target = copy.deepcopy(target)
    if identity_changed:
        changed_target["serial"] = "REPLACED"
    scans = iter((
        {"blockdevices": [copy.deepcopy(boot), copy.deepcopy(target)]},
        {"blockdevices": [changed_target, copy.deepcopy(boot)]},
    ))
    rdevs = {"/dev/sdb": 11, "/dev/sdb1": 12, "/dev/nvme0n1": 13}
    monkeypatch.setattr(export, "_block_rdev", rdevs.__getitem__)
    monkeypatch.setattr("beamo_wipe.discover.read_mount_sources", lambda: ["/dev/sdb1"])
    monkeypatch.setattr("beamo_wipe.discover.read_cmdline", lambda: "boot=live")

    if identity_changed:
        with pytest.raises(SafetyError) as exc:
            export.capture_diagnostic_baseline(scan=lambda: next(scans))
        assert isinstance(exc.value.__cause__, SafetyError)
        assert str(exc.value.__cause__) == export.UNSTABLE_BASELINE
        return
    baseline = export.capture_diagnostic_baseline(scan=lambda: next(scans))

    assert {item.path for item in baseline} == {"/dev/sdb", "/dev/nvme0n1"}
    assert all(item.required and item.rdev > 0 for item in baseline)
