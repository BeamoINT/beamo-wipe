# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression proofs from the 2026-09-03 accountable safety audit.

Every device and process boundary in this file is fake or monkeypatched.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from beamo_wipe.discover import (
    _validate_real_lsblk_metadata,
    identify_boot_path,
    parent_disk_path,
    parse_lsblk_json,
)
from beamo_wipe.evidence import (
    OUTCOME_FAILED,
    build_evidence,
    export_evidence,
    verify_evidence_checksum,
)
from beamo_wipe.models import DiskKind, MethodId, Screen, WipeRequest, WipeResult
from beamo_wipe.nwipe_runner import (
    NwipeRunner,
    _target_job_percent,
    evaluate_nwipe_completion,
)
from beamo_wipe.safety import (
    SafetyError,
    _log_filesystem_is_target,
    assert_disk_identity,
    truncate_log_file,
)
from beamo_wipe.wizard import Wizard, make_demo_wizard


def _node(name: str, *, boot: bool = False, **extra):
    node = {
        "name": name,
        "path": f"/dev/{name}",
        "type": "disk",
        "size": 10_000_000_000,
        "ro": False,
        "mountpoint": None,
        "mountpoints": [],
        "tran": "usb" if boot else "sata",
        "rota": True,
        "model": "Boot" if boot else "Target",
        "serial": f"SER-{name}",
    }
    node.update(extra)
    return node


@pytest.mark.parametrize(
    "line",
    [
        "Found /dev/vda, SCSI, USB | Erased |, S/N=x",
        "Found /dev/vda, SCSI, : 100.00%, round 1 of 1, pass 1 of 1",
        "/dev/vda: 100.00%, round 0 of 0",
        "/dev/vda: 100.00%, round 1 of 1, pass 0 of 0",
        "/dev/vda: 100.00%, round 2 of 1, pass 1 of 1",
    ],
)
def test_untrusted_or_malformed_log_lines_cannot_complete(line):
    assert evaluate_nwipe_completion(0, line, "/dev/vda") == (
        False,
        "nwipe exited without wiping",
    )


def test_exact_status_row_and_progress_still_complete():
    assert evaluate_nwipe_completion(0, " vda | Erased | 1 MB/s | 00:01 | disk", "/dev/vda")[0]
    assert evaluate_nwipe_completion(
        0,
        "/dev/vda: 100.00%, round 1 of 1, pass 1 of 1, eta 00:00:00",
        "/dev/vda",
    )[0]
    assert evaluate_nwipe_completion(
        0,
        "[2026/09/03 12:34:56]    info: /dev/vda: 100.00%, round 1 of 1, pass 1 of 1, eta 00:00:00",
        "/dev/vda",
    )[0]


def test_pinned_nwipe_progress_is_not_normalized_twice():
    line = "/dev/vda: 66.67%, round 1 of 1, pass 3 of 3, eta 00:01:00"
    assert _target_job_percent(line, "/dev/vda") == 66.67


def test_huge_progress_counter_is_ignored_not_raised():
    digits = "9" * 5000
    line = f"/dev/vda: 100.00%, round {digits} of {digits}"
    assert evaluate_nwipe_completion(0, line, "/dev/vda")[0] is False


def test_duplicate_start_preserves_active_log(tmp_path, monkeypatch):
    log = tmp_path / "active.log"
    log.write_text("active progress\n", encoding="utf-8")
    runner = NwipeRunner(binary=str(tmp_path / "fake-engine"))
    runner._proc = object()  # type: ignore[assignment]
    req = WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(log))
    with pytest.raises(SafetyError, match="already running"):
        runner.start(req)
    assert log.read_text(encoding="utf-8") == "active progress\n"


def test_cross_process_lock_refusal_precedes_log_truncation(tmp_path, monkeypatch):
    import beamo_wipe.nwipe_runner as nr

    log = tmp_path / "active.log"
    log.write_text("other process progress\n", encoding="utf-8")
    runner = nr.NwipeRunner(binary=str(tmp_path / "fake-engine"))
    request = WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sr0", str(log))
    truncated = []

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr(nr, "assert_log_not_on_target", lambda *_a, **_k: None)

    def truncate(*_args):
        truncated.append(True)
        log.write_text("", encoding="utf-8")

    monkeypatch.setattr(nr, "truncate_log_file", truncate)
    monkeypatch.setattr(
        runner,
        "_acquire_wipe_lock",
        lambda _request: (_ for _ in ()).throw(SafetyError("A wipe is already running.")),
    )

    with pytest.raises(SafetyError, match="already running"):
        runner.start(request)
    assert truncated == []
    assert log.read_text(encoding="utf-8") == "other process progress\n"


def test_locked_boundary_rechecks_size_before_exec(monkeypatch):
    import beamo_wipe.nwipe_runner as nr

    runner = nr.NwipeRunner()
    req = WipeRequest(
        "/dev/vda", MethodId.EVERYDAY, "/dev/sdb", "/tmp/fake.log",
        device_rdev=1, device_size_bytes=500, boot_rdev=2,
    )
    calls = 0

    def size_check(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SafetyError("Disk size changed")

    monkeypatch.setattr(nr, "require_real_live_for_nwipe", lambda: None)
    monkeypatch.setattr(nr, "pinned_nwipe_already_running", lambda **_k: False)
    monkeypatch.setattr(nr, "_verify_pinned_nwipe", lambda _p: None)
    monkeypatch.setattr(nr, "assert_existing_is_block_device", lambda *_a, **_k: None)
    monkeypatch.setattr(nr, "assert_size_unchanged", size_check)
    monkeypatch.setattr(nr, "assert_local_device_transport", lambda *_a: None)
    monkeypatch.setattr(nr, "block_rdev", lambda p: 1 if p == "/dev/vda" else 2)
    monkeypatch.setattr(nr, "assert_not_boot", lambda *_a, **_k: None)
    monkeypatch.setattr(nr, "assert_log_not_on_target", lambda *_a, **_k: None)
    monkeypatch.setattr(nr, "truncate_log_file", lambda *_a, **_k: None)
    monkeypatch.setattr(runner, "_acquire_wipe_lock", lambda _r: None)
    monkeypatch.setattr(nr.subprocess, "Popen", lambda *_a, **_k: pytest.fail("exec reached"))
    with pytest.raises(SafetyError, match="size changed"):
        runner.start(req)
    assert calls == 2


def test_version_probe_requires_zero_exit(monkeypatch):
    import beamo_wipe.nwipe_runner as nr

    monkeypatch.setattr(nr, "assert_nwipe_binary_safe", lambda _p: None)
    monkeypatch.setattr(
        nr.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(
            returncode=1, stdout="nwipe version 0.42\n", stderr=""
        ),
    )
    with pytest.raises(SafetyError, match="pinned version"):
        nr._verify_pinned_nwipe("/usr/lib/beamo-wipe/nwipe")


def test_permission_denied_proc_probe_is_fail_closed(monkeypatch):
    import beamo_wipe.nwipe_runner as nr

    monkeypatch.setattr(nr.os.path, "realpath", lambda p: p)
    monkeypatch.setattr(nr.os, "listdir", lambda _p: ["4242"])
    monkeypatch.setattr(
        nr.os,
        "readlink",
        lambda _p: (_ for _ in ()).throw(PermissionError(errno.EACCES, "denied")),
    )
    monkeypatch.setattr(nr, "_try_log_diag", lambda *_a: None)
    assert nr.pinned_nwipe_already_running() is True


def test_scalar_mountpoint_and_flat_partition_are_not_selectable():
    target = _node("sda", mountpoints="/media/target")
    boot = _node("sdb", boot=True)
    result = parse_lsblk_json({"blockdevices": [target, boot]}, boot_path="/dev/sdb")
    assert result.selectable == ()

    target = _node("sda")
    partition = {
        "name": "sda1", "path": "/dev/sda1", "type": "part", "pkname": "sda",
        "mountpoint": "/media/target", "mountpoints": ["/media/target"],
    }
    result = parse_lsblk_json(
        {"blockdevices": [target, partition, boot]}, boot_path="/dev/sdb"
    )
    assert result.selectable == ()


def test_invalid_mountpoint_shape_is_rejected():
    with pytest.raises(ValueError, match="mountpoints"):
        _validate_real_lsblk_metadata(
            {"blockdevices": [_node("sda", mountpoints={"bad": "shape"})]}
        )


def test_multiparent_boot_owner_is_ambiguous():
    tree = [
        _node("sda", children=[{"name": "md0", "path": "/dev/md0", "type": "raid1"}]),
        _node("sdb", children=[{"name": "md0", "path": "/dev/md0", "type": "raid1"}]),
    ]
    assert parent_disk_path("/dev/md0", tree) is None


def test_boot_wwn_alias_is_never_selectable():
    target = _node("sda", wwn="same-lun")
    boot = _node("sdb", boot=True, wwn="SAME-LUN")
    result = parse_lsblk_json({"blockdevices": [target, boot]}, boot_path="/dev/sdb")
    assert [d.path for d in result.selectable] == []
    assert next(d for d in result.disks if d.path == "/dev/sda").is_boot


def test_control_character_device_path_is_rejected_not_repaired():
    target = _node("sda", path="/dev/sd\x00a")
    boot = _node("sdb", boot=True)
    result = parse_lsblk_json({"blockdevices": [target, boot]}, boot_path="/dev/sdb")
    assert result.selectable == ()


def test_conflicting_cmdline_boot_tokens_fail_closed():
    nodes = [_node("sda"), _node("sdb", boot=True)]
    assert identify_boot_path(
        nodes, mount_sources=[], cmdline="bootfrom=/dev/sda live-media=/dev/sdb"
    ) is None


def test_transport_and_media_class_are_part_of_rediscovery_identity():
    base = make_demo_wizard().discovery
    selected = base.selectable[0]
    changed = replace(selected, bus="USB", kind=DiskKind.SSD)
    fresh = replace(base, disks=(changed, base.boot), selectable=(changed,))
    with pytest.raises(SafetyError, match="identity changed"):
        assert_disk_identity(selected, fresh)


def test_hardlinked_log_is_rejected_before_truncate(tmp_path, monkeypatch):
    victim = tmp_path / "victim"
    log = tmp_path / "wipe.log"
    victim.write_text("KEEP", encoding="utf-8")
    os.link(victim, log)
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    with pytest.raises(SafetyError, match="linked"):
        truncate_log_file(str(log), "/dev/vda")
    assert victim.read_text(encoding="utf-8") == "KEEP"


def test_root_mounted_target_is_detected(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("1 0 0:1 / / rw - ext4 /dev/vda1 rw\n", encoding="utf-8")
    monkeypatch.setattr("beamo_wipe.discover.MOUNTINFO_PATH", str(mountinfo))
    assert _log_filesystem_is_target(Path("/tmp/beamo-wipe/log"), "/dev/vda")


def test_evidence_revalidates_contradictory_success():
    base = make_demo_wizard()
    disk = base.discovery.selectable[0]
    request = WipeRequest(
        disk.path, MethodId.EVERYDAY, base.discovery.boot.path, "/tmp/fake.log"
    )
    for result, log in (
        (WipeResult(True, 1, "finished", request.logfile), f"{disk.path}: 100.00%, round 1 of 1"),
        (WipeResult(True, 0, "finished", request.logfile), ""),
    ):
        evidence = build_evidence(
            disk=disk, discovery=base.discovery, method=MethodId.EVERYDAY,
            request=request, result=result, started_at_wall="a", ended_at_wall="b",
            started_mono=0.0, ended_mono=1.0, argv=[], log_text=log,
        )
        assert evidence["outcome"] == OUTCOME_FAILED
        assert evidence["verification"]["verified"] is False


def _seed_evidence(path: Path, data: bytes = b"{}\n") -> None:
    path.write_bytes(data)
    Path(str(path) + ".sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  {path.name}\n", encoding="ascii"
    )


def test_export_copies_the_bytes_it_authenticated(tmp_path, monkeypatch):
    import beamo_wipe.evidence as evidence

    src = tmp_path / "src.json"
    dest = tmp_path / "usb"
    dest.mkdir()
    _seed_evidence(src, b'{"safe":true}\n')
    original = evidence._read_regular_nofollow
    reads = 0

    def replace_after_data(path):
        nonlocal reads
        data = original(path)
        reads += 1
        if Path(path) == src:
            src.write_bytes(b'{"forged":true}\n')
        return data

    monkeypatch.setattr(evidence, "_read_regular_nofollow", replace_after_data)
    out = export_evidence(src, dest)
    assert out.read_bytes() == b'{"safe":true}\n'
    assert reads == 2  # source and its sidecar, never a second source read


def test_export_sidecar_failure_is_retryable(tmp_path, monkeypatch):
    import beamo_wipe.evidence as evidence

    src = tmp_path / "src.json"
    dest = tmp_path / "usb"
    dest.mkdir()
    _seed_evidence(src)
    original = evidence._atomic_write_bytes
    calls = 0

    def fail_second(path, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sidecar full")
        return original(path, data)

    monkeypatch.setattr(evidence, "_atomic_write_bytes", fail_second)
    with pytest.raises(OSError, match="sidecar"):
        export_evidence(src, dest)
    assert not (dest / src.name).exists()
    monkeypatch.setattr(evidence, "_atomic_write_bytes", original)
    assert verify_evidence_checksum(export_evidence(src, dest))


def test_export_post_rename_fsync_failure_is_retryable(tmp_path, monkeypatch):
    """A USB directory-sync error must not strand an orphan JSON forever."""
    import stat

    import beamo_wipe.evidence as evidence

    src = tmp_path / "src.json"
    dest = tmp_path / "usb"
    dest.mkdir()
    _seed_evidence(src)
    original_fsync = evidence.os.fsync

    def fail_directory_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("USB directory sync failed")
        return original_fsync(fd)

    monkeypatch.setattr(evidence.os, "fsync", fail_directory_sync)
    with pytest.raises(OSError, match="directory sync"):
        export_evidence(src, dest)
    assert not (dest / src.name).exists()
    assert not Path(str(dest / src.name) + ".sha256").exists()

    monkeypatch.setattr(evidence.os, "fsync", original_fsync)
    assert verify_evidence_checksum(export_evidence(src, dest))


def _drive_to_working(wizard: Wizard) -> None:
    wizard.skip_splash()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.selectable[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    wizard._erase_until = 0
    wizard.confirm_erase()


def test_cancel_preserves_completion_that_won_race(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()

    class Runner:
        progress = 99.0
        result = None
        _log_tail = ""

        def start(self, request):
            self.request = request
            self._log_tail = f"{request.device}: 100.00%, round 1 of 1, pass 1 of 1\n"

        def poll(self, _request):
            return self.result

        def cancel(self):
            self.result = WipeResult(True, 0, "finished", self.request.logfile)

    runner = Runner()
    wizard = Wizard(base.discovery, runner, dry_run=True)
    _drive_to_working(wizard)
    wizard.cancel_wipe()
    assert wizard.wipe_result is runner.result
    assert wizard.done_ok
    assert wizard.evidence["outcome"] == "verified"


def test_delayed_started_evidence_cannot_replace_terminal_evidence(tmp_path, monkeypatch):
    import beamo_wipe.evidence as evidence

    entered = threading.Event()
    release = threading.Event()

    class Runner:
        progress = 100.0
        result = None
        _log_tail = ""

        def start(self, request):
            self.request = request
            self._log_tail = f"{request.device}: 100.00%, round 1 of 1, pass 1 of 1\n"
            self.result = WipeResult(True, 0, "finished", request.logfile)

        def poll(self, _request):
            return self.result

        def cancel(self):
            return None

    def fake_write(ev, **_kwargs):
        outcome = ev["outcome"]
        if outcome == "started":
            entered.set()
            assert release.wait(5)
        path = tmp_path / f"{outcome}.json"
        path.write_text(json.dumps(ev), encoding="utf-8")
        return path

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(evidence, "write_evidence_atomic", fake_write)
    monkeypatch.setattr(evidence, "verify_evidence_checksum", lambda _p: True)
    base = make_demo_wizard()
    wizard = Wizard(base.discovery, Runner(), dry_run=True)
    thread = threading.Thread(target=lambda: _drive_to_working(wizard))
    thread.start()
    assert entered.wait(5)
    wizard.tick()
    assert wizard.evidence["outcome"] == "verified"
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert wizard.evidence["outcome"] == "verified"
    assert Path(wizard.evidence_path).name == "verified.json"


def test_countdown_display_uses_true_ceiling():
    wizard = make_demo_wizard()
    wizard.screen = Screen.LAST_CHANCE
    wizard._erase_until = wizard.now + 4.001
    assert wizard.countdown_display == 5


def test_shutdown_nonzero_tries_the_next_command(monkeypatch):
    from beamo_wipe import app
    import subprocess as subprocess_module

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0)

    monkeypatch.setattr(subprocess_module, "run", fake_run)
    assert app._shutdown() is True
    assert len(calls) == 2


def test_live_tk_failure_returns_to_supervisor_before_console(monkeypatch):
    from beamo_wipe import app

    fake = SimpleNamespace(
        wants_shutdown=False,
        dry_run=False,
        screen=Screen.WHAT,
        cancel_wipe=lambda: None,
    )
    console_calls = []
    monkeypatch.setattr(app, "running_on_live_usb", lambda: False)
    monkeypatch.setattr(app.signal, "signal", lambda *_a: None)
    monkeypatch.setattr(app, "_build_wizard", lambda _args: fake)
    monkeypatch.setattr(
        "beamo_wipe.ui.tk_wizard.run_tk",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no display")),
    )
    monkeypatch.setattr(
        "beamo_wipe.ui.console_wizard.run_console",
        lambda *_a, **_k: console_calls.append(True) or 0,
    )
    assert app.main([]) == 3
    assert console_calls == []


def test_plain_console_cancel_works_without_sigint(monkeypatch):
    import io
    from beamo_wipe.ui import console_wizard

    cancelled = []
    fake = SimpleNamespace(
        wants_shutdown=False,
        screen=Screen.WORKING,
        preview=False,
        progress=None,
        evidence_error=None,
        error=None,
        selected=None,
        tick=lambda: None,
    )

    def cancel():
        cancelled.append(True)
        fake.wants_shutdown = True

    fake.cancel_wipe = cancel
    monkeypatch.setattr(console_wizard.select, "select", lambda *_a: ([object()], [], []))
    monkeypatch.setattr(console_wizard.sys, "stdin", io.StringIO("CANCEL\n"))
    assert console_wizard._plain_loop_body(fake) == 0
    assert cancelled == [True]


def test_diagnostics_write_loop_handles_short_writes(monkeypatch):
    from beamo_wipe.diagnostics import _write_all

    written = bytearray()

    def short_write(_fd, data):
        chunk = bytes(data[:1])
        written.extend(chunk)
        return len(chunk)

    monkeypatch.setattr(os, "write", short_write)
    _write_all(123, b"complete\n")
    assert bytes(written) == b"complete\n"


def test_serial_marker_is_bounded_and_written_to_character_device(monkeypatch):
    import stat

    from beamo_wipe import diagnostics

    written = bytearray()
    closed = []
    monkeypatch.setattr(diagnostics.os, "open", lambda *_args, **_kwargs: 41)
    monkeypatch.setattr(
        diagnostics.os,
        "fstat",
        lambda _fd: SimpleNamespace(st_mode=stat.S_IFCHR),
    )
    monkeypatch.setattr(
        diagnostics.os,
        "write",
        lambda _fd, data: written.extend(bytes(data)) or len(data),
    )
    monkeypatch.setattr(diagnostics.os, "close", closed.append)

    assert diagnostics.emit_serial_marker("BEAMO_WIPE_SCREEN_DONE") is True
    assert written == b"BEAMO_WIPE_SCREEN_DONE\n"
    assert closed == [41]

    written.clear()
    assert diagnostics.emit_serial_marker("BEAMO_WIPE_SCREEN_/dev/sda") is False
    assert diagnostics.emit_serial_marker("BEAMO_WIPE_" + "A" * 65) is False
    assert written == b""


def test_read_diagnostics_reads_tail_not_old_prefix(tmp_path):
    from beamo_wipe.diagnostics import DIAG_LOG_MAX_BYTES, read_diagnostics

    path = tmp_path / "diagnostics.log"
    old = json.dumps({"code": "OLD", "pad": "x" * 1000}) + "\n"
    latest = json.dumps({"code": "LATEST"}) + "\n"
    path.write_text(old * (DIAG_LOG_MAX_BYTES // len(old) + 4) + latest, encoding="utf-8")
    assert read_diagnostics(tmp_path, limit=1) == [{"code": "LATEST"}]


def test_qemu_gate_requires_rendered_kiosk_screen_and_media_readback():
    root = Path(__file__).resolve().parents[1]
    qemu = (root / "scripts/qemu-verify.sh").read_text(encoding="utf-8")
    kiosk = (
        root
        / "packaging/live/config/includes.chroot/usr/local/sbin/beamo-wipe-kiosk"
    ).read_text(encoding="utf-8")
    assert "BEAMO_WIPE_KIOSK_READY" in kiosk
    assert "BEAMO_WIPE_KIOSK_READY" in qemu
    assert 'BEAMO_WIPE_SCREEN_WHAT "$BOOT_WAIT_SECONDS"' in qemu
    assert "never rendered the shipped Tk WHAT screen" in qemu
    assert "chunk = b\"\\xa5\"" in qemu
    assert 'cmp -n 268435456 "$TARGET_RAW" /dev/zero' in qemu


def test_build_omits_bytecode_and_enforces_wrapper_version():
    root = Path(__file__).resolve().parents[1]
    build = (root / "scripts/build-iso.sh").read_text(encoding="utf-8")
    inside = (root / "packaging/live/inside-docker.sh").read_text(encoding="utf-8")
    assert "WRAPPER_VERSION" in build
    assert "git ls-files -- src/beamo_wipe" in build
    assert "-name '*.pyc'" in build
    assert "--exclude '*.pyc'" in inside
    assert "unapproved live-build hook" in build
    assert ".bundle-backup." in build
