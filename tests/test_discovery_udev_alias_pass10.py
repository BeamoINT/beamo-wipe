"""A by-label source must agree with its actual device-link target."""

import os

from beamo_wipe.discover import discover


def _inventory(label_disk):
    disks = []
    for name, bus in (("sda", "sata"), ("sdb", "usb")):
        disks.append(
            {
                "name": name,
                "path": f"/dev/{name}",
                "type": "disk",
                "tran": bus,
                "size": 512_000_000_000 if name == "sda" else 16_000_000_000,
                "serial": f"SERIAL-{name}",
                "children": [
                    {
                        "name": f"{name}1",
                        "path": f"/dev/{name}1",
                        "type": "part",
                        "pkname": name,
                        "label": "LIVE" if name == label_disk else "OTHER",
                    }
                ],
            }
        )
    return {"blockdevices": disks}


def _mount_alias(monkeypatch):
    original = os.path.realpath
    alias = "/dev/disk/by-label/LIVE"
    monkeypatch.setattr(
        os.path,
        "realpath",
        lambda path: "/dev/sdb1" if str(path) == alias else original(path),
    )
    return alias


def test_by_label_value_cannot_override_disagreeing_actual_link_target(monkeypatch):
    source = _mount_alias(monkeypatch)

    result = discover(
        lsblk_payload=_inventory("sda"),
        mount_sources=[source],
        cmdline="boot=live",
        env={},
    )

    assert not result.boot_identified
    assert result.selectable == ()


def test_by_label_value_matching_actual_link_target_still_identifies_usb(monkeypatch):
    source = _mount_alias(monkeypatch)

    result = discover(
        lsblk_payload=_inventory("sdb"),
        mount_sources=[source],
        cmdline="boot=live",
        env={},
    )

    assert result.boot_identified
    assert result.boot is not None and result.boot.path == "/dev/sdb"
