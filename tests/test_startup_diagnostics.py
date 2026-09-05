# SPDX-License-Identifier: GPL-3.0-or-later
"""Startup support reports; all device/process boundaries below are fake."""

import copy
import hashlib
import json
import os
import subprocess
from types import SimpleNamespace
import threading

import pytest

from beamo_wipe import app
from beamo_wipe import diagnostic_report as d
from beamo_wipe import support_export as export
from beamo_wipe.models import DiscoveryResult, Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.safety import SafetyError
from beamo_wipe.wizard import Wizard
from test_usb_report_workflow import _payload, _discovery


@pytest.fixture
def blocked():
    return Wizard(
        DiscoveryResult(
            error="private /dev/secret SERIAL password=secret",
            diagnostic="token=secret",
            error_code="discovery_failed",
        ),
        DryRunRunner(),
    )


def blob():
    return d.create_report(
        "discovery_failed",
        DiscoveryResult(error="secret"),
        ui="console",
        session_started=0,
    )


@pytest.mark.parametrize(
    "exc,code",
    [
        (SafetyError("secret"), "startup_refused"),
        (FileNotFoundError("secret"), "dependency_missing"),
        (PermissionError("secret"), "permission_denied"),
        (OSError("secret"), "io_failed"),
        (ValueError("secret"), "discovery_invalid"),
        (TypeError("secret"), "discovery_invalid"),
        (AttributeError("secret"), "discovery_invalid"),
        (UnicodeDecodeError("utf8", b"x", 0, 1, "secret"), "discovery_invalid"),
        (subprocess.TimeoutExpired("secret", 1), "discovery_timeout"),
        (
            subprocess.CalledProcessError(1, "secret", stderr="token=secret"),
            "discovery_command_failed",
        ),
        (RuntimeError("secret"), "unexpected_startup_failure"),
    ],
)
def test_startup_failure_keeps_console_and_sanitized_diagnostic_reachable(
    monkeypatch, capsys, exc, code
):
    def fail(_args):
        raise exc

    monkeypatch.setattr(app, "_build_wizard", fail)

    def console(w):
        assert w.screen == Screen.PICK_BLOCKED
        assert w.startup_error_code == code
        assert w.can_open_diagnostic and not w.can_save_report and not w.can_refresh
        w.open_diagnostic()
        assert w.screen == Screen.DIAGNOSTIC
        assert w.evidence is None and w.wipe_result is None and w._wipe_request is None
        payload = d.create_report(code, w.discovery, ui="console", session_started=0)
        assert b"secret" not in payload
        d.validate_report(payload)
        return 0

    monkeypatch.setattr("beamo_wipe.ui.console_wizard.run_console", console)
    assert app.main(["--console"]) == 0
    assert "secret" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("secret"),
        PermissionError("secret"),
        ValueError("secret"),
        subprocess.TimeoutExpired("secret", 1),
        RuntimeError("secret"),
    ],
)
def test_discovery_failures_have_allowlisted_codes(monkeypatch, exc):
    import beamo_wipe.discover as discovery

    monkeypatch.setattr(discovery, "run_lsblk", lambda: (_ for _ in ()).throw(exc))
    result = discovery.discover()
    assert not result.boot_identified and not result.selectable
    assert result.error_code == d.exception_code(exc)
    assert b"secret" not in d.create_report(
        result.error_code, result, ui="console", session_started=0
    )


def test_graphical_startup_failure_retains_diagnostic_path(monkeypatch):
    monkeypatch.setattr(
        app, "_build_wizard", lambda _: (_ for _ in ()).throw(PermissionError("secret"))
    )

    def graphical(w, **kwargs):
        assert w.can_open_diagnostic and w._startup_blocked
        return 0

    monkeypatch.setattr("beamo_wipe.ui.tk_wizard.run_tk", graphical)
    assert app.main([]) == 0


def test_no_privacy_fields_even_when_environment_and_inventory_are_poisoned(
    monkeypatch,
):
    monkeypatch.setenv("BUILD_ID", "secret")
    monkeypatch.setenv("TOKEN", "secret")
    monkeypatch.setattr(d.platform, "machine", lambda: "private-machine-secret")
    monkeypatch.setattr(d.platform, "system", lambda: "host-secret")
    discovery = _discovery(_payload()[1])
    discovery.diagnostic = "SERIAL /media/private secret"
    discovery.error = "secret"
    data = d.create_report(
        "discovery_failed", discovery, ui="console", session_started=0
    )
    payload = d.validate_report(data)
    for forbidden in (
        b"secret",
        b"/dev/",
        b"BOOT-1",
        b"TARGET-1",
        b"wwn",
        b"hostname",
        b"mountpoints",
        b"outcome",
        b"exit_code",
    ):
        assert forbidden not in data
    assert payload["time"]["wall_confidence"] == "unverified"
    assert payload["environment"]["architecture"] == "other"
    assert len(data) < d.MAX_BYTES


@pytest.mark.parametrize(
    "path",
    [
        ("outcome",),
        ("application", "hostname"),
        ("discovery", "serial"),
        ("environment", "token"),
        ("time", "timezone"),
        ("events",),
    ],
)
def test_worker_schema_rejects_added_private_fields(path):
    p = json.loads(blob())
    if path == ("events",):
        p["events"] = [{"code": "discovery_failed", "detail": "secret"}]
    else:
        target = p
        for component in path[:-1]:
            target = target[component]
        target[path[-1]] = "secret"
    with pytest.raises(SafetyError):
        d.validate_report(json.dumps(p).encode())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(error_code="secret"),
        lambda p: p.update(events=[{"code": "discovery_failed"}] * (d.MAX_EVENTS + 1)),
        lambda p: p["time"].update(session_elapsed_seconds=float("nan")),
        lambda p: p["time"].update(wall_confidence="verified"),
        lambda p: p["time"].update(recorded_at_utc="secret"),
        lambda p: p["application"].update(version="secret"),
    ],
)
def test_invalid_or_unbounded_metadata_is_rejected(mutation):
    p = json.loads(blob())
    mutation(p)
    with pytest.raises(SafetyError):
        d.validate_report(json.dumps(p).encode())


def test_build_identity_is_exact_and_runtime_overrides_are_ignored(
    tmp_path, monkeypatch
):
    metadata = {
        "source_commit": "a" * 40,
        "source_sha256": d.runtime_source_sha256(),
        "build_id": "12345678-1234-1234-1234-123456789abc",
        "source_dirty": False,
    }
    path = tmp_path / "build-identity.json"
    path.write_text(json.dumps(metadata))
    monkeypatch.setattr(d, "BUILD_PATH", path)
    monkeypatch.setenv("BUILD_ID", "private")
    assert d.application_identity()["build"] == metadata
    assert d.validate_report(blob())["application"]["build_status"] == "recorded"
    metadata["hostname"] = "private"
    path.write_text(json.dumps(metadata))
    assert d.application_identity()["build_status"] == "unavailable"
    path.unlink()
    path.symlink_to(tmp_path / "absent")
    assert d.application_identity()["build_status"] == "unavailable"


def test_report_is_separate_checksums_authenticate_exact_bytes(tmp_path):
    data = blob()
    session, files = export.write_report_bundle(tmp_path, data, b"", "unavailable")
    export.verify_report_bundle(tmp_path, session, files)
    assert set(files) == {
        "diagnostic.json",
        "diagnostic.json.sha256",
        "README.txt",
        "COMPLETE",
    }
    assert b"not erase evidence" in files["README.txt"]
    manifest = json.loads(files["COMPLETE"])
    for name, digest in manifest["files"].items():
        assert hashlib.sha256(files[name]).hexdigest() == digest
    assert (
        files["diagnostic.json.sha256"]
        == (hashlib.sha256(data).hexdigest() + "  diagnostic.json\n").encode()
    )
    directory = tmp_path / export.REPORTS_DIR / session
    for name in files:
        original = (directory / name).read_bytes()
        (directory / name).write_bytes(b"changed")
        with pytest.raises(SafetyError):
            export.verify_report_bundle(tmp_path, session, files)
        (directory / name).write_bytes(original)


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/tmp/escape",
        "..",
        "report-" + "a" * 24 + "/../escape",
        "report-\n",
    ],
)
def test_diagnostic_session_traversal_is_rejected(tmp_path, name):
    with pytest.raises(SafetyError):
        export.write_report_bundle(
            tmp_path, blob(), b"", "unavailable", session_name=name
        )
    with pytest.raises(SafetyError):
        export.verify_report_bundle(tmp_path, name, {})


@pytest.mark.parametrize("failure_index", range(1, 5))
def test_partial_diagnostic_writes_never_publish_complete(
    tmp_path, monkeypatch, failure_index
):
    original = export._full_write
    calls = 0

    def fail(fd, data):
        nonlocal calls
        calls += 1
        if calls == failure_index:
            os.write(fd, data[:3])
            raise OSError("fake full disk")
        original(fd, data)

    monkeypatch.setattr(export, "_full_write", fail)
    with pytest.raises(OSError):
        export.write_report_bundle(tmp_path, blob(), b"", "unavailable")
    assert not list(tmp_path.rglob("COMPLETE"))


def test_short_writes_complete_or_fail_explicitly(tmp_path, monkeypatch):
    original = os.write
    monkeypatch.setattr(export.os, "write", lambda fd, data: original(fd, data[:7]))
    session, files = export.write_report_bundle(tmp_path, blob(), b"", "unavailable")
    export.verify_report_bundle(tmp_path, session, files)
    monkeypatch.setattr(export.os, "write", lambda fd, data: 0)
    with pytest.raises(OSError):
        export.write_report_bundle(tmp_path, blob(), b"", "unavailable")


def test_diagnostic_export_refuses_symlink_directory(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / export.REPORTS_DIR).symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(OSError):
        export.write_report_bundle(tmp_path, blob(), b"", "unavailable")
    assert not list(elsewhere.iterdir())


def test_diagnostics_never_accept_raw_logs(tmp_path):
    with pytest.raises(SafetyError):
        export.write_report_bundle(tmp_path, blob(), b"secret", "complete")
    assert not list(tmp_path.rglob("COMPLETE"))


def fake_baseline(monkeypatch):
    payload, disks = _payload()
    original = copy.deepcopy(payload)
    original["blockdevices"] = original["blockdevices"][:2]
    rdevs = {"/dev/sdb": 11, "/dev/nvme0n1": 12, "/dev/sdc": 13, "/dev/sdc1": 14}
    monkeypatch.setattr(export, "_block_rdev", lambda path: rdevs[path])
    monkeypatch.setattr("beamo_wipe.discover.discover", lambda **kw: _discovery(disks))
    baseline = export.capture_diagnostic_baseline(scan=lambda: original)
    return payload, baseline


def test_baseline_protects_every_existing_disk_and_requires_boot(monkeypatch):
    payload, baseline = fake_baseline(monkeypatch)
    assert all(item.required and item.rdev for item in baseline)
    monkeypatch.setattr("beamo_wipe.discover.discover", lambda **kw: DiscoveryResult())
    with pytest.raises(SafetyError, match="boot USB"):
        export.capture_diagnostic_baseline(scan=lambda: payload)


@pytest.mark.parametrize("bad", [{}, {"blockdevices": []}, {"blockdevices": "secret"}])
def test_missing_invalid_baseline_fails_closed(monkeypatch, bad):
    fake_baseline(monkeypatch)
    with pytest.raises(SafetyError):
        export.capture_diagnostic_baseline(scan=lambda: bad)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda p: p["blockdevices"].pop(), "exactly one"),
        (
            lambda p: p["blockdevices"].append(copy.deepcopy(p["blockdevices"][-1])),
            "duplicate",
        ),
        (lambda p: p["blockdevices"][-1]["children"][0].update(fstype="ext4"), "FAT32"),
        (lambda p: p["blockdevices"][-1]["children"][0].update(fsver="FAT16"), "FAT32"),
        (
            lambda p: p["blockdevices"][-1]["children"][0].update(
                path="/dev/sdc1/../../etc"
            ),
            "path",
        ),
        (
            lambda p: p["blockdevices"][-1]["children"][0].update(
                mountpoint="/private"
            ),
            "mounted",
        ),
        (lambda p: p["blockdevices"][-1].update(rm=0), "removable"),
        (lambda p: p["blockdevices"][-1].update(ro=1), "writable"),
        (lambda p: p["blockdevices"].pop(0), "connected"),
    ],
)
def test_diagnostic_destination_policy_cannot_reach_worker_on_invalid_media(
    monkeypatch, mutation, match
):
    payload, baseline = fake_baseline(monkeypatch)
    mutation(payload)

    def worker(*a, **kw):
        pytest.fail("invalid destination reached worker")

    with pytest.raises(SafetyError, match=match):
        export.export_diagnostic_to_new_usb(
            data=blob(), baseline=baseline, scan=lambda: payload, run=worker
        )


def test_diagnostic_controller_worker_checksum_and_privacy_boundary(monkeypatch):
    payload, baseline = fake_baseline(monkeypatch)
    data = blob()

    def worker(command, **kw):
        request = json.loads(kw["input"])
        raw = kw["input"].encode()
        report, volume, protected, rdevs, log, status = export._decode_worker_request(
            raw
        )
        assert report.data == data and log == b"" and status == "unavailable"
        assert command[:3] == [export.UNSHARE_BIN, "--mount", "--propagation"]
        request["evidence_sha256"] = "0" * 64
        with pytest.raises(SafetyError, match="checksum"):
            export._decode_worker_request(json.dumps(request).encode())
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "safe_to_remove": True,
                    "code": "saved_verified_unmounted",
                    "evidence_sha256": hashlib.sha256(data).hexdigest(),
                    "session_name": "report-" + "c" * 24,
                    "log_status": "unavailable",
                }
            ),
        )

    receipt = export.export_diagnostic_to_new_usb(
        data=data, baseline=baseline, scan=lambda: payload, run=worker
    )
    assert receipt.ok and receipt.safe_to_remove


def test_no_wipe_state_is_created_and_export_blocks_navigation(monkeypatch, blocked):
    blocked.dry_run = False
    blocked.screen = Screen.PICK_BLOCKED
    blocked.open_diagnostic()
    entered = threading.Event()
    release = threading.Event()

    def prepare():
        entered.set()
        assert release.wait(3)
        return ("fake",)

    monkeypatch.setattr(export, "capture_diagnostic_baseline", prepare)
    assert blocked.diagnostic_action(background=True)
    assert entered.wait(1)
    assert not blocked.diagnostic_action()
    blocked.shutdown()
    blocked.back()
    blocked.confirm_erase()
    assert not blocked.wants_shutdown and blocked.screen == Screen.DIAGNOSTIC
    assert not blocked.can_refresh and not blocked.can_save_report
    release.set()
    for thread in threading.enumerate():
        if thread.name == "beamo-diagnostic-export":
            thread.join(2)
    assert not blocked._diagnostic_busy and blocked._diagnostic_baseline
    assert blocked.evidence is None and blocked._wipe_request is None


def test_plain_console_diagnostic_flow_requires_explicit_prepare(
    monkeypatch, capsys, blocked
):
    from beamo_wipe.ui.console_wizard import _plain_loop

    blocked.screen = Screen.PICK_BLOCKED
    answers = iter(["DIAGNOSTIC", "PREPARE", "SHUTDOWN"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert _plain_loop(blocked) == 0
    text = capsys.readouterr().out
    assert "Support diagnostics only" in text
    assert "dry-run" in text
    assert blocked.evidence is None


def test_completed_evidence_eligibility_remains_independent(blocked):
    blocked.screen = Screen.DONE
    assert not blocked.can_open_diagnostic and not blocked.can_save_report
    blocked.screen = Screen.WORKING
    assert not blocked.can_open_diagnostic


@pytest.mark.parametrize(
    "stage,exc,code",
    [
        ("ready", SafetyError("private"), "preflight_rejected"),
        ("argv", SafetyError("private"), "preflight_rejected"),
        ("start", SafetyError("private"), "preflight_rejected"),
        ("start", FileNotFoundError("private"), "engine_start_failed"),
        ("start", PermissionError("private"), "engine_start_failed"),
        ("start", OSError("private"), "engine_start_failed"),
        ("start", RuntimeError("private"), "unexpected_startup_failure"),
    ],
)
def test_preflight_and_engine_failures_offer_diagnostics_without_evidence(
    monkeypatch, stage, exc, code
):
    from beamo_wipe.demo import make_demo_wizard
    import beamo_wipe.wizard as module

    w = make_demo_wizard()
    w.preview = False
    w.screen = Screen.LAST_CHANCE
    w._erase_until = w.now - 1
    w.selected = w.selectable[0]
    w.owner_ok = True
    w.confirm_input = w.confirm.token

    def fail(*a, **kw):
        raise exc

    if stage == "ready":
        monkeypatch.setattr(module, "assert_ready_to_wipe", fail)
    else:
        monkeypatch.setattr(module, "assert_ready_to_wipe", lambda **kw: object())
        monkeypatch.setattr(
            module, "build_nwipe_argv", fail if stage == "argv" else lambda req: []
        )
        monkeypatch.setattr(w.runner, "start", fail)
    w.confirm_erase()
    assert w.startup_error_code == code and w.can_open_diagnostic
    assert w.evidence is None and w._wipe_request is None and w.wipe_result is None
    assert "private" not in w.error


def test_worker_rejects_diagnostic_log_smuggling(monkeypatch):
    import base64

    payload, baseline = fake_baseline(monkeypatch)
    data = blob()
    volume = export.select_export_volume(payload, baseline)
    request = export._request_dict(
        d.verified_report(data), volume, baseline, (11, 12), b"secret", "complete"
    )
    with pytest.raises(SafetyError, match="raw logs"):
        export._decode_worker_request(json.dumps(request).encode())
    modified = json.loads(data)
    modified["secret"] = "value"
    altered = json.dumps(modified).encode()
    request.update(
        evidence=base64.b64encode(altered).decode(),
        evidence_sha256=hashlib.sha256(altered).hexdigest(),
        log="",
        log_status="unavailable",
    )
    with pytest.raises(SafetyError, match="unsanitized"):
        export._decode_worker_request(json.dumps(request).encode())


def test_readback_rejects_symlink_ancestor_and_bounded_growth(tmp_path):
    session, files = export.write_report_bundle(tmp_path, blob(), b"", "unavailable")
    real = tmp_path / export.REPORTS_DIR
    moved = tmp_path / "moved"
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    with pytest.raises(OSError):
        export.verify_report_bundle(tmp_path, session, files)
    fd = os.open(str(moved / session), os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(SafetyError):
            export._read_at(fd, "../escape")
        with pytest.raises(SafetyError):
            export._read_at(fd, "diagnostic.json", limit=1)
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "bad_receipt",
    [
        export.ExportReceipt(True, False, "saved_verified_unmounted"),
        export.ExportReceipt(
            True, True, "saved_verified_unmounted", "a" * 64, "report-" + "b" * 24
        ),
        export.ExportReceipt(False, False, "export_failed"),
    ],
)
def test_diagnostic_ui_never_announces_success_from_unverified_receipt(
    monkeypatch, blocked, bad_receipt
):
    blocked.dry_run = False
    blocked.screen = Screen.PICK_BLOCKED
    blocked.open_diagnostic()
    blocked._diagnostic_baseline = ("fake",)
    monkeypatch.setattr(
        export, "export_diagnostic_to_new_usb", lambda **kw: bad_receipt
    )
    blocked.diagnostic_action()
    assert "safe to remove" not in blocked.diagnostic_message
    assert not blocked.can_save_report and blocked.evidence is None


def test_diagnostic_worker_start_failure_is_visible_and_retryable(monkeypatch, blocked):
    blocked.screen = Screen.PICK_BLOCKED
    blocked.open_diagnostic()
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert not blocked.diagnostic_action(background=True)
    assert (
        not blocked._diagnostic_busy and "could not start" in blocked.diagnostic_message
    )
    assert "private" not in blocked.diagnostic_message


def test_curses_diagnostic_action_requires_explicit_typed_confirmation(
    monkeypatch, blocked
):
    from beamo_wipe.ui import console_wizard as ui

    blocked.screen = Screen.PICK_BLOCKED
    blocked.open_diagnostic()
    calls = []
    monkeypatch.setattr(blocked, "diagnostic_action", lambda **kw: calls.append(kw))
    monkeypatch.setattr(ui.curses, "echo", lambda: None)
    monkeypatch.setattr(ui.curses, "noecho", lambda: None)

    class Tty:
        answer = b"R"

        def getmaxyx(self):
            return (24, 80)

        def addstr(self, *args):
            pass

        def refresh(self):
            pass

        def timeout(self, n):
            pass

        def getstr(self, *args):
            return self.answer

    tty = Tty()
    ui._confirm_diagnostic_action(tty, blocked)
    assert not calls
    tty.answer = b"PREPARE"
    ui._confirm_diagnostic_action(tty, blocked)
    assert calls == [{"background": True}]


def test_runtime_identity_matches_release_source_digest():
    from beamo_wipe.release_manifest import live_build_inputs

    assert d.runtime_source_sha256() == live_build_inputs()["src/beamo_wipe/"]


def test_supervisor_console_keeps_graphical_failure_visible(monkeypatch):
    from beamo_wipe.demo import make_demo_wizard

    w = make_demo_wizard()
    w.preview = False
    w.screen = Screen.WHAT
    monkeypatch.setattr(app, "_build_wizard", lambda _: w)
    monkeypatch.setenv("BEAMO_WIPE_GRAPHICAL_UNAVAILABLE", "1")
    monkeypatch.setattr("beamo_wipe.ui.console_wizard.run_console", lambda w: 0)
    assert app.main(["--console"]) == 0
    assert w.startup_error_code == "graphical_unavailable" and w.can_open_diagnostic


def test_diagnostic_render_snapshot_is_immutable(blocked):
    blocked.screen = Screen.PICK_BLOCKED
    blocked.open_diagnostic()
    old = blocked.diagnostic_view
    blocked.diagnostic_action()
    new = blocked.diagnostic_view
    assert new.revision > old.revision and new.message != old.message
    assert old.message == "" and not old.busy


def test_curses_diagnostic_shutdown_obeys_active_export_guard(blocked):
    from beamo_wipe.ui.console_wizard import _handle

    blocked.screen = Screen.PICK_BLOCKED
    blocked.open_diagnostic()
    blocked._diagnostic_busy = True
    _handle(blocked, ord("S"))
    assert not blocked.wants_shutdown
    blocked._diagnostic_busy = False
    _handle(blocked, ord("S"))
    assert blocked.wants_shutdown
