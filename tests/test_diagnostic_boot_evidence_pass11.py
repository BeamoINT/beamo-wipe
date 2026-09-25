"""Diagnostic export must reidentify the live USB from real boot evidence."""

import pytest

from beamo_wipe import discover as discovery
from beamo_wipe import support_export as export
from beamo_wipe.safety import SafetyError
from test_usb_report_workflow import _partition, _payload


def _initial_inventory():
    payload, _ = _payload()
    payload["blockdevices"] = payload["blockdevices"][:2]
    payload["blockdevices"][0]["children"] = [
        _partition("/dev/sdb1", pkname="sdb", mounted=True)
    ]
    return payload


def _fake_rdev(monkeypatch):
    devices = {"/dev/sdb": 11, "/dev/sdb1": 12, "/dev/nvme0n1": 13}
    monkeypatch.setattr(export, "_block_rdev", devices.__getitem__)


def test_diagnostic_baseline_uses_live_mount_to_find_unlabeled_boot_usb(monkeypatch):
    payload = _initial_inventory()
    _fake_rdev(monkeypatch)
    monkeypatch.setattr(discovery, "read_mount_sources", lambda: ["/dev/sdb1"])
    monkeypatch.setattr(discovery, "read_cmdline", lambda: "boot=live")
    monkeypatch.delenv("BEAMO_WIPE_BOOT_DEVICE", raising=False)

    baseline = export.capture_diagnostic_baseline(scan=lambda: payload)

    assert {item.path for item in baseline} == {"/dev/sdb", "/dev/nvme0n1"}


def test_diagnostic_baseline_rejects_test_only_boot_override(monkeypatch):
    payload = _initial_inventory()
    _fake_rdev(monkeypatch)
    monkeypatch.setattr(discovery, "read_mount_sources", list)
    monkeypatch.setattr(discovery, "read_cmdline", str)
    monkeypatch.setenv("BEAMO_WIPE_BOOT_DEVICE", "/dev/nvme0n1")

    with pytest.raises(SafetyError, match="boot USB"):
        export.capture_diagnostic_baseline(scan=lambda: payload)
