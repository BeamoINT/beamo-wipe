"""Duplicate lsblk observations must not discard a disk's exclusions."""

import importlib

import pytest

from beamo_wipe.safety import SafetyError, assert_disk_identity


discovery = importlib.import_module("beamo_wipe.discover")


def disk(name, **changes):
    row = {
        "name": name, "path": f"/dev/{name}", "type": "disk",
        "size": 32_000_000_000, "model": "Fake disk", "serial": name,
        "tran": "usb", "rota": False, "ro": False,
        "mountpoints": [None], "mountpoint": None,
    }
    row.update(changes)
    return row


def probe(monkeypatch, rows):
    monkeypatch.setattr(discovery, "run_lsblk", lambda: {"blockdevices": rows})
    return discovery.discover(mount_sources=["/dev/sdb"], cmdline="", env={})


@pytest.mark.parametrize("restriction", [
    {"mountpoints": ["/media/data"]},
    {"ro": True},
    {"tran": "iscsi"},
    {"size": 0},
    {"serial": "another-physical-disk"},
])
@pytest.mark.parametrize("restricted_first", [True, False])
def test_conflicting_duplicate_disk_observations_fail_closed(monkeypatch, restriction, restricted_first):
    pair = [disk("sda", **restriction), disk("sda")]
    result = probe(monkeypatch, [disk("sdb"), *(pair if restricted_first else pair[::-1])])
    # Before the fix, a mounted/read-only/remote copy is filtered out and the
    # writable copy passes the final identity revalidation as a unique disk.
    assert not result.boot_identified
    assert result.selectable == ()


def test_identical_duplicate_observations_still_refuse_identity(monkeypatch):
    result = probe(monkeypatch, [disk("sdb"), disk("sda"), disk("sda")])
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sda", "/dev/sda"]
    with pytest.raises(SafetyError, match="safe list"):
        assert_disk_identity(result.selectable[0], result)


def test_normal_retry_after_conflicting_probe_recovers(monkeypatch):
    first = probe(monkeypatch, [disk("sdb"), disk("sda"), disk("sda", ro=True)])
    assert first.selectable == ()
    second = probe(monkeypatch, [disk("sdb"), disk("sda")])
    assert second.boot_identified
    assert [target.path for target in second.selectable] == ["/dev/sda"]


def test_conflicting_canonical_alias_is_not_a_separate_safe_target(monkeypatch):
    realpath = discovery.os.path.realpath
    monkeypatch.setattr(discovery.os.path, "realpath", lambda value: (
        "/dev/sda" if value == "/dev/disk/by-id/fake-target" else realpath(value)
    ))
    result = probe(monkeypatch, [
        disk("sdb"), disk("sda"),
        disk("sda", path="/dev/disk/by-id/fake-target", ro=True),
    ])
    assert not result.boot_identified
    assert result.selectable == ()


def test_conflicting_boot_observations_fail_closed(monkeypatch):
    result = probe(monkeypatch, [disk("sdb"), disk("sdb", serial="replacement"), disk("sda")])
    assert not result.boot_identified
    assert result.selectable == ()


def test_identical_boot_and_excluded_duplicates_preserve_target(monkeypatch):
    result = probe(monkeypatch, [
        disk("sdb"), disk("sdb"), disk("sda"),
        disk("sdc", ro=True), disk("sdc", ro=True),
    ])
    assert result.boot_identified
    assert [target.path for target in result.selectable] == ["/dev/sda"]
    assert [target.path for target in result.disks] == [
        "/dev/sdb", "/dev/sdb", "/dev/sda", "/dev/sdc", "/dev/sdc",
    ]
