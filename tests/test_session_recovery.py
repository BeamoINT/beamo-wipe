# SPDX-License-Identifier: GPL-3.0-or-later
"""Every inventory/engine is fake. No host block device is opened or erased."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from beamo_wipe.evidence import build_evidence, write_evidence_atomic
from beamo_wipe.models import MethodId, Screen, WipeRequest, WipeResult
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.safety import SafetyError
from beamo_wipe.session_recovery import SessionStore, NAME, _bytes
from beamo_wipe.wizard import Wizard
from test_usb_report_workflow import _payload, _discovery, _success_receipt

BOOT = "00000000-0000-0000-0000-000000000001"
BUILD = "a" * 64


@pytest.fixture
def session(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setattr("beamo_wipe.safety.DEFAULT_LOG_DIR", directory)
    opened = []

    def factory(**kw):
        store = SessionStore(
            directory, boot=kw.get("boot", BOOT), build=kw.get("build", BUILD)
        )
        opened.append(store)
        return store.open()

    yield factory
    for store in opened:
        store.close()


def armed(store, method=MethodId.QUICK_ZERO):
    _, disks = _payload()
    discovery = _discovery(disks)
    request = WipeRequest(
        discovery.selectable[0].path,
        method,
        discovery.boot.path,
        str(store.directory / "nwipe-test.log"),
    )
    store.arm(discovery, request)
    return discovery, request


def finish(store, discovery, request):
    log = f"{Path(request.device).name} | Erased |\n"
    Path(request.logfile).write_text(log)
    os.chmod(request.logfile, 0o600)
    ev = build_evidence(
        disk=discovery.selectable[0],
        discovery=discovery,
        method=request.method,
        request=request,
        result=WipeResult(True, 0, "done", request.logfile),
        started_at_wall="",
        ended_at_wall="",
        started_mono=time.monotonic(),
        ended_mono=time.monotonic(),
        argv=[],
        log_text=log,
    )
    path = write_evidence_atomic(
        ev,
        log_dir=store.directory,
        device_path=request.device,
        target_device=request.device,
    )
    store.finish(path)
    return path


def recover(store):
    _, disks = _payload()
    runner = DryRunRunner()
    w = Wizard(_discovery(disks), runner)
    w.enable_session_recovery(store)
    assert w._wipe_request is None and not w.owner_ok and not w.confirm_input
    assert w._erase_until is None and runner._started is None
    w.confirm_erase()
    w.tick()
    assert runner._started is None
    return w


@pytest.mark.parametrize("method", list(MethodId))
def test_completed_recovered_only_with_pinned_evidence_and_log(session, method):
    first = session()
    discovery, request = armed(first, method)
    path = finish(first, discovery, request)
    first.close()
    second = session()
    w = recover(second)
    assert w.screen == Screen.DONE and w.done_ok and w.can_save_report
    assert w.evidence_path == str(path)
    assert (
        "restart" in w.result_view.next_step and "power loss" in w.result_view.next_step
    )
    assert w.report_status == "idle" and w._saved_report_claim is None
    w._report_exporter = _success_receipt
    w.save_report_to_usb()
    assert w.report_status == "saved"


@pytest.mark.parametrize(
    "boundary",
    ["discovery", "confirmation", "writing", "verification", "final_save", "export"],
)
def test_process_crash_boundaries_never_resume(session, boundary):
    first = session()
    if boundary not in {"discovery", "confirmation"}:
        discovery, request = armed(first)
        if boundary in {"writing", "verification"}:
            Path(request.logfile).write_text("100% writing\n100% verification\n")
            os.chmod(request.logfile, 0o600)
        if boundary in {"final_save", "export"}:
            path = finish(first, discovery, request)
            if boundary == "final_save":
                Path(str(path) + ".sha256").unlink()
    first.close()  # loss of all UI memory, not a clean shutdown checkpoint
    w = recover(session())
    assert w.done_ok is (boundary == "export")
    assert w.report_status != "saved"
    if boundary in {"discovery", "confirmation"}:
        assert w.screen == Screen.PICK_BLOCKED and w.can_open_diagnostic
    elif boundary != "export":
        assert w.result_view.code == "indeterminate" and w.can_save_report
        assert w.evidence["exit_evidence"]["exit_code"] is None
        w._report_exporter = _success_receipt
        w.save_report_to_usb()
        assert w.report_status == "saved"


@pytest.mark.parametrize(
    "mutation",
    [
        "json",
        "digest",
        "boot",
        "build",
        "schema0",
        "schema2",
        "bool_schema",
        "partial",
        "contradictory",
        "duplicate",
        "future",
    ],
)
def test_corrupt_foreign_and_migration_records_are_rejected(session, mutation):
    first = session()
    armed(first)
    path = first.directory / NAME
    envelope = json.loads(path.read_bytes())
    record = envelope["payload"]
    if mutation == "json":
        data = b"{"
    elif mutation == "duplicate":
        data = b'{"payload":{},"payload":{},"sha256":"x"}'
    else:
        if mutation == "boot":
            record["boot"] = BOOT[:-1] + "2"
        if mutation == "build":
            record["build"] = "b" * 64
        if mutation == "schema0":
            record["schema"] = 0
        if mutation == "schema2":
            record["schema"] = 2
        if mutation == "bool_schema":
            record["schema"] = True
        if mutation == "partial":
            record.pop("context")
        if mutation == "contradictory":
            record["context"]["target"] = record["context"]["boot"]
        if mutation == "future":
            record["created"] = time.monotonic() + 10000
        envelope["sha256"] = (
            hashlib.sha256(_bytes(record)).hexdigest()
            if mutation != "digest"
            else "b" * 64
        )
        data = _bytes(envelope)
    path.write_bytes(data)
    first.close()
    second = session()
    assert second.invalid
    w = recover(second)
    assert not w.done_ok and not w.can_save_report and w.can_open_diagnostic


@pytest.mark.parametrize("name", [NAME, "interface.lock", "wipe.lock"])
@pytest.mark.parametrize("mode", [0o644, 0o666, 0o400])
def test_unsafe_file_permissions_fail_closed(session, name, mode):
    first = session()
    armed(first)
    path = first.directory / name
    if not path.exists():
        path.touch(mode=0o600)
    path.chmod(mode)
    first.close()
    if name == "interface.lock":
        with pytest.raises((SafetyError, OSError)):
            session()
    else:
        w = recover(session())
        assert not w.done_ok and not w.can_save_report
        if name == "wipe.lock":
            assert not w.can_open_diagnostic


def test_unsafe_directory_is_not_repaired(session):
    first = session()
    first.directory.chmod(0o755)
    first.close()
    with pytest.raises((SafetyError, OSError)):
        session()
    assert first.directory.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("link", ["symbolic", "hard"])
def test_linked_state_is_rejected(session, link):
    first = session()
    armed(first)
    path = first.directory / NAME
    original = first.directory / "original"
    path.rename(original)
    if link == "symbolic":
        path.symlink_to(original)
    else:
        os.link(original, path)
    first.close()
    second = session()
    assert second.invalid and not recover(second).done_ok


def test_concurrent_ui_owners_and_orphan_runner(session):
    first = session()
    armed(first)
    with pytest.raises(BlockingIOError):
        session()
    path = first.directory / "wipe.lock"
    # Fake child owns the same inherited lock protocol, but never executes nwipe.
    code = "import fcntl,os,sys; f=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.read()"
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        first.close()
        second = session()
        w = recover(second)
        assert "may still be running" in w.error
        assert not w.can_save_report and not w.can_open_diagnostic
        w.shutdown()
        assert not w.wants_shutdown
        child.communicate("", timeout=10)
        w.tick()
        assert w.result_view.code == "indeterminate" and w.can_save_report
        # Recovery keeps the runner lock until the UI exits.
        fd = os.open(path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


@pytest.mark.parametrize("fault", ["write", "fsync", "replace"])
def test_atomic_crash_keeps_prior_record_and_never_launches(
    session, monkeypatch, fault
):
    first = session()
    previous = (first.directory / NAME).read_bytes()

    def crash(*args, **kwargs):
        raise OSError("injected crash")

    with monkeypatch.context() as patch:
        patch.setattr(os, fault, crash)
        with pytest.raises(OSError):
            armed(first)
    assert (first.directory / NAME).read_bytes() == previous
    first.close()
    w = recover(session())
    assert w.screen == Screen.PICK_BLOCKED and not w.done_ok


def test_missing_journal_does_not_migrate_legacy_logs_or_results(session):
    first = session()
    armed(first)
    Path(first.record["context"]["logfile"]).touch(mode=0o600)
    (first.directory / NAME).unlink()
    first.close()
    second = session()
    assert second.invalid and recover(second).screen == Screen.PICK_BLOCKED


@pytest.mark.parametrize(
    "field", ["log", "log_mode", "evidence_mode", "sidecar", "identity"]
)
def test_success_requires_all_terminal_proof(session, field):
    first = session()
    discovery, request = armed(first)
    path = finish(first, discovery, request)
    if field == "log":
        Path(request.logfile).write_text("100%\n")
    if field == "log_mode":
        Path(request.logfile).chmod(0o644)
    if field == "evidence_mode":
        path.chmod(0o644)
    if field == "sidecar":
        Path(str(path) + ".sha256").unlink()
    if field == "identity":
        evidence = json.loads(path.read_bytes())
        evidence["device"]["serial"] = "FOREIGN"
        path.write_text(json.dumps(evidence))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        Path(str(path) + ".sha256").write_text(f"{digest}  {path.name}\n")
        first.save({"terminal": {"name": path.name, "sha256": digest}})
    first.close()
    w = recover(session())
    assert w.result_view.code == "indeterminate" and not w.done_ok


def test_unknown_boot_identity_refuses_startup(tmp_path):
    store = SessionStore(tmp_path / "private", boot="", build=BUILD)
    try:
        with pytest.raises(SafetyError):
            store.open()
    finally:
        store.close()


@pytest.mark.parametrize(
    "boundary",
    ["discovery", "confirmation", "writing", "verification", "final_save", "export"],
)
def test_abrupt_process_exit_at_each_boundary(tmp_path, monkeypatch, boundary):
    directory = tmp_path / "private"
    monkeypatch.setattr("beamo_wipe.safety.DEFAULT_LOG_DIR", directory)
    # A genuinely separate process dies without finally blocks, store.close(),
    # cancellation or a terminal checkpoint. Only ordinary temporary files exist.
    code = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_session_recovery import SessionStore, BOOT, BUILD, armed, finish
from beamo_wipe import safety, evidence
safety.DEFAULT_LOG_DIR = Path(sys.argv[2])
s = SessionStore(safety.DEFAULT_LOG_DIR, boot=BOOT, build=BUILD).open()
boundary = sys.argv[3]
if boundary not in {"discovery", "confirmation"}:
    discovery, request = armed(s)
    if boundary in {"writing", "verification"}:
        Path(request.logfile).write_text("100% " + boundary)
        os.chmod(request.logfile, 0o600)
    elif boundary == "final_save":
        original = evidence._atomic_write_bytes
        def crash(path, data):
            original(path, data)
            if str(path).endswith(".json"):
                os._exit(73)
        evidence._atomic_write_bytes = crash
        finish(s, discovery, request)
    else:
        finish(s, discovery, request)
        # An incomplete export is outside the recovery journal. It cannot
        # restore a saved receipt, even if it has a COMPLETE-looking name.
        (s.directory / "COMPLETE").write_text("not a verified receipt")
os._exit(73)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(Path(__file__).parent),
            str(directory),
            boundary,
        ],
        env=env,
        timeout=15,
    )
    assert result.returncode == 73
    store = SessionStore(directory, boot=BOOT, build=BUILD)
    try:
        store.open()
        w = recover(store)
        assert w.done_ok is (boundary == "export")
        assert not w._has_verified_export_locked()
    finally:
        store.close()


def test_controller_checkpoint_failure_prevents_fake_runner_start(session, monkeypatch):
    from test_refresh_disks import authorized

    w = authorized()
    store = session()
    w.enable_session_recovery(store)

    def fail(*a, **kw):
        raise OSError("injected checkpoint failure")

    monkeypatch.setattr(store, "arm", fail)
    w.confirm_erase()
    assert not w.runner.started and w._wipe_request is None


def test_preflight_is_saved_before_discovery_and_recovery_survives_discovery_failure(
    session, monkeypatch
):
    from beamo_wipe import app, session_recovery

    first = session()
    directory = first.directory
    first.close()
    monkeypatch.setattr(
        session_recovery,
        "SessionStore",
        lambda: SessionStore(directory, boot=BOOT, build=BUILD),
    )
    monkeypatch.setattr(app, "running_on_live_usb", lambda: True)
    monkeypatch.setattr(app, "apply_live_session_overrides", lambda args: None)

    def discover_failure(args, **_kwargs):
        assert (directory / NAME).exists()
        raise OSError("discovery crash")

    monkeypatch.setattr(app, "_build_wizard", discover_failure)

    def ui(w):
        assert w._recovered and w.screen == Screen.PICK_BLOCKED
        assert not w.done_ok and w._wipe_request is None
        return 3

    monkeypatch.setattr("beamo_wipe.ui.console_wizard.run_console", ui)
    assert app.main(["--console"]) == 3


def test_export_failure_after_recovery_remains_retryable(session):
    first = session()
    discovery, request = armed(first)
    finish(first, discovery, request)
    first.close()
    w = recover(session())

    def failure(**kw):
        raise OSError("export interrupted")

    w._report_exporter = failure
    w.save_report_to_usb()
    assert w.report_status == "error" and not w._has_verified_export_locked()
    assert w.can_save_report
    w._report_exporter = _success_receipt
    w.save_report_to_usb()
    assert w.report_status == "saved" and w._has_verified_export_locked()


@pytest.mark.parametrize("mode", ["replace", "directory_fsync"])
def test_crash_after_terminal_evidence_before_journal_commit(
    session, monkeypatch, mode
):
    first = session()
    discovery, request = armed(first)
    original_replace, original_fsync = os.replace, os.fsync

    def replace(*a, **kw):
        if a[1] == NAME:
            raise OSError("journal commit failed")
        return original_replace(*a, **kw)

    def fsync(fd):
        if fd == first.fd:
            raise OSError("directory fsync failed")
        return original_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(
            os,
            "replace" if mode == "replace" else "fsync",
            replace if mode == "replace" else fsync,
        )
        with pytest.raises(OSError):
            finish(first, discovery, request)
    first.close()
    w = recover(session())
    # A rename visible in this same boot may be read back and independently
    # validated after a failed fsync. Without the commit, old armed state wins.
    assert w.done_ok is (mode == "directory_fsync")


def test_contradictory_terminal_clock_is_not_success(session):
    first = session()
    discovery, request = armed(first)
    path = finish(first, discovery, request)
    evidence = json.loads(path.read_bytes())
    evidence["timestamps"]["started_monotonic"] = first.record["created"] - 10
    path.write_text(json.dumps(evidence))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    Path(str(path) + ".sha256").write_text(f"{digest}  {path.name}\n")
    first.save({"terminal": {"name": path.name, "sha256": digest}})
    first.close()
    assert not recover(session()).done_ok


def test_record_owner_mismatch_is_rejected(session, monkeypatch):
    from types import SimpleNamespace

    first = session()
    armed(first)
    original = os.fstat
    inode = (first.directory / NAME).stat().st_ino
    first.close()

    def foreign(fd):
        st = original(fd)
        if st.st_ino == inode:
            return SimpleNamespace(
                st_mode=st.st_mode, st_uid=os.getuid() + 1, st_nlink=st.st_nlink
            )
        return st

    monkeypatch.setattr(os, "fstat", foreign)
    assert session().invalid


def test_recovered_console_shows_loss_warning_and_exports_on_explicit_action(
    session, monkeypatch, capsys
):
    from beamo_wipe.ui.console_wizard import _plain_loop

    first = session()
    armed(first)
    first.close()
    w = recover(session())
    calls = []
    w._report_exporter = lambda **kw: calls.append(kw) or _success_receipt(**kw)
    answers = iter(["SAVE", "SHUTDOWN"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert _plain_loop(w) == 0
    output = capsys.readouterr().out
    assert "result could not be confirmed" in output
    assert "No erase was restarted or resumed" in output and "power loss" in output
    assert len(calls) == 1 and w._wipe_request is None
    data = json.loads(Path(calls[0]["evidence_path"]).read_bytes())
    assert data["exit_evidence"]["exit_code"] is None
    assert not data["verification"]["verified"] and data["logfile"] == ""
    assert BOOT not in json.dumps(data) and BUILD not in json.dumps(data)


def test_diagnostic_recovery_report_does_not_claim_engine_never_started(session):
    from beamo_wipe.diagnostic_report import create_report, validate_report

    first = session()
    first.close()
    w = recover(session())
    data = create_report(
        w.startup_error_code,
        w.discovery,
        ui="console",
        session_started=time.monotonic(),
    )
    payload = validate_report(data)
    assert payload["title"] == "Diagnostic report — previous result unavailable"
    assert "identifiers" in payload["notice"] and payload["raw_logs"] == "omitted"


@pytest.mark.parametrize("flag", ["--version", "--help"])
def test_informational_cli_does_not_create_a_session(monkeypatch, flag):
    from beamo_wipe import app, session_recovery

    monkeypatch.setattr(app, "running_on_live_usb", lambda: True)

    def forbidden():
        pytest.fail("Informational invocation touched session ownership")

    monkeypatch.setattr(session_recovery, "SessionStore", forbidden)
    with pytest.raises(SystemExit) as result:
        app.main([flag])
    assert result.value.code == 0
