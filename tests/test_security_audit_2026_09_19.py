# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the 2026-09-19 security audit. Fake disks only."""

from __future__ import annotations

from pathlib import Path

import pytest

from beamo_wipe.safety import SafetyError

ROOT = Path(__file__).resolve().parents[1]


def _payload_with_target(*, tran, path="/dev/sda", name="sda"):
    return {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 16000000000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BOOT1",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                    }
                ],
            },
            {
                "name": name,
                "path": path,
                "size": 500107862016,
                "type": "disk",
                "tran": tran,
                "model": "Target",
                "serial": "TGT1",
            },
        ]
    }


def test_empty_or_null_scsi_tran_is_not_wipeable():
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.identity import SERIAL_LABEL
    from beamo_wipe.inventory import REASON_UNPROVEN_TRANSPORT, other_devices
    from beamo_wipe.safety import is_unproven_scsi_transport, selectable_disks

    for tran in ("", None):
        result = parse_lsblk_json(_payload_with_target(tran=tran), boot_path="/dev/sdb")
        target = next(d for d in result.disks if d.path == "/dev/sda")
        assert target.bus == "other"
        assert is_unproven_scsi_transport(target)
        assert target.path not in {d.path for d in selectable_disks(result)}
        excluded = next(
            d for d in other_devices(result) if f"{SERIAL_LABEL}: TGT1" in d.identity
        )
        assert REASON_UNPROVEN_TRANSPORT in excluded.reasons


def test_virtio_and_named_local_buses_stay_selectable():
    from beamo_wipe.discover import classify_bus, parse_lsblk_json
    from beamo_wipe.safety import selectable_disks

    assert classify_bus("virtio") == "virtio"
    result = parse_lsblk_json(
        _payload_with_target(tran="virtio", path="/dev/vda", name="vda"),
        boot_path="/dev/sdb",
    )
    assert [d.path for d in selectable_disks(result)] == ["/dev/vda"]
    sata = parse_lsblk_json(_payload_with_target(tran="sata"), boot_path="/dev/sdb")
    assert [d.path for d in selectable_disks(sata)] == ["/dev/sda"]


def test_iscsi_token_still_refused():
    from beamo_wipe.discover import parse_lsblk_json
    from beamo_wipe.safety import is_remote_disk, selectable_disks

    result = parse_lsblk_json(_payload_with_target(tran="iscsi"), boot_path="/dev/sdb")
    target = next(d for d in result.disks if d.path == "/dev/sda")
    assert is_remote_disk(target)
    assert target.path not in {d.path for d in selectable_disks(result)}


def test_scsi_sysfs_iscsi_path_is_refused_off_preview(monkeypatch):
    from beamo_wipe.safety import assert_local_device_transport

    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)

    import os as os_mod

    os_realpath = os_mod.path.realpath

    def fake_realpath(path):
        text = str(path)
        if text == "/dev/sdz":
            return "/dev/sdz"
        if text.endswith("/sys/block/sdz/device") or text == "/sys/block/sdz/device":
            return "/sys/devices/platform/host0/iscsi_session/session1/target/0:0:0:0"
        return os_realpath(text)

    monkeypatch.setattr(os_mod.path, "realpath", fake_realpath)
    with pytest.raises(SafetyError, match="remote or unknown SCSI"):
        assert_local_device_transport("/dev/sdz")


def test_scsi_sysfs_local_ata_path_is_allowed_off_preview(monkeypatch):
    from beamo_wipe.safety import assert_local_device_transport

    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    import os as os_mod

    os_realpath = os_mod.path.realpath

    def fake_realpath(path):
        text = str(path)
        if text == "/dev/sdz":
            return "/dev/sdz"
        if text.endswith("/sys/block/sdz/device") or text == "/sys/block/sdz/device":
            return "/sys/devices/pci0000:00/0000:00:1f.2/ata1/host0/target0:0:0/0:0:0:0"
        return os_realpath(text)

    monkeypatch.setattr(os_mod.path, "realpath", fake_realpath)
    assert_local_device_transport("/dev/sdz")


def test_gallery_escapes_disk_derived_html():
    txt = (ROOT / "src/beamo_wipe/gallery.py").read_text(encoding="utf-8")
    assert "${esc(text)}" in txt
    assert "${esc(d.prompt)}" in txt
    assert "${esc(sev)}" in txt
    assert "${panel(\"warn\", d.warning)}" in txt
    assert "${d.warning}" not in txt.replace("${panel(\"warn\", d.warning)}", "")
    assert "${d.prompt}" not in txt


def test_session_exec_env_drops_loader_overrides(monkeypatch):
    from beamo_wipe.safety import session_exec_env

    monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
    monkeypatch.setenv("PYTHONPATH", "/tmp/evil-py")
    monkeypatch.setenv("DISPLAY", ":99")
    env = session_exec_env()
    assert "LD_PRELOAD" not in env
    assert "PYTHONPATH" not in env
    assert env["PATH"] == "/usr/sbin:/usr/bin:/sbin:/bin"
    assert env["DISPLAY"] == ":99"


def test_resolve_system_binary_rejects_relative_and_tmp(tmp_path, monkeypatch):
    from beamo_wipe.safety import resolve_system_binary

    monkeypatch.setattr(
        "beamo_wipe.safety.shutil.which", lambda name, path=None: str(tmp_path / name)
    )
    assert resolve_system_binary("pactl") is None
    assert resolve_system_binary("../pactl") is None
    assert resolve_system_binary("/usr/bin/pactl") is None


def test_bootloaders_lock_command_line_edits():
    isolinux = (
        ROOT / "packaging/live/config/bootloaders/isolinux/isolinux.cfg"
    ).read_text(encoding="utf-8")
    grub_cfg = (
        ROOT / "packaging/live/config/bootloaders/grub-pc/config.cfg"
    ).read_text(encoding="utf-8")
    grub_menu = (
        ROOT / "packaging/live/config/bootloaders/grub-pc/grub.cfg"
    ).read_text(encoding="utf-8")
    assert "NOESCAPE 1" in isolinux
    assert "ALLOWOPTIONS 0" in isolinux
    assert 'set superusers="beamo"' in grub_cfg
    assert "--unrestricted" in grub_menu
    assert grub_menu.count("--unrestricted") >= 3


def test_kiosk_cmdline_parse_disables_globbing():
    text = (
        ROOT
        / "packaging/live/config/includes.chroot/usr/local/sbin/beamo-wipe-kiosk"
    ).read_text(encoding="utf-8")
    assert "set -f" in text.split("boot_ui_mode()")[1].split("UI_MODE=")[0]


def test_qr_rejects_non_support_payload():
    from beamo_wipe import support_contact as sc

    with pytest.raises(ValueError, match="verified support URL"):
        sc.qr_matrix("https://evil.example")
    with pytest.raises(ValueError, match="verified support URL"):
        sc.qr_svg("/dev/sda")
    assert sc.qr_matrix() == sc.qr_matrix(sc.SUPPORT_URL)
