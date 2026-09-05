"""Read-only primary-code discovery followup using synthetic probe responses."""
from types import SimpleNamespace
import importlib

import pytest

discovery = importlib.import_module("beamo_wipe.discover")


@pytest.fixture(autouse=True)
def fake_serial(monkeypatch):
    markers = []
    monkeypatch.setattr("beamo_wipe.diagnostics.emit_serial_marker", markers.append)
    return markers


def _payload():
    return {"blockdevices": [
        {"name": "sr0", "path": "/dev/sr0", "type": "rom", "size": 1000000000,
         "tran": "ata", "ro": True, "mountpoints": ["/run/live/medium"]},
        {"name": "vda", "path": "/dev/vda", "type": "disk", "size": 10000000000,
         "tran": "virtio", "ro": False, "mountpoints": [None]},
    ]}


def test_findmnt_repeated_source_rows_do_not_invent_unknown_source(monkeypatch):
    monkeypatch.setattr(discovery, "_run_findmnt", lambda _path: SimpleNamespace(
        returncode=0, stdout="/dev/sr0\n/dev/sr0\n", stderr=""))
    monkeypatch.setattr(discovery, "read_mountinfo_sources", lambda _paths: ["/dev/sr0"])
    sources = discovery.read_mount_sources(paths=["/run/live/medium"])
    result = discovery.discover(lsblk_payload=_payload(), mount_sources=sources,
                                cmdline="boot=live", env={})
    assert result.boot_identified, sources
    assert [disk.path for disk in result.selectable] == ["/dev/vda"]


def test_findmnt_single_source_with_mountinfo_duplicate_is_supported(monkeypatch):
    monkeypatch.setattr(discovery, "_run_findmnt", lambda _path: SimpleNamespace(
        returncode=0, stdout="/dev/sr0\n", stderr=""))
    monkeypatch.setattr(discovery, "read_mountinfo_sources", lambda _paths: ["/dev/sr0"])
    sources = discovery.read_mount_sources(paths=["/run/live/medium"])
    result = discovery.discover(lsblk_payload=_payload(), mount_sources=sources,
                                cmdline="boot=live", env={})
    assert result.boot_identified


@pytest.mark.parametrize("stdout", [
    "/dev/sr0\n/dev/vda\n",
    "/dev/sr0\nUUID=private-unknown-source\n",
    "/dev/sr0\n/dev/loop0\n",
])
def test_multiple_rows_keep_every_conflicting_or_unknown_source(monkeypatch, stdout):
    monkeypatch.setattr(discovery, "_run_findmnt", lambda _path: SimpleNamespace(
        returncode=0, stdout=stdout, stderr=""))
    monkeypatch.setattr(discovery, "read_mountinfo_sources", lambda _paths: ["/dev/sr0"])
    sources = discovery.read_mount_sources(paths=["/run/live/medium"])
    assert sources == stdout.splitlines()
    result = discovery.discover(lsblk_payload=_payload(), mount_sources=sources,
                                cmdline="boot=live", env={})
    assert not result.boot_identified
    assert result.selectable == ()


@pytest.mark.parametrize("stdout", ["/dev/sr0\n\n", "\n/dev/sr0\n", "/dev/sr0\r\n/dev/sr0\r\n"])
def test_empty_records_and_line_endings_do_not_invent_sources(monkeypatch, stdout):
    monkeypatch.setattr(discovery, "_run_findmnt", lambda _path: SimpleNamespace(
        returncode=0, stdout=stdout, stderr=""))
    monkeypatch.setattr(discovery, "read_mountinfo_sources", lambda _paths: [])
    assert discovery.read_mount_sources(paths=["/run/live/medium"]) == ["/dev/sr0"]


def test_boot_failure_markers_do_not_expose_source_identifiers(fake_serial):
    result = discovery.discover(lsblk_payload=_payload(),
                                mount_sources=["/dev/sr0", "UUID=private-drive-identifier"],
                                cmdline="boot=live", env={})
    assert not result.boot_identified
    assert fake_serial == ["BEAMO_WIPE_BOOT_SOURCE_UNRESOLVED", "BEAMO_WIPE_BOOT_SOURCE_TYPED"]
