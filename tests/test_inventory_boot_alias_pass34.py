"""An alias of the protected boot medium is not an additional device."""

from dataclasses import replace

from beamo_wipe.demo import discovery_for_scenario
from beamo_wipe.inventory import count_summary, other_devices
from beamo_wipe.models import ExcludedDevice


def test_excluded_boot_alias_is_not_counted_as_other_device(tmp_path):
    boot_file = tmp_path / "boot-device"
    boot_file.write_bytes(b"")
    alias = tmp_path / "boot-alias"
    alias.symlink_to(boot_file)
    other_file = tmp_path / "other-device"
    other_file.write_bytes(b"")

    base = discovery_for_scenario("empty")
    assert base.boot is not None
    discovery = replace(
        base,
        boot=replace(base.boot, path=str(boot_file)),
        excluded=(
            ExcludedDevice("Boot alias", ("protected",), path=str(alias)),
            ExcludedDevice("Other device", ("mounted",), path=str(other_file)),
        ),
    )

    assert tuple(device.path for device in other_devices(discovery)) == (str(other_file),)
    assert "1 other device not available" in count_summary(discovery)


def test_child_of_boot_alias_is_not_counted_as_other_device(tmp_path):
    boot_file = tmp_path / "boot-device"
    boot_file.write_bytes(b"")
    boot_alias = tmp_path / "boot-alias"
    boot_alias.symlink_to(boot_file)

    base = discovery_for_scenario("empty")
    assert base.boot is not None
    discovery = replace(
        base,
        boot=replace(base.boot, path=str(boot_file)),
        excluded=(ExcludedDevice(
            "Boot partition", ("protected",),
            path=str(tmp_path / "boot-partition"), parent_path=str(boot_alias),
        ),),
    )

    assert other_devices(discovery) == ()
    assert "other device" not in count_summary(discovery)


def test_excluded_child_groups_under_aliased_parent(tmp_path):
    parent = tmp_path / "parent-device"
    parent.write_bytes(b"")
    alias = tmp_path / "parent-alias"
    alias.symlink_to(parent)
    child = tmp_path / "child-device"

    base = discovery_for_scenario("empty")
    discovery = replace(
        base,
        excluded=(
            ExcludedDevice("Parent", ("mounted",), path=str(parent)),
            ExcludedDevice("Child", ("partition",), path=str(child), parent_path=str(alias)),
        ),
    )

    shown = other_devices(discovery)
    assert len(shown) == 1
    assert shown[0].path == str(parent)
    assert tuple(device.path for device in shown[0].children) == (str(child),)
    assert "1 other device not available" in count_summary(discovery)
