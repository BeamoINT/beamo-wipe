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
    assert spec.token in spec.prompt
    assert "numbers" in spec.prompt
    assert "serial number" not in spec.prompt.lower()


def test_duplicate_size_uses_serial_suffix():
    d = _disc("lsblk_same_size.json", "/dev/sdb")
    disks = selectable_disks(d)
    assert disks[0].size_gb_label == disks[1].size_gb_label
    spec0 = confirm_spec(disks[0], disks)
    spec1 = confirm_spec(disks[1], disks)
    assert spec0.token == disks[0].serial[-4:]
    assert spec1.token == disks[1].serial[-4:]
    assert spec0.token != spec1.token
    assert "4 characters" in spec0.prompt
    assert spec0.token in spec0.prompt
    assert "serial number" not in spec0.prompt.lower()
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


def test_empty_serial_does_not_share_token_with_peer_serial():
    """A disk named sda and a peer whose serial is 'sda' must not share a token."""
    from beamo_wipe.models import Disk, DiskKind

    unnamed = Disk(
        path="/dev/sda",
        name="sda",
        model="A",
        serial="",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    named_serial = Disk(
        path="/dev/sdb",
        name="sdb",
        model="B",
        serial="sda",
        size_bytes=500_000_000_000,
        size_gb_label="500",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    spec_a = confirm_spec(unnamed, [unnamed, named_serial])
    spec_b = confirm_spec(named_serial, [unnamed, named_serial])
    assert spec_a.token.casefold() != spec_b.token.casefold()
    assert not token_matches(spec_a.token, spec_b)
    assert not token_matches(spec_b.token, spec_a)


def test_confirm_token_disambiguates_boot_usb_same_size():
    """The pick list shows the boot USB. A matching size must not use '16'."""
    from beamo_wipe.models import Disk, DiskKind
    from beamo_wipe.safety import listed_disks, same_size_conflict
    from beamo_wipe.models import DiscoveryResult

    boot = Disk(
        path="/dev/sdb",
        name="sdb",
        model="Beamo Wipe",
        serial="BEAMOUSB001",
        size_bytes=16_000_000_000,
        size_gb_label="16",
        kind=DiskKind.HDD,
        bus="USB",
        label="BEAMO_WIPE",
        is_boot=True,
    )
    hdd = Disk(
        path="/dev/sda",
        name="sda",
        model="ST16",
        serial="HDDSERIAL99",
        size_bytes=16_000_000_000,
        size_gb_label="16",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
        is_boot=False,
    )
    discovery = DiscoveryResult(
        disks=(boot, hdd),
        selectable=(hdd,),
        boot=boot,
        error=None,
        boot_identified=True,
    )
    shown = listed_disks(discovery)
    spec = confirm_spec(hdd, shown)
    assert spec.token != "16"
    assert spec.token == "AL99"
    assert same_size_conflict(shown)
    assert token_matches("al99", spec)
    assert not token_matches("16", spec)
