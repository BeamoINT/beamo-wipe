# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed gaps: classification, boot exclusion, argv, verify, cancel, recovery.

Fake lsblk JSON, DryRunRunner, SpyRunner, FakeProc. Never a host disk. Never
pinned nwipe. Production disk-selection and nwipe flags are unchanged unless a
test here proves a real bug.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from beamo_wipe.copy import IDENTIFY_ERROR, NOT_LIVE_ERROR
from beamo_wipe.discover import classify_kind, discover, load_lsblk_json_text
from beamo_wipe.evidence import OUTCOME_INTERRUPTED
from beamo_wipe.models import DiskKind, MethodId, Screen, WipeRequest
from beamo_wipe.nwipe_runner import (
    DryRunRunner,
    build_nwipe_argv,
    evaluate_nwipe_outcome,
    validate_argv,
)
from beamo_wipe.safety import (
    SafetyError,
    is_live_environment,
    normalize_whole_disk,
    require_live_or_dry_run,
    selectable_disks,
)
from beamo_wipe.wizard import Wizard, make_demo_wizard
from test_boot_exclusion_fails_closed import SpyRunner, _wizard_for_discovery

FIXTURES = Path(__file__).parent / "fixtures"


class Clock:
    def __init__(self, t=0.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def add(self, s):
        self.t += float(s)


def _disk(name, **changes):
    value = {
        "name": name,
        "path": "/dev/" + name,
        "type": "disk",
        "size": 32_000_000_000,
        "model": "Fake disk",
        "serial": name,
        "tran": "usb",
        "rota": False,
        "ro": False,
        "mountpoints": [None],
        "mountpoint": None,
    }
    value.update(changes)
    return value


def _request(tmp_path: Path) -> WipeRequest:
    payload = load_lsblk_json_text((FIXTURES / "lsblk_vm_iso.json").read_text(encoding="utf-8"))
    discovery = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
        mount_sources=[],
        cmdline="",
    )
    disk = selectable_disks(discovery)[0]
    return WipeRequest(
        device=disk.path,
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )


# ---------------------------------------------------------------------------
# Device classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rota", ["", "yes", "no", 2, "maybe", None])
def test_malformed_rota_is_unknown_kind_not_hdd_or_ssd(rota):
    assert classify_kind("sda", "sata", rota) == DiskKind.UNKNOWN


# ---------------------------------------------------------------------------
# Boot-media exclusion — two resolved live mounts
# ---------------------------------------------------------------------------


def test_two_resolved_live_mounts_fail_closed_and_never_start_nwipe(monkeypatch):
    markers = []
    monkeypatch.setattr(
        "beamo_wipe.diagnostics.emit_serial_marker", lambda marker: markers.append(marker)
    )
    payload = {
        "blockdevices": [
            {
                "name": "sda",
                "path": "/dev/sda",
                "size": 16_000_000_000,
                "type": "disk",
                "tran": "usb",
                "model": "Beamo",
                "serial": "BEAMO001",
                "ro": False,
                "mountpoints": [None],
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "label": "BEAMO_WIPE",
                    }
                ],
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": 500_000_000_000,
                "type": "disk",
                "tran": "sata",
                "model": "ST500",
                "serial": "ST50001",
                "ro": False,
                "mountpoints": [None],
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "label": "WINDOWS",
                    }
                ],
            },
            {
                "name": "nvme0n1",
                "path": "/dev/nvme0n1",
                "size": 256_000_000_000,
                "type": "disk",
                "tran": "nvme",
                "model": "NVMe",
                "serial": "NVME01",
                "rota": False,
                "ro": False,
                "mountpoints": [None],
            },
        ]
    }
    result = discover(
        lsblk_payload=payload,
        boot_path=None,
        mount_sources=["/dev/sda1", "/dev/sdb1"],
        cmdline="boot=live",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert result.selectable == ()
    assert IDENTIFY_ERROR.lower() in (result.error or "").lower()
    assert "BEAMO_WIPE_BOOT_SOURCE_CONFLICT" in markers

    spy = SpyRunner()
    wiz = _wizard_for_discovery(result, spy=spy)
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK_BLOCKED
    assert not wiz.erase_enabled
    wiz.confirm_erase()
    assert spy.start_calls == []


# ---------------------------------------------------------------------------
# System-disk / live-env: mkdir /run/live is not a live medium
# ---------------------------------------------------------------------------


def test_boot_live_with_non_block_mountinfo_is_not_live():
    overlay = "10 1 0:100 / /run/live/medium - overlay overlay rw\n"
    tmpfs = "36 1 0:1 / /run/live/medium - tmpfs tmpfs rw\n"
    empty = ""
    for text in (overlay, tmpfs, empty):
        assert not is_live_environment(env={}, cmdline="boot=live quiet", mountinfo_text=text)
    with pytest.raises(SafetyError) as err:
        require_live_or_dry_run(env={}, cmdline="boot=live", live_medium_mounted=False)
    assert str(err.value) == NOT_LIVE_ERROR


def test_boot_live_with_block_source_mountinfo_is_live():
    text = "10 1 8:1 / /run/live/medium - ext4 /dev/sda1 rw\n"
    assert is_live_environment(env={}, cmdline="boot=live quiet", mountinfo_text=text)


# ---------------------------------------------------------------------------
# Malformed production lsblk — missing RO / mountpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda node: node.pop("ro"), "read-only"),
        (lambda node: node.__setitem__("ro", "maybe"), "read-only"),
        (lambda node: (node.pop("mountpoints"), node.pop("mountpoint")), "mountpoint"),
    ],
    ids=["omit-ro", "unparseable-ro", "omit-mountpoints"],
)
def test_production_lsblk_missing_safety_columns_fails_closed(monkeypatch, mutate, needle):
    discovery_module = importlib.import_module("beamo_wipe.discover")
    payload = {"blockdevices": [_disk("sda"), _disk("sdb")]}
    mutate(payload["blockdevices"][0])
    monkeypatch.setattr(discovery_module, "run_lsblk", lambda: payload)
    result = discovery_module.discover(mount_sources=["/dev/sdb"], cmdline="", env={})
    assert not result.boot_identified
    assert result.selectable == ()
    assert IDENTIFY_ERROR.lower() in (result.error or "").lower()
    assert needle in (result.diagnostic or "").lower()


def test_injected_lsblk_still_skips_production_metadata_gate():
    """Fixture payloads omit the production column gate by design."""
    payload = {"blockdevices": [_disk("sda"), _disk("sdb", tran="usb")]}
    payload["blockdevices"][0].pop("ro")
    result = discover(
        lsblk_payload=payload,
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert result.boot_identified
    assert "/dev/sda" in {disk.path for disk in result.selectable}


# ---------------------------------------------------------------------------
# Wipe command construction
# ---------------------------------------------------------------------------


def test_duplicate_autonuke_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    req = _request(tmp_path)
    argv = build_nwipe_argv(req)
    argv.insert(1, "--autonuke")
    with pytest.raises(SafetyError, match="Exactly one --autonuke"):
        validate_argv(argv, req)
    assert "--force" not in argv


def test_xen_dasd_and_ide_whole_disks_are_wipe_nodes_partitions_are_not(monkeypatch):
    monkeypatch.setattr("os.path.realpath", lambda path: path)
    assert normalize_whole_disk("/dev/xvda") == "/dev/xvda"
    assert normalize_whole_disk("/dev/dasda") == "/dev/dasda"
    assert normalize_whole_disk("/dev/hda") == "/dev/hda"
    for partition in ("/dev/xvda1", "/dev/dasda1", "/dev/hda1"):
        with pytest.raises(SafetyError, match="whole-disk"):
            normalize_whole_disk(partition)


# ---------------------------------------------------------------------------
# Progress / verification parsing
# ---------------------------------------------------------------------------


def test_target_verification_mismatch_beats_erased_row_and_exit_zero():
    log = (
        "Verification mismatch on '/dev/vda' at offset 4096\n"
        "vda | Erased |\n"
        "Nwipe successfully completed\n"
    )
    ok, detail, reason = evaluate_nwipe_outcome(0, log, "/dev/vda")
    assert not ok
    assert reason == "verification_failed"
    assert "verification" in detail.lower()


def test_partition_verification_mismatch_is_not_attributed_to_parent_disk():
    log = (
        "Verification mismatch on '/dev/vda1' at offset 1\n"
        "vda | Erased |\n"
        "Nwipe successfully completed\n"
    )
    ok, _, reason = evaluate_nwipe_outcome(0, log, "/dev/vda")
    assert ok and reason == "completed"


def test_invalid_completion_metadata_is_indeterminate():
    ok, detail, reason = evaluate_nwipe_outcome(None, "vda | Erased |", "/dev/vda")
    assert not ok
    assert reason == "indeterminate"
    assert "invalid" in detail.lower()


# ---------------------------------------------------------------------------
# Cancellation before SIGUSR1 / at 0% progress
# ---------------------------------------------------------------------------


def test_cancel_before_sigusr1_ready_is_cancelled_not_finished(tmp_path, monkeypatch):
    import signal

    from beamo_wipe.nwipe_runner import NwipeRunner

    signals = []

    class FakeProc:
        returncode = None

        def poll(self):
            return self.returncode

        def send_signal(self, value):
            signals.append(value)

        def terminate(self):
            self.returncode = 143

        def wait(self, timeout):
            return self.returncode

        def kill(self):
            self.returncode = 9

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.subprocess.Popen", lambda *a, **kw: FakeProc()
    )
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(tmp_path / "fake_nwipe_startup"))
    runner.start(req)
    runner.poll(req)
    assert not runner._sigusr1_armed
    assert signals == []
    runner.cancel()
    assert runner.result is not None
    assert not runner.result.ok
    assert runner.result.reason == "cancelled"
    assert runner._proc is None
    assert signal.SIGUSR1 not in signals


def test_cancel_at_zero_progress_is_interrupted_never_finished(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()
    clock = Clock()
    runner = DryRunRunner(duration_s=10.0, clock=clock)
    wiz = Wizard(base.discovery, runner, clock=clock, dry_run=True)
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    assert runner.progress is None
    wiz.cancel_wipe()
    assert wiz.screen == Screen.DONE
    assert wiz.wipe_result is not None
    assert not wiz.wipe_result.ok
    assert wiz.wipe_result.summary == "interrupted"
    assert wiz.evidence is not None
    assert wiz.evidence["outcome"] == OUTCOME_INTERRUPTED
    assert runner.progress != 100.0
    assert not wiz.done_ok
