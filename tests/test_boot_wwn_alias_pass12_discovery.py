"""The usual optional WWN 0x prefix cannot distinguish physical disks."""

from beamo_wipe.discover import discover
from beamo_wipe.identity import duplicate_identifier
from beamo_wipe.safety import possible_hardware_alias


def _node(name: str, *, wwn: str, bus: str = "sata") -> dict:
    return {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "tran": bus,
        "size": 512_000_000_000,
        "serial": f"SERIAL-{name}",
        "wwn": wwn,
        "children": [{
            "name": f"{name}1",
            "path": f"/dev/{name}1",
            "type": "part",
            "pkname": name,
        }],
    }


def test_boot_wwn_alias_with_optional_hex_prefix_is_not_selectable():
    result = discover(
        lsblk_payload={"blockdevices": [
            _node("sda", wwn="0x50014ee20aa00001", bus="usb"),
            _node("sdb", wwn="50014ee20aa00001"),
            _node("sdc", wwn="0x50014ee20aa00003"),
        ]},
        mount_sources=["/dev/sda1"],
        cmdline="boot=live",
        env={},
    )

    assert result.boot_identified and result.boot is not None
    assert {disk.path for disk in result.selectable} == {"/dev/sdc"}
    alias = next(disk for disk in result.disks if disk.path == "/dev/sdb")
    assert alias.is_boot
    assert possible_hardware_alias(result.boot, alias)
    assert duplicate_identifier(result.boot, result.disks)
