# SPDX-License-Identifier: GPL-3.0-or-later
"""Mountinfo authority checks use per-mount options, not superblock options."""

import os
from types import SimpleNamespace

import pytest

from beamo_wipe import support_export as export
from beamo_wipe.safety import SafetyError


@pytest.mark.parametrize(
    ("mount_options", "super_options", "read_only"),
    [
        ("rw,nodev,nosuid,noexec,nosymfollow", "ro", True),
        ("ro,nosuid,noexec,nosymfollow", "ro,nodev", True),
        ("ro,nodev,nosuid,noexec,nosymfollow", "rw", False),
    ],
)
def test_superblock_options_cannot_satisfy_missing_mount_options(
    tmp_path, monkeypatch, mount_options, super_options, read_only
):
    mountpoint = tmp_path / "mount"
    mountpoint.mkdir()
    source = "/dev/sdz1"
    rdev = os.makedev(8, 241)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        f"20 1 8:241 / {mountpoint} {mount_options} - vfat {source} {super_options}\n"
    )
    volume = export.ExportVolume(
        export.DeviceFingerprint("/dev/sdz", 10_000_000, "USB", "", ""),
        source, 9_000_000, "vfat", "FAT32", "1234-ABCD", rdev,
    )
    real_stat = export.os.stat

    def stat_for_mount(path, *args, **kwargs):
        if str(path) == source:
            return SimpleNamespace(st_rdev=rdev)
        if str(path) == str(mountpoint):
            return SimpleNamespace(st_dev=rdev)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(export, "MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr(export.os, "stat", stat_for_mount)
    with pytest.raises(SafetyError, match="missing required safety options"):
        export._verify_mount(mountpoint, volume, read_only=read_only)


@pytest.mark.parametrize("read_only", [False, True])
def test_complete_per_mount_options_are_accepted(tmp_path, monkeypatch, read_only):
    mountpoint = tmp_path / "mount"
    mountpoint.mkdir()
    source = "/dev/sdz1"
    rdev = os.makedev(8, 241)
    mode = "ro" if read_only else "rw"
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        f"20 1 8:241 / {mountpoint} {mode},nodev,nosuid,noexec,nosymfollow "
        f"- vfat {source} {mode}\n"
    )
    volume = export.ExportVolume(
        export.DeviceFingerprint("/dev/sdz", 10_000_000, "USB", "", ""),
        source, 9_000_000, "vfat", "FAT32", "1234-ABCD", rdev,
    )
    real_stat = export.os.stat

    def stat_for_mount(path, *args, **kwargs):
        if str(path) == source:
            return SimpleNamespace(st_rdev=rdev)
        if str(path) == str(mountpoint):
            return SimpleNamespace(st_dev=rdev)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(export, "MOUNTINFO_PATH", str(mountinfo))
    monkeypatch.setattr(export.os, "stat", stat_for_mount)
    export._verify_mount(mountpoint, volume, read_only=read_only)
