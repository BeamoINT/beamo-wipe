# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.safety import confirm_spec, selectable_disks, token_matches

FIXTURES = Path(__file__).parent / "fixtures"


def _disc(name: str, boot: str):
    payload = load_lsblk_json_text((FIXTURES / name).read_text(encoding="utf-8"))
    return discover(
        lsblk_payload=payload,
        boot_path=boot,
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )


def test_unique_size_uses_gb_label():
    d = _disc("lsblk_vm_iso.json", "/dev/sr0")
    disk = selectable_disks(d)[0]
    spec = confirm_spec(disk, selectable_disks(d))
    assert spec.token == disk.size_gb_label
    assert token_matches(spec.token, spec)
    assert token_matches(" " + spec.token + " ", spec)
    assert not token_matches("999", spec)


def test_duplicate_size_uses_serial_suffix():
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disks = selectable_disks(d)
    assert disks[0].size_gb_label == disks[1].size_gb_label
    spec0 = confirm_spec(disks[0], disks)
    spec1 = confirm_spec(disks[1], disks)
    assert spec0.token == disks[0].serial[-4:]
    assert spec1.token == disks[1].serial[-4:]
    assert spec0.token != spec1.token
    assert token_matches(spec0.token.lower(), spec0)
    assert not token_matches(spec0.token, spec1)
    assert not token_matches(disks[0].size_gb_label, spec0)


def test_same_size_colliding_serial_suffix_uses_device_name():
    from beamo_wipe.models import Disk, DiskKind

    d1 = Disk(
        path="/dev/sda",
        name="sda",
        model="A",
        serial="AAAA1234",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    d2 = Disk(
        path="/dev/sdb",
        name="sdb",
        model="B",
        serial="BBBB1234",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    spec1 = confirm_spec(d1, [d1, d2])
    spec2 = confirm_spec(d2, [d1, d2])
    assert spec1.token != spec2.token
    assert not token_matches(spec1.token, spec2)
    assert spec1.token in {"sda", "AAAA1234"}
    assert spec2.token in {"sdb", "BBBB1234"}
