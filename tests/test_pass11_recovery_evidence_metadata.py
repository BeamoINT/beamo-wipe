"""Journal recovery must keep the evidence file private through validation."""

import os
from pathlib import Path

import pytest

from beamo_wipe import evidence as evidence_module
from beamo_wipe.evidence import (
    _read_regular_nofollow,
    build_evidence,
    write_evidence_atomic,
)
from beamo_wipe.models import MethodId, WipeResult
from beamo_wipe.safety import SafetyError
from beamo_wipe import session_recovery as recovery_module
from beamo_wipe.session_recovery import NAME, SessionStore
from test_session_recovery import BOOT, BUILD, armed, finish


@pytest.mark.parametrize(
    "change",
    [
        "evidence_permissions",
        "evidence_hardlink",
        "sidecar_permissions",
        "sidecar_hardlink",
    ],
)
def test_recovery_rejects_evidence_metadata_change_between_reads(
    tmp_path, monkeypatch, change
):
    directory = tmp_path / "private"
    monkeypatch.setattr("beamo_wipe.safety.DEFAULT_LOG_DIR", directory)
    first = SessionStore(directory, boot=BOOT, build=BUILD).open()
    second = SessionStore(directory, boot=BOOT, build=BUILD)
    try:
        discovery, request = armed(first)
        path = finish(first, discovery, request)
        first.close()
        second.open()
        original_recover = evidence_module.recover_result

        def change_then_recover(evidence_path, **kwargs):
            # The journal's first private read is complete at this point.
            altered = (
                path if change.startswith("evidence") else Path(str(path) + ".sha256")
            )
            if change.endswith("permissions"):
                altered.chmod(0o644)
            else:
                os.link(altered, tmp_path / ("exposed-" + altered.name))
            return original_recover(evidence_path, **kwargs)

        monkeypatch.setattr(evidence_module, "recover_result", change_then_recover)
        with pytest.raises(SafetyError, match="Terminal result cannot be proved"):
            second.terminal()
    finally:
        first.close()
        second.close()


def test_private_evidence_read_rejects_permission_change_during_read(
    tmp_path, monkeypatch
):
    path = tmp_path / "result.json"
    path.write_bytes(b"authenticated evidence bytes")
    path.chmod(0o600)
    original_read = os.read
    changed = False

    def read_then_change(fd, size):
        nonlocal changed
        chunk = original_read(fd, size)
        if chunk and not changed and os.fstat(fd).st_ino == path.stat().st_ino:
            path.chmod(0o644)
            changed = True
        return chunk

    monkeypatch.setattr(evidence_module.os, "read", read_then_change)
    with pytest.raises((SafetyError, PermissionError)):
        _read_regular_nofollow(path, private=True)


@pytest.mark.parametrize("change", ["permissions", "hardlink"])
def test_session_read_rejects_metadata_change_during_read(
    tmp_path, monkeypatch, change
):
    store = SessionStore(tmp_path / "private", boot=BOOT, build=BUILD).open()
    journal = store.directory / NAME
    original_read = os.read
    changed = False

    def read_then_change(fd, size):
        nonlocal changed
        chunk = original_read(fd, size)
        if chunk and not changed and os.fstat(fd).st_ino == journal.stat().st_ino:
            if change == "permissions":
                journal.chmod(0o644)
            else:
                os.link(journal, tmp_path / "exposed-journal")
            changed = True
        return chunk

    monkeypatch.setattr(recovery_module.os, "read", read_then_change)
    try:
        with pytest.raises(SafetyError):
            store.read(NAME)
    finally:
        store.close()


def test_recovered_nothing_erased_claim_requires_private_log(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    monkeypatch.setattr("beamo_wipe.safety.DEFAULT_LOG_DIR", directory)
    first = SessionStore(directory, boot=BOOT, build=BUILD).open()
    second = SessionStore(directory, boot=BOOT, build=BUILD)
    try:
        discovery, request = armed(first, MethodId.EVERYDAY)
        log = f"{request.device} is reported as IN USE\n"
        logfile = Path(request.logfile)
        logfile.write_text(log)
        logfile.chmod(0o600)
        record = build_evidence(
            disk=discovery.selectable[0],
            discovery=discovery,
            method=request.method,
            request=request,
            result=WipeResult(False, 0, "busy", request.logfile, "occupied"),
            started_at_wall="",
            ended_at_wall="",
            started_mono=first.record["created"],
            ended_mono=first.record["created"],
            argv=[],
            log_text=log,
        )
        path = write_evidence_atomic(
            record,
            log_dir=directory,
            device_path=request.device,
            target_device=request.device,
        )
        first.finish(path)
        first.close()
        second.open()
        assert second.terminal()[0] == path
        logfile.chmod(0o644)
        with pytest.raises(SafetyError):
            second.terminal()
    finally:
        first.close()
        second.close()
