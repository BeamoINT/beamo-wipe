# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for the shipped second-USB report workflow.

Every device and process boundary is fake here.  The actual FAT32 loop-device
exercise is confined to scripts/qemu-verify.sh on isolated x86_64 Linux.
"""

from __future__ import annotations

import json
import hashlib
import fcntl
import os
import re
import stat
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from beamo_wipe.evidence import write_evidence_atomic
from beamo_wipe.discover import node_to_disk
from beamo_wipe.models import Disk, DiskKind, DiscoveryResult, Screen, WipeResult
from beamo_wipe.safety import CLEAN_SUBPROCESS_ENV, SafetyError, confirm_spec
from beamo_wipe.support_export import (
    DeviceFingerprint,
    ExportVolume,
    ExportReceipt,
    VerifiedEvidence,
    baseline_fingerprints,
    export_to_new_usb,
    prepare_terminal_evidence,
    read_export_log,
    select_export_volume,
    verify_report_bundle,
    write_report_bundle,
)
from beamo_wipe.wizard import Wizard, make_demo_wizard


def _root(
    path: str,
    *,
    size: int,
    tran: str,
    model: str,
    serial: str,
    wwn: str = "",
    rm: object = 0,
    hotplug: object = 0,
    ro: object = 0,
    fstype: object = None,
    fsver: object = None,
    uuid: object = None,
    children: object = None,
) -> dict:
    return {
        "name": path.removeprefix("/dev/"),
        "path": path,
        "size": size,
        "type": "disk",
        "tran": tran,
        "model": model,
        "serial": serial,
        "wwn": wwn,
        "rm": rm,
        "hotplug": hotplug,
        "ro": ro,
        "fstype": fstype,
        "fsver": fsver,
        "uuid": uuid,
        "mountpoints": [],
        "mountpoint": None,
        "children": [] if children is None else children,
    }


def _partition(
    path: str = "/dev/sdc1",
    *,
    fstype: object = "vfat",
    uuid: object = "ABCD-1234",
    ro: object = 0,
    mounted: bool = False,
    pkname: object = "sdc",
    fsver: object = "FAT32",
) -> dict:
    return {
        "name": path.removeprefix("/dev/"),
        "path": path,
        "size": 31_000_000,
        "type": "part",
        "tran": None,
        "model": None,
        "serial": None,
        "wwn": None,
        "ro": ro,
        "fstype": fstype,
        "fsver": fsver,
        "pkname": pkname,
        "uuid": uuid,
        "mountpoints": ["/media/report"] if mounted else [],
        "mountpoint": "/media/report" if mounted else None,
        "children": [],
    }


def _payload(*extra: dict) -> tuple[dict, tuple]:
    boot = _root(
        "/dev/sdb",
        size=16_000_000_000,
        tran="usb",
        model="Beamo Wipe",
        serial="BOOT-1",
        wwn="boot-wwn",
        rm=1,
        hotplug=1,
    )
    target = _root(
        "/dev/nvme0n1",
        size=256_000_000_000,
        tran="nvme",
        model="Target",
        serial="TARGET-1",
        wwn="target-wwn",
    )
    candidate = _root(
        "/dev/sdc",
        size=32_000_000,
        tran="usb",
        model="Report USB",
        serial="REPORT-1",
        wwn="report-wwn",
        rm=1,
        hotplug=1,
        children=[_partition()],
    )
    baseline = (
        SimpleNamespace(path="/dev/sdb", size_bytes=16_000_000_000, model="Beamo Wipe", serial="BOOT-1", wwn="boot-wwn"),
        SimpleNamespace(path="/dev/nvme0n1", size_bytes=256_000_000_000, model="Target", serial="TARGET-1", wwn="target-wwn"),
    )
    return {"blockdevices": [boot, target, candidate, *extra]}, baseline


def _discovery(baseline_disks) -> DiscoveryResult:
    disks = tuple(
        Disk(
            path=item.path,
            name=Path(item.path).name,
            model=item.model,
            serial=item.serial,
            size_bytes=item.size_bytes,
            size_gb_label="1",
            kind=DiskKind.UNKNOWN,
            bus="USB" if item.path == "/dev/sdb" else "NVMe",
            label="",
            is_boot=item.path == "/dev/sdb",
            wwn=item.wwn,
        )
        for item in baseline_disks
    )
    return DiscoveryResult(
        disks=disks,
        selectable=(disks[1],),
        boot=disks[0],
        boot_identified=True,
    )


def test_selects_exactly_one_new_unmounted_fat32_usb():
    payload, disks = _payload()
    volume = select_export_volume(payload, baseline_fingerprints(disks))
    assert volume.path == "/dev/sdc1"
    assert volume.parent.path == "/dev/sdc"
    assert volume.fstype == "vfat"
    assert volume.uuid == "ABCD-1234"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda p: p["blockdevices"].pop(), "exactly one"),
        (lambda p: p["blockdevices"][2].__setitem__("rm", None), "metadata"),
        (lambda p: p["blockdevices"][2].__setitem__("hotplug", 0), "removable"),
        (lambda p: p["blockdevices"][2].__setitem__("ro", 1), "writable"),
        (lambda p: p["blockdevices"][2]["children"][0].__setitem__("mountpoints", ["/media/x"]), "mounted"),
        (lambda p: p["blockdevices"][2]["children"][0].__setitem__("fstype", "ext4"), "FAT32"),
        (lambda p: p["blockdevices"][2]["children"][0].__setitem__("fsver", "FAT16"), "FAT32"),
        (lambda p: p["blockdevices"][2]["children"].append(_partition("/dev/sdc2")), "exactly one"),
        (lambda p: p["blockdevices"][2]["children"][0].__setitem__("path", "/dev/sdb1"), "parent"),
        (lambda p: p["blockdevices"][2]["children"][0].__setitem__("pkname", "sdb"), "parent"),
        (lambda p: p["blockdevices"][2]["children"][0].__setitem__("uuid", None), "metadata"),
        (lambda p: p["blockdevices"][0].__setitem__("serial", "changed"), "Leave the Beamo"),
        (lambda p: p["blockdevices"][2].__setitem__("wwn", "boot-wwn"), "exactly one"),
    ],
)
def test_report_usb_malformed_duplicate_or_unsafe_fails_closed(mutation, message):
    payload, disks = _payload()
    mutation(payload)
    with pytest.raises(SafetyError, match=message):
        select_export_volume(payload, baseline_fingerprints(disks))


def test_multiple_new_usb_devices_are_ambiguous():
    another = _root(
        "/dev/sdd",
        size=64_000_000,
        tran="usb",
        model="Another",
        serial="REPORT-2",
        rm=1,
        hotplug=1,
        children=[_partition("/dev/sdd1", uuid="EEEE-FFFF")],
    )
    payload, disks = _payload(another)
    with pytest.raises(SafetyError, match="exactly one"):
        select_export_volume(payload, baseline_fingerprints(disks))


def test_optical_boot_remains_present_but_is_never_an_export_candidate():
    payload, disks = _payload()
    optical = payload["blockdevices"][0]
    optical.update(
        {
            "name": "sr0",
            "path": "/dev/sr0",
            "type": "rom",
            "tran": "sata",
            "model": "Live ISO",
            "serial": "ISO-1",
            "wwn": "",
        }
    )
    disks = (
        SimpleNamespace(
            path="/dev/sr0",
            size_bytes=16_000_000_000,
            model="Live ISO",
            serial="ISO-1",
            wwn="",
        ),
        disks[1],
    )
    volume = select_export_volume(payload, baseline_fingerprints(disks))
    assert volume.path == "/dev/sdc1"


def _terminal_evidence(tmp_path: Path, outcome: str = "failed") -> Path:
    return write_evidence_atomic(
        {
            "schema_version": 1,
            "outcome": outcome,
            "device": {"path": "/dev/nvme0n1"},
            "logfile": "",
        },
        log_dir=tmp_path,
        device_path="/dev/nvme0n1",
        target_device="/dev/nvme0n1",
    )


@pytest.mark.parametrize("outcome", ["started", "running"])
def test_nonterminal_evidence_cannot_reach_usb(tmp_path, outcome):
    path = _terminal_evidence(tmp_path, outcome)
    with pytest.raises(SafetyError, match="finished"):
        prepare_terminal_evidence(path, "/dev/nvme0n1")


def test_export_log_requires_the_terminal_evidence_snapshot(tmp_path):
    log = tmp_path / "nwipe.log"
    original = b"original terminal nwipe bytes\n"
    log.write_bytes(original)
    expected = hashlib.sha256(original).hexdigest()

    # A caller without an evidence-era hash/length must not export mutable
    # logfile bytes merely because the inode is stable while it is read.
    data, status = read_export_log(str(log))
    assert (data, status) == (b"", "unavailable")

    # With an authenticated snapshot, the exact suffix is exportable.
    data, status = read_export_log(
        str(log), expected_sha256=expected, expected_size_bytes=len(original)
    )
    assert (data, status) == (original, "complete")

    # Replacing the bytes after evidence creation must omit the log.
    log.write_bytes(b"replacement from another run\n")
    data, status = read_export_log(
        str(log), expected_sha256=expected, expected_size_bytes=len(original)
    )
    assert (data, status) == (b"", "unavailable")


def test_controller_uses_two_stable_scans_and_exact_private_worker_command(
    tmp_path, monkeypatch
):
    evidence_path = _terminal_evidence(tmp_path)
    payload, baseline_disks = _payload()
    discovery = _discovery(baseline_disks)
    rdevs = {
        "/dev/sdb": 201,
        "/dev/nvme0n1": 202,
        "/dev/sdc": 301,
        "/dev/sdc1": 302,
    }
    monkeypatch.setattr(
        "beamo_wipe.support_export._block_rdev", lambda path: rdevs[path]
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        request = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "safe_to_remove": True,
                    "code": "saved_verified_unmounted",
                    "evidence_sha256": request["evidence_sha256"],
                    "session_name": "report-0123456789abcdef01234567",
                    "log_status": "unavailable",
                }
            ),
            stderr="",
        )

    scan_count = 0

    def scan():
        nonlocal scan_count
        scan_count += 1
        return payload

    receipt = export_to_new_usb(
        evidence_path=evidence_path,
        discovery=discovery,
        target_path="/dev/nvme0n1",
        scan=scan,
        run=fake_run,
    )
    assert receipt.ok and receipt.safe_to_remove
    assert scan_count == 2
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        "/usr/bin/unshare",
        "--mount",
        "--propagation",
        "private",
        "--",
        "/usr/bin/python3",
        "-sP",
        "-m",
        "beamo_wipe.support_export",
        "--worker",
    ]
    assert kwargs["shell"] is False
    assert kwargs["env"] == CLEAN_SUBPROCESS_ENV
    assert kwargs["timeout"] == 120
    assert kwargs["close_fds"] is True


def test_controller_allows_an_unrelated_optional_disk_to_be_removed(tmp_path, monkeypatch):
    evidence_path = _terminal_evidence(tmp_path)
    payload, baseline_disks = _payload()
    optional = SimpleNamespace(
        path="/dev/sdz",
        size_bytes=500_000_000_000,
        model="Unrelated",
        serial="OPTIONAL-1",
        wwn="optional-wwn",
    )
    discovery = _discovery((*baseline_disks, optional))
    rdevs = {
        "/dev/sdb": 201,
        "/dev/nvme0n1": 202,
        "/dev/sdc": 301,
        "/dev/sdc1": 302,
    }

    def block_rdev(path):
        if path == optional.path:
            raise FileNotFoundError(path)
        return rdevs[path]

    monkeypatch.setattr("beamo_wipe.support_export._block_rdev", block_rdev)

    def fake_run(command, **kwargs):
        request = json.loads(kwargs["input"])
        assert request["baseline"][2]["required"] is False
        assert request["baseline"][2]["rdev"] == 0
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "safe_to_remove": True,
                    "code": "saved_verified_unmounted",
                    "evidence_sha256": request["evidence_sha256"],
                    "session_name": "report-0123456789abcdef01234567",
                    "log_status": "unavailable",
                }
            ),
            stderr="",
        )

    receipt = export_to_new_usb(
        evidence_path=evidence_path,
        discovery=discovery,
        target_path="/dev/nvme0n1",
        scan=lambda: payload,
        run=fake_run,
    )
    assert receipt.ok and receipt.safe_to_remove


def test_controller_rejects_changed_second_scan_before_open(tmp_path, monkeypatch):
    evidence_path = _terminal_evidence(tmp_path)
    first, baseline_disks = _payload()
    second = json.loads(json.dumps(first))
    second["blockdevices"][2]["children"][0]["uuid"] = "CHANGED-1"
    discovery = DiscoveryResult(disks=tuple(baseline_disks), boot_identified=True)  # type: ignore[arg-type]
    scans = iter((first, second))
    monkeypatch.setattr(
        "beamo_wipe.support_export._block_rdev",
        lambda _path: pytest.fail("changed scan must fail before block open"),
    )
    with pytest.raises(SafetyError, match="changed"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: next(scans),
        )


def test_controller_rejects_an_evidence_hash_other_than_the_claim(tmp_path):
    evidence_path = _terminal_evidence(tmp_path)
    payload, baseline_disks = _payload()
    discovery = _discovery(baseline_disks)
    with pytest.raises(SafetyError, match="changed before export"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            expected_evidence_sha256="0" * 64,
            scan=lambda: pytest.fail("stale evidence must fail before discovery"),
            run=lambda *_args, **_kwargs: pytest.fail("stale evidence must not run worker"),
        )


def test_controller_permission_timeout_and_worker_failure_are_visible(tmp_path, monkeypatch):
    import beamo_wipe.support_export as support_export

    evidence_path = _terminal_evidence(tmp_path)
    payload, baseline_disks = _payload()
    discovery = _discovery(baseline_disks)

    monkeypatch.setattr(
        support_export,
        "_block_rdev",
        lambda _path: (_ for _ in ()).throw(
            SafetyError("The report USB disappeared before it could be opened.")
        ),
    )
    with pytest.raises(SafetyError, match="disappeared"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
        )

    rdevs = {
        "/dev/sdb": 201,
        "/dev/nvme0n1": 202,
        "/dev/sdc": 301,
        "/dev/sdc1": 302,
    }
    monkeypatch.setattr(support_export, "_block_rdev", lambda path: rdevs[path])

    def timeout(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, 120)

    with pytest.raises(SafetyError, match="timed out"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=timeout,
        )

    with pytest.raises(SafetyError, match="helper failed"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 1, stdout="", stderr="permission denied"
            ),
        )

    with pytest.raises(SafetyError, match="invalid receipt"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "ok": True,
                        "safe_to_remove": True,
                        "code": "saved_verified_unmounted",
                    }
                ),
                stderr="",
            ),
        )

    with pytest.raises(SafetyError, match="invalid receipt"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "ok": False,
                        "safe_to_remove": True,
                        "code": "export_failed",
                        "evidence_sha256": "",
                        "session_name": "",
                        "log_status": "unavailable",
                    }
                ),
                stderr="",
            ),
        )

    evidence_hash = prepare_terminal_evidence(
        evidence_path, "/dev/nvme0n1"
    ).sha256
    with pytest.raises(SafetyError, match="invalid receipt"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "ok": "false",
                        "safe_to_remove": "false",
                        "code": "saved_verified_unmounted",
                        "evidence_sha256": evidence_hash,
                        "session_name": "report-0123456789abcdef01234567",
                        "log_status": "unavailable",
                    }
                ),
                stderr="",
            ),
        )


def test_controller_rejects_block_alias_to_target(tmp_path, monkeypatch):
    import beamo_wipe.support_export as support_export

    evidence_path = _terminal_evidence(tmp_path)
    payload, baseline_disks = _payload()
    discovery = _discovery(baseline_disks)
    rdevs = {
        "/dev/sdb": 201,
        "/dev/nvme0n1": 202,
        "/dev/sdc": 202,
        "/dev/sdc1": 302,
    }
    monkeypatch.setattr(support_export, "_block_rdev", lambda path: rdevs[path])
    with pytest.raises(SafetyError, match="boot device or selected disk"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=lambda *_args, **_kwargs: pytest.fail("alias must fail before worker"),
        )


def test_controller_rejects_alias_to_a_protected_partition(tmp_path, monkeypatch):
    import beamo_wipe.support_export as support_export

    evidence_path = _terminal_evidence(tmp_path)
    payload, baseline_disks = _payload()
    payload["blockdevices"][0]["children"] = [
        _partition("/dev/sdb1", pkname="sdb", uuid="BOOT-1234")
    ]
    discovery = _discovery(baseline_disks)
    rdevs = {
        "/dev/sdb": 201,
        "/dev/sdb1": 203,
        "/dev/nvme0n1": 202,
        "/dev/sdc": 301,
        "/dev/sdc1": 203,
    }
    monkeypatch.setattr(support_export, "_block_rdev", lambda path: rdevs[path])
    with pytest.raises(SafetyError, match="boot device or selected disk"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=lambda *_args, **_kwargs: pytest.fail("alias must fail before worker"),
        )


@pytest.mark.parametrize(
    ("volume_label", "display_model"),
    [(None, "Unknown model"), ("DATA", "DATA")],
)
def test_display_model_fallback_is_not_used_as_protected_hardware_identity(
    volume_label, display_model
):
    """Raw MODEL absence must compare identically before and during export."""
    payload, _baseline_disks = _payload()
    target = payload["blockdevices"][1]
    target["model"] = None
    target["label"] = volume_label
    initial = (
        node_to_disk(payload["blockdevices"][0], True),
        node_to_disk(target, False),
    )
    assert initial[1].model == display_model
    assert initial[1].raw_model == ""
    baseline = baseline_fingerprints(
        initial, required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    selected = select_export_volume(payload, baseline)

    assert selected.path == "/dev/sdc1"


@pytest.mark.parametrize(
    "hidden_path",
    (
        "/dev/fd0",
        "/dev/ram0",
        "/dev/zram0",
        "/dev/mmcblk0boot0",
        "/dev/mmcblk0boot1",
        "/dev/mmcblk0rpmb",
    ),
)
def test_export_ignores_the_same_non_target_root_devices_as_discovery(hidden_path):
    payload, baseline_disks = _payload(
        _root(
            hidden_path,
            size=4_194_304,
            tran="",
            model="System area",
            serial="",
        )
    )
    baseline = baseline_fingerprints(
        baseline_disks, required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    selected = select_export_volume(payload, baseline)

    assert selected.path == "/dev/sdc1"


def test_export_still_rejects_an_unknown_root_device_path():
    payload, baseline_disks = _payload(
        _root(
            "/dev/mapper/unknown",
            size=4_194_304,
            tran="",
            model="Unknown root",
            serial="",
        )
    )
    baseline = baseline_fingerprints(
        baseline_disks, required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )

    with pytest.raises(SafetyError, match="device path is unsupported"):
        select_export_volume(payload, baseline)


def test_real_raw_model_change_still_fails_closed():
    payload, _baseline_disks = _payload()
    initial = (
        node_to_disk(payload["blockdevices"][0], True),
        node_to_disk(payload["blockdevices"][1], False),
    )
    baseline = baseline_fingerprints(
        initial, required_paths={"/dev/sdb", "/dev/nvme0n1"}
    )
    payload["blockdevices"][1]["model"] = "Substituted target"

    with pytest.raises(SafetyError, match="Leave the Beamo USB"):
        select_export_volume(payload, baseline)


def test_legacy_disk_without_raw_model_keeps_model_identity():
    disk = SimpleNamespace(
        path="/dev/sda",
        size_bytes=1_000_000_000,
        model="Hardware model",
        serial="SERIAL",
        wwn="WWN",
    )

    fingerprint = baseline_fingerprints((disk,))[0]

    assert fingerprint.model == "Hardware model"


def test_bundle_is_completion_marked_and_readback_verified(tmp_path):
    evidence = b'{"outcome":"failed"}\n'
    log = b"bounded log\n"
    session, files = write_report_bundle(
        tmp_path,
        evidence,
        log,
        "complete",
        session_name="report-0123456789abcdef01234567",
    )
    assert list(files)[-1] == "COMPLETE"
    verify_report_bundle(tmp_path, session, files)
    complete = json.loads(files["COMPLETE"])
    assert "complete" not in complete
    assert complete["manifest_scope"] == "content_only"
    assert complete["safe_to_remove"] is False
    assert complete["log_status"] == "complete"


def test_partial_bundle_does_not_block_unique_retry(tmp_path, monkeypatch):
    import beamo_wipe.support_export as support_export

    original = support_export._write_exclusive
    calls = 0

    def fail_second(directory_fd, name, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated full USB")
        original(directory_fd, name, data)

    monkeypatch.setattr(support_export, "_write_exclusive", fail_second)
    with pytest.raises(OSError, match="full USB"):
        write_report_bundle(
            tmp_path,
            b"one",
            b"",
            "unavailable",
            session_name="report-aaaaaaaaaaaaaaaaaaaaaaaa",
        )
    assert not (
        tmp_path / "BEAMO-WIPE-REPORTS" / "report-aaaaaaaaaaaaaaaaaaaaaaaa" / "COMPLETE"
    ).exists()

    monkeypatch.setattr(support_export, "_write_exclusive", original)
    session, files = write_report_bundle(
        tmp_path,
        b"one",
        b"",
        "unavailable",
        session_name="report-bbbbbbbbbbbbbbbbbbbbbbbb",
    )
    verify_report_bundle(tmp_path, session, files)


def test_late_directory_fsync_failure_leaves_no_success_claim(tmp_path, monkeypatch):
    import beamo_wipe.support_export as support_export

    original_fsync = support_export.os.fsync

    def fail_first_directory_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("simulated directory fsync failure")
        return original_fsync(fd)

    monkeypatch.setattr(support_export.os, "fsync", fail_first_directory_fsync)
    session = "report-cccccccccccccccccccccccc"
    with pytest.raises(OSError, match="directory fsync"):
        write_report_bundle(
            tmp_path,
            b"one",
            b"",
            "unavailable",
            session_name=session,
        )

    marker = tmp_path / "BEAMO-WIPE-REPORTS" / session / "COMPLETE"
    if marker.exists():
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload.get("complete") is not True
        assert payload.get("safe_to_remove") is False


def _fake_export_state(tmp_path, monkeypatch):
    import beamo_wipe.support_export as support_export

    monkeypatch.setattr(support_export, "MOUNT_ROOT", tmp_path / "run")
    parent = DeviceFingerprint(
        "/dev/sdc", 64_000_000, "Report", "REPORT-1", "report-wwn", 801
    )
    volume = ExportVolume(
        parent, "/dev/sdc1", 63_000_000, "vfat", "FAT32", "ABCD-1234", 802
    )
    evidence = VerifiedEvidence(b"evidence\n", "a" * 64, "failed", "", "", 0)
    backing = tmp_path / "fake-block-handle"
    backing.write_bytes(b"x")
    fd = os.open(backing, os.O_RDONLY)
    monkeypatch.setattr(support_export, "_mounted_exact", lambda *_args: True)
    monkeypatch.setattr(support_export, "_verify_mount", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(support_export, "_mount_record", lambda *_args: None)
    return support_export, volume, evidence, fd


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("mount", "mounted safely"),
        ("sync", "synchronized"),
        ("unmount", "could not be unmounted"),
        ("remount", "remounted for verification"),
        ("readback", "read-back"),
        ("final_unmount", "verified report USB could not be unmounted"),
    ],
)
def test_worker_mount_state_failures_never_claim_safe(
    tmp_path, monkeypatch, failure, message
):
    support_export, volume, evidence, fd = _fake_export_state(tmp_path, monkeypatch)
    command_index = 0

    def run_command(_command, **_kwargs):
        nonlocal command_index
        command_index += 1
        fail_index = {"mount": 1, "sync": 2, "remount": 3}.get(failure)
        return subprocess.CompletedProcess([], 1 if command_index == fail_index else 0)

    unmount_index = 0

    def ordinary_unmount(*_args):
        nonlocal unmount_index
        unmount_index += 1
        if failure == "unmount" and unmount_index == 1:
            return False
        if failure == "final_unmount" and unmount_index == 2:
            return False
        return True

    monkeypatch.setattr(support_export, "_run_command", run_command)
    monkeypatch.setattr(support_export, "_ordinary_unmount", ordinary_unmount)
    if failure == "readback":
        monkeypatch.setattr(
            support_export,
            "verify_report_bundle",
            lambda *_args: (_ for _ in ()).throw(
                SafetyError("The exported report did not pass read-back verification.")
            ),
        )
    try:
        with pytest.raises(SafetyError, match=message):
            support_export._persist_and_verify_report(
                volume, evidence, b"", "unavailable", fd
            )
    finally:
        os.close(fd)

    for marker in (tmp_path / "run").glob("mount-*/BEAMO-WIPE-REPORTS/report-*/COMPLETE"):
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["safe_to_remove"] is False
        assert "complete" not in payload


def test_worker_duplicate_export_is_blocked_then_retry_succeeds(tmp_path, monkeypatch):
    support_export, volume, evidence, fd = _fake_export_state(tmp_path, monkeypatch)
    support_export.MOUNT_ROOT.mkdir(parents=True)
    lock_fd = os.open(
        support_export.MOUNT_ROOT / ".lock", os.O_RDWR | os.O_CREAT, 0o600
    )
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(SafetyError, match="already running"):
            support_export._persist_and_verify_report(
                volume, evidence, b"", "unavailable", fd
            )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    monkeypatch.setattr(
        support_export,
        "_run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0),
    )
    monkeypatch.setattr(support_export, "_ordinary_unmount", lambda *_args: True)
    try:
        receipt = support_export._persist_and_verify_report(
            volume, evidence, b"", "unavailable", fd
        )
    finally:
        os.close(fd)
    assert receipt.ok is True and receipt.safe_to_remove is True


def _done_wizard(exporter, tmp_path: Path) -> Wizard:
    base = make_demo_wizard()
    wizard = Wizard(base.discovery, base.runner, dry_run=False, report_exporter=exporter)
    wizard.preview = False
    wizard.screen = Screen.DONE
    wizard.selected = wizard.discovery.selectable[0]
    wizard.wipe_result = WipeResult(False, 1, "failed", "/tmp/beamo-wipe/nwipe.log")
    path = write_evidence_atomic(
        {
            "schema_version": 1,
            "outcome": "failed",
            "device": {"path": wizard.selected.path},
            "exit_evidence": {"exit_code": 1, "signal": None},
            "logfile": wizard.wipe_result.logfile,
        },
        log_dir=tmp_path,
        device_path=wizard.selected.path,
        target_device=wizard.selected.path,
    )
    wizard.evidence_path = str(path)
    wizard.evidence = json.loads(path.read_text(encoding="utf-8"))
    wizard.evidence["provenance"]["verified"] = True
    wizard._evidence_written_for = wizard._result_evidence_key(wizard.wipe_result)
    wizard._evidence_write_seq = 1
    return wizard


def _success_receipt(**kwargs) -> ExportReceipt:
    return ExportReceipt(
        True,
        True,
        "saved_verified_unmounted",
        evidence_sha256=kwargs["expected_evidence_sha256"],
        session_name="report-0123456789abcdef01234567",
    )


def test_wizard_only_announces_safe_after_verified_unmount(tmp_path):
    wizard = _done_wizard(
        lambda **_kwargs: ExportReceipt(False, True, "copy_failed"), tmp_path
    )
    wizard.save_report_to_usb()
    assert wizard.report_status == "error"
    assert "safe to remove" not in wizard.report_message.casefold()

    wizard = _done_wizard(_success_receipt, tmp_path)
    wizard.save_report_to_usb()
    assert wizard.report_status == "saved"
    assert "safe to remove" in wizard.report_message.casefold()

    forged = SimpleNamespace(
        ok="false",
        safe_to_remove="false",
        session_name="report-0123456789abcdef01234567",
    )
    wizard = _done_wizard(lambda **_kwargs: forged, tmp_path)
    wizard.save_report_to_usb()
    assert wizard.report_status == "error"
    assert "safe to remove" not in wizard.report_message.casefold()


def test_wizard_rejects_stale_or_failed_terminal_evidence_write(tmp_path):
    wizard = _done_wizard(lambda **_kwargs: pytest.fail("must not export"), tmp_path)
    wizard.evidence["outcome"] = "started"
    wizard.save_report_to_usb()
    assert wizard.report_status == "error"


def test_wizard_export_claim_rejects_same_outcome_stale_payload(tmp_path):
    wizard = _done_wizard(lambda **_kwargs: pytest.fail("must not export"), tmp_path)
    wizard.evidence["failure_reason"] = "a different failed run"

    wizard.save_report_to_usb()

    assert wizard.report_status == "error"
    assert "changed" in wizard.report_message.casefold()


def test_wizard_rejects_success_receipt_for_different_evidence_hash(tmp_path):
    wizard = _done_wizard(
        lambda **_kwargs: ExportReceipt(
            True,
            True,
            "saved_verified_unmounted",
            evidence_sha256="0" * 64,
            session_name="report-0123456789abcdef01234567",
        ),
        tmp_path,
    )

    wizard.save_report_to_usb()

    assert wizard.report_status == "error"
    assert "safe to remove" not in wizard.report_message.casefold()


def test_wizard_rejects_terminal_evidence_from_a_different_result(tmp_path):
    wizard = _done_wizard(lambda **_kwargs: pytest.fail("must not export"), tmp_path)
    wizard.wipe_result = WipeResult(True, 0, "finished", "/tmp/beamo-wipe/nwipe.log")
    wizard.evidence["outcome"] = "failed"
    wizard.evidence["exit_evidence"] = {"exit_code": 1, "signal": None}
    assert not wizard.can_save_report
    wizard.report_status = "idle"
    wizard.evidence["outcome"] = "failed"
    wizard.evidence_error = "completion evidence write failed"
    wizard.save_report_to_usb()
    assert wizard.report_status == "error"


def test_wizard_report_failure_is_retryable_with_a_new_attempt(tmp_path):
    attempts = iter((False, True))

    def exporter(**kwargs):
        if next(attempts):
            return _success_receipt(**kwargs)
        return ExportReceipt(False, False, "export_failed")

    wizard = _done_wizard(exporter, tmp_path)
    wizard.save_report_to_usb()
    assert wizard.report_status == "error"
    wizard.save_report_to_usb()
    assert wizard.report_status == "saved"


def test_concurrent_report_requests_run_one_worker_and_block_shutdown(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def exporter(**_kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return _success_receipt(**_kwargs)

    wizard = _done_wizard(exporter, tmp_path)
    assert wizard.begin_report_export()
    assert entered.wait(5)
    assert not wizard.begin_report_export()
    assert wizard.report_status == "saving"
    wizard.shutdown()
    assert not wizard.wants_shutdown
    release.set()
    for _ in range(1000):
        if wizard.report_status == "saved":
            break
        threading.Event().wait(0.001)
    assert wizard.report_status == "saved"
    assert calls == [True]


def test_report_changed_during_export_cannot_publish_saved(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def exporter(**kwargs):
        entered.set()
        assert release.wait(5)
        return _success_receipt(**kwargs)

    wizard = _done_wizard(exporter, tmp_path)
    assert wizard.begin_report_export()
    assert entered.wait(5)
    wizard.evidence_path = str(tmp_path / "different-result.json")
    release.set()
    for _ in range(1000):
        if not wizard.report_view.exporting:
            break
        threading.Event().wait(0.001)
    assert wizard.report_status == "error"
    assert "safe to remove" not in wizard.report_message.casefold()


def test_report_view_revision_publishes_coherent_export_states(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def exporter(**kwargs):
        entered.set()
        assert release.wait(5)
        return _success_receipt(**kwargs)

    wizard = _done_wizard(exporter, tmp_path)
    before = wizard.report_view
    assert wizard.begin_report_export()
    assert entered.wait(5)
    saving = wizard.report_view
    assert saving.revision > before.revision
    assert (saving.status, saving.exporting, saving.can_save) == ("saving", True, False)
    release.set()
    for _ in range(1000):
        saved = wizard.report_view
        if saved.status == "saved":
            break
        threading.Event().wait(0.001)
    assert saved.revision > saving.revision
    assert (saved.status, saved.exporting, saved.can_save) == ("saved", False, False)


def test_mount_commands_never_use_force_or_lazy_flags():
    source = Path("src/beamo_wipe/support_export.py").read_text(encoding="utf-8")
    assert "[UMOUNT_BIN, \"--\", str(mountpoint)]" in source
    assert "umount -l" not in source
    assert "umount -f" not in source


def test_plain_done_requires_literal_save_or_shutdown(monkeypatch, tmp_path):
    from beamo_wipe.ui import console_wizard

    actions = iter(("", "SHUTDOWN"))
    wizard = _done_wizard(lambda **_kwargs: pytest.fail("blank must not export"), tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(actions))
    assert console_wizard._plain_loop_body(wizard) == 0
    assert wizard.wants_shutdown


def test_plain_done_hides_save_when_terminal_evidence_unavailable(
    monkeypatch, tmp_path, capsys
):
    from beamo_wipe.ui import console_wizard

    wizard = _done_wizard(lambda **_kwargs: pytest.fail("must not export"), tmp_path)
    wizard.evidence_error = "completion evidence write failed"
    prompts = []

    def answer(prompt=""):
        prompts.append(prompt)
        return "SHUTDOWN"

    monkeypatch.setattr("builtins.input", answer)
    assert console_wizard._plain_loop_body(wizard) == 0
    output = capsys.readouterr().out
    assert "FAT32" not in output
    assert "Insert exactly" not in output
    assert all("SAVE" not in prompt for prompt in prompts)


def test_curses_enter_requires_a_full_quiet_interval_before_rearm():
    from beamo_wipe.ui.console_wizard import (
        ENTER_RELEASE_QUIET_S,
        _advance_enter_quiet,
    )

    held, since, released = _advance_enter_quiet(True, None, 10.0)
    assert (held, since, released) == (True, 10.0, False)
    held, since, released = _advance_enter_quiet(
        held, since, 10.0 + ENTER_RELEASE_QUIET_S - 0.001
    )
    assert (held, released) == (True, False)
    held, since, released = _advance_enter_quiet(
        held, since, 10.0 + ENTER_RELEASE_QUIET_S
    )
    assert (held, since, released) == (False, None, True)


def test_no_shipped_ui_accepts_a_report_destination_path():
    tk_source = Path("src/beamo_wipe/ui/tk_wizard.py").read_text(encoding="utf-8")
    console_source = Path("src/beamo_wipe/ui/console_wizard.py").read_text(
        encoding="utf-8"
    )
    assert "filedialog" not in tk_source
    assert "askdirectory" not in tk_source
    assert "destination path" not in console_source.casefold()
    assert "Type SAVE" in console_source
    assert "_confirm_report_save" in console_source


def test_live_service_has_private_mount_namespace():
    service = Path(
        "packaging/live/config/includes.chroot/etc/systemd/system/beamo-wipe-kiosk.service"
    ).read_text(encoding="utf-8")
    assert "PrivateMounts=yes" in service


def test_isolated_linux_gate_exercises_real_fat32_and_crash_cleanup():
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    hosted = Path("scripts/ci-hosted.sh").read_text(encoding="utf-8")
    assert "mkfs.vfat -F 32" in qemu
    assert "write_report_bundle" in qemu
    assert "verify_report_bundle" in qemu
    assert "unshare --mount --propagation private" in qemu
    assert "private report helper leaked a mount" in qemu
    assert "dosfstools" in hosted
    assert "export_to_new_usb" in qemu
    assert "BEAMO_WIPE_REPORT_SAVED" in qemu
    assert "device_add" in qemu
    assert "BEAMO_WIPE_SCREEN_DONE" in qemu
    tk_text = Path("src/beamo_wipe/ui/tk_wizard.py").read_text(encoding="utf-8")
    assert 'emit_serial_marker(f"BEAMO_WIPE_SCREEN_{screen.name}")' in tk_text
    assert 'emit_serial_marker(f"BEAMO_WIPE_REPORT_{report_view.status.upper()}")' in tk_text


def test_qemu_report_volume_label_fits_fat_limit():
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    match = re.search(r"mkfs\.vfat\s+-F\s+32\s+-n\s+([^\s]+)", qemu)
    assert match is not None
    assert len(match.group(1)) <= 11


def test_qemu_key_steps_synchronize_press_redraw_and_release():
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    tk_source = Path("src/beamo_wipe/ui/tk_wizard.py").read_text(encoding="utf-8")
    key_branch = qemu.split('if action == "query":', 1)[1].split(
        'elif action == "hotplug-report":', 1
    )[0]
    assert '"input-send-event"' in key_branch
    assert 'action == "key-tap"' in key_branch
    assert '"send-key"' in key_branch
    assert '"hold-time": 100' in key_branch
    assert 'action in {"key-down", "key-up"}' in key_branch
    assert '"down": action == "key-down"' in key_branch
    assert '"human-monitor-command"' not in key_branch
    assert "send_key_for_marker" in qemu
    assert "wait_for_new_marker" in qemu
    assert "BEAMO_WIPE_KEY_RETURN_RELEASED" in qemu
    assert "BEAMO_WIPE_KEY_SPACE_RELEASED" in qemu
    assert "BEAMO_WIPE_KEY_RETURN_RELEASED" in tk_source
    assert "BEAMO_WIPE_KEY_SPACE_RELEASED" in tk_source
    assert 'card.bind("<space>", self._owner_key)' in tk_source
    assert "BEAMO_WIPE_OWNER_CHECKED" in qemu
    assert "BEAMO_WIPE_OWNER_CHECKED" in tk_source
    assert 'qmp_request "$qmp_socket" key-tap "$key"' in qemu
    assert "type_token_for_marker" in qemu
    assert "BEAMO_WIPE_CONFIRM_MATCHED" in tk_source
    assert "BEAMO_WIPE_CONFIRM_FOCUSED" in qemu
    assert "BEAMO_WIPE_CONFIRM_UNFOCUSED" in qemu
    assert "BEAMO_WIPE_CONFIRM_FOCUSED" in tk_source
    assert "BEAMO_WIPE_CONFIRM_UNFOCUSED" in tk_source
    assert 'wait_for_marker "$label" BEAMO_WIPE_CONFIRM_FOCUSED 20' in qemu


def test_qemu_types_the_token_required_for_same_size_boot_and_target_disks():
    """The shipped ISO and 1 GiB target both display as 1 GB in this gate."""
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    serial_match = re.search(r'^QEMU_TARGET_SERIAL="([A-Za-z0-9._:-]+)"$', qemu, re.MULTILINE)
    assert serial_match is not None
    serial = serial_match.group(1)

    boot = Disk(
        path="/dev/sr0",
        name="sr0",
        model="QEMU DVD-ROM",
        serial="",
        size_bytes=429_916_160,
        size_gb_label="1",
        kind=DiskKind.UNKNOWN,
        bus="ata",
        label="Beamo Wipe",
        is_boot=True,
    )
    target = Disk(
        path="/dev/vda",
        name="vda",
        model="QEMU HARDDISK",
        serial=serial,
        size_bytes=1_073_741_824,
        size_gb_label="1",
        kind=DiskKind.HDD,
        bus="virtio",
        label="",
    )

    assert confirm_spec(target, (target, boot)).token == serial
    assert 'serial=$QEMU_TARGET_SERIAL' in qemu
    assert (
        'type_token_for_marker "$label" "$qmp_socket" "$QEMU_TARGET_SERIAL" '
        'BEAMO_WIPE_CONFIRM_MATCHED 20'
    ) in qemu


def test_owner_card_space_suppresses_x11_autorepeat_pair():
    """The focused owner card must share the root Space hold guard."""
    from beamo_wipe.ui.tk_wizard import TkWizard

    class FakeRoot:
        def __init__(self):
            self.callbacks = {}
            self.next_id = 0

        def after_idle(self, callback):
            self.next_id += 1
            callback_id = f"idle-{self.next_id}"
            self.callbacks[callback_id] = callback
            return callback_id

        def after_cancel(self, callback_id):
            self.callbacks.pop(callback_id)

    class FakeVar:
        def __init__(self):
            self.value = 0

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class FakeWizard:
        owner_ok = False

        def set_owner(self, value):
            self.owner_ok = bool(value)

        def arm_done_keyboard(self):
            pass

    app = object.__new__(TkWizard)
    app.root = FakeRoot()
    app.w = FakeWizard()
    app._owner_var = FakeVar()
    app._space_held = False
    app._space_release_after = None
    app._space_action_active = False
    draw_count = []
    app._draw = lambda: draw_count.append(True)

    assert app._owner_key() == "break"
    assert app.w.owner_ok
    assert len(draw_count) == 1

    # X11 autorepeat queues Release/Press before the event loop is idle.
    app._on_space_release()
    assert app._owner_key() == "break"
    assert app.w.owner_ok
    assert len(draw_count) == 1
    assert app._space_held


def test_confirm_screen_recovers_entry_focus_without_window_manager(monkeypatch):
    """The live startx path has no WM to grant an ordinary focus request."""
    from beamo_wipe.ui import tk_wizard
    from beamo_wipe.ui.tk_wizard import TkWizard

    class FakeRoot:
        focused = None

        def focus_get(self):
            return self.focused

    class FakeEntry:
        def __init__(self, root):
            self.root = root
            self.force_calls = 0

        def focus_force(self):
            self.force_calls += 1
            self.root.focused = self

    app = object.__new__(TkWizard)
    app.root = FakeRoot()
    app.w = SimpleNamespace(screen=Screen.CONFIRM)
    entry = FakeEntry(app.root)
    markers = []
    monkeypatch.setattr(tk_wizard, "emit_serial_marker", markers.append)

    app._ensure_confirm_focus(entry)

    assert entry.force_calls == 1
    assert app.root.focus_get() is entry
    assert markers == ["BEAMO_WIPE_CONFIRM_FOCUSED"]


def test_confirm_focus_retries_after_async_x11_focus_request(monkeypatch):
    """X11 may not report a forced focus change until a later event-loop turn."""
    from beamo_wipe.ui import tk_wizard
    from beamo_wipe.ui.tk_wizard import TkWizard

    class FakeRoot:
        focused = None

        def focus_get(self):
            return self.focused

    class FakeEntry:
        def __init__(self, root):
            self.root = root
            self.force_calls = 0
            self.callbacks = []

        def focus_force(self):
            self.force_calls += 1
            if self.force_calls == 2:
                self.root.focused = self

        def after(self, delay_ms, callback):
            assert delay_ms == 50
            self.callbacks.append(callback)

    app = object.__new__(TkWizard)
    app.root = FakeRoot()
    app.w = SimpleNamespace(screen=Screen.CONFIRM)
    entry = FakeEntry(app.root)
    markers = []
    monkeypatch.setattr(tk_wizard, "emit_serial_marker", markers.append)

    app._ensure_confirm_focus(entry)

    assert entry.force_calls == 1
    assert markers == []
    assert len(entry.callbacks) == 1
    entry.callbacks.pop()()
    assert entry.force_calls == 2
    assert app.root.focus_get() is entry
    assert markers == ["BEAMO_WIPE_CONFIRM_FOCUSED"]


def test_qemu_screen_markers_require_exact_full_lines():
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    marker_helper = qemu.split("marker_count() {", 1)[1].split("\n}", 1)[0]
    assert "$0 == marker" in marker_helper
    assert 'grep -qF "$marker"' not in qemu
    assert "report_marker_summary" in qemu
    assert "BEAMO_WIPE_SCREEN_PICK_BLOCKED" in qemu
    assert "BEAMO_WIPE_SCREEN_PICK_EMPTY" in qemu
    assert "BEAMO_WIPE_RETURN_RESULT_PICK" in qemu
    assert "BEAMO_WIPE_RETURN_RESULT_PICK_BLOCKED" in qemu
    assert "BEAMO_WIPE_RETURN_RESULT_PICK_EMPTY" in qemu
    assert "observed exact marker" in qemu
    tk_source = Path("src/beamo_wipe/ui/tk_wizard.py").read_text(encoding="utf-8")
    assert 'emit_serial_marker(f"BEAMO_WIPE_RETURN_RESULT_{self.w.screen.name}")' in tk_source


def test_qemu_marker_waits_recheck_after_the_final_sleep():
    """A marker arriving during the last sleep must not be reported missing."""
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")

    def after_loop(name):
        body = qemu.split(f"{name}() {{", 1)[1].split("\n}", 1)[0]
        return body.split("\n  done", 1)[1]

    assert 'marker_count "$label" "$marker"' in after_loop("wait_for_marker")
    assert 'marker_count "$label" "$marker"' in after_loop("wait_for_new_marker")
    report_tail = after_loop("wait_for_report_saved")
    assert "BEAMO_WIPE_REPORT_SAVED" in report_tail
    assert "BEAMO_WIPE_REPORT_ERROR" in report_tail


def test_qemu_report_failure_trace_identifies_the_last_safe_export_boundary():
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    export_source = Path("src/beamo_wipe/support_export.py").read_text(encoding="utf-8")
    required = {
        "BEAMO_WIPE_EXPORT_CONTROLLER_STARTED",
        "BEAMO_WIPE_EXPORT_EVIDENCE_VERIFIED",
        "BEAMO_WIPE_EXPORT_SCAN_ONE",
        "BEAMO_WIPE_EXPORT_SELECT_ONE",
        "BEAMO_WIPE_EXPORT_SCAN_TWO",
        "BEAMO_WIPE_EXPORT_CONTROLLER_SELECTED",
        "BEAMO_WIPE_EXPORT_CONTROLLER_IDENTIFIED",
        "BEAMO_WIPE_EXPORT_WORKER_DECODED",
        "BEAMO_WIPE_EXPORT_WORKER_SELECTED",
        "BEAMO_WIPE_EXPORT_WORKER_IDENTIFIED",
        "BEAMO_WIPE_EXPORT_WORKER_OPENED",
        "BEAMO_WIPE_EXPORT_RW_MOUNTED",
        "BEAMO_WIPE_EXPORT_BUNDLE_WRITTEN",
        "BEAMO_WIPE_EXPORT_RW_UNMOUNTED",
        "BEAMO_WIPE_EXPORT_RO_MOUNTED",
        "BEAMO_WIPE_EXPORT_READBACK_VERIFIED",
        "BEAMO_WIPE_EXPORT_RO_UNMOUNTED",
        "BEAMO_WIPE_EXPORT_WORKER_FAILED",
        "BEAMO_WIPE_EXPORT_FAIL_METADATA",
        "BEAMO_WIPE_EXPORT_FAIL_BASELINE",
        "BEAMO_WIPE_EXPORT_FAIL_REMOVABLE",
        "BEAMO_WIPE_EXPORT_FAIL_COUNT",
        "BEAMO_WIPE_EXPORT_FAIL_MOUNTED",
        "BEAMO_WIPE_EXPORT_FAIL_LAYOUT",
        "BEAMO_WIPE_EXPORT_FAIL_DEVICE_PATH",
        "BEAMO_WIPE_EXPORT_FAIL_CHILDREN",
        "BEAMO_WIPE_EXPORT_FAIL_AMBIGUOUS",
        "BEAMO_WIPE_EXPORT_FAIL_UNSUPPORTED_LAYOUT",
        "BEAMO_WIPE_EXPORT_FAIL_PARENT_LINK",
        "BEAMO_WIPE_EXPORT_FAIL_VOLUME_PATH",
        "BEAMO_WIPE_EXPORT_FAIL_SIZE",
        "BEAMO_WIPE_EXPORT_FAIL_FAT32",
        "BEAMO_WIPE_EXPORT_FAIL_OTHER",
    }
    for marker in required:
        assert marker in export_source
        assert marker in qemu
    report_wait = qemu.split("wait_for_report_saved() {", 1)[1].split("\n}", 1)[0]
    error_branch = report_wait.split(
        'marker_count "$label" BEAMO_WIPE_REPORT_ERROR', 1
    )[1]
    assert 'report_marker_summary "$label"' in error_branch


def test_qemu_tcg_boot_gets_a_larger_bounded_startup_budget():
    """Software-emulated boot can exceed the KVM kiosk-start deadline."""
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    assert "BOOT_WAIT_SECONDS=120" in qemu
    assert 'if [[ ! -r /dev/kvm ]]; then BOOT_WAIT_SECONDS=300; fi' in qemu
    assert 'BEAMO_WIPE_SCREEN_WHAT "$BOOT_WAIT_SECONDS"' in qemu


def test_qemu_boot_readiness_uses_the_rendered_tk_screen_not_the_wrapper_marker():
    """A rendered WHAT screen proves the kiosk even if its early marker was lost."""
    qemu = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    boot_probe = qemu.split("boot_probe() {", 1)[1].split("\n}", 1)[0]

    assert 'wait_for_marker "$label" BEAMO_WIPE_SCREEN_WHAT' in boot_probe
    assert 'wait_for_marker "$label" BEAMO_WIPE_KIOSK_READY' not in boot_probe
