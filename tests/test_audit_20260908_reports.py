"""Report audit regressions; ordinary temporary files and fake boundaries only."""

import errno
import hashlib

import pytest

from beamo_wipe import support_export


@pytest.mark.parametrize("operation", ["fstat", "read", "lseek"])
@pytest.mark.parametrize("number", [errno.EIO, errno.EACCES])
def test_optional_log_io_failure_is_unavailable_and_retryable(
    tmp_path, monkeypatch, operation, number
):
    """An unreadable optional log must not prevent saving terminal evidence."""
    data = b"authenticated engine log\n"
    path = tmp_path / "nwipe.log"
    path.write_bytes(data)
    options = {
        "expected_sha256": hashlib.sha256(data).hexdigest(),
        "expected_size_bytes": len(data),
    }
    original_close = support_export.os.close
    closed = []

    def close(fd):
        closed.append(fd)
        return original_close(fd)

    def fail(*args, **kwargs):
        raise OSError(number, "simulated log media error")

    with monkeypatch.context() as patch:
        patch.setattr(support_export.os, "close", close)
        patch.setattr(support_export.os, operation, fail)
        if operation == "lseek":
            # A lower fixture limit exercises the real suffix seek without a
            # large file or any block-device access.
            patch.setattr(support_export, "MAX_LOG_BYTES", len(data) - 1)
            options["expected_size_bytes"] = len(data) - 1
        assert support_export.read_export_log(str(path), **options) == (b"", "unavailable")
    assert len(closed) == 1
    assert support_export.read_export_log(
        str(path),
        expected_sha256=hashlib.sha256(data).hexdigest(),
        expected_size_bytes=len(data),
    ) == (data, "complete")


def test_terminal_export_preserves_evidence_when_log_read_fails_then_recovers(
    tmp_path, monkeypatch
):
    import json
    import os
    import subprocess
    from dataclasses import asdict

    from beamo_wipe.evidence import write_evidence_atomic
    from test_usb_report_workflow import _discovery, _payload

    log = tmp_path / "nwipe.log"
    log_data = b"engine failure evidence\n"
    log.write_bytes(log_data)
    evidence = write_evidence_atomic(
        {
            "schema_version": 1,
            "outcome": "failed",
            "device": {"path": "/dev/nvme0n1"},
            "logfile": str(log),
            "log_checksum_sha256": hashlib.sha256(log_data).hexdigest(),
            "log_snapshot_size_bytes": len(log_data),
        },
        log_dir=tmp_path,
        device_path="/dev/nvme0n1",
        target_device="/dev/nvme0n1",
    )
    evidence_data = evidence.read_bytes()
    payload, disks = _payload()
    fake_rdevs = {"/dev/sdb": 201, "/dev/nvme0n1": 202, "/dev/sdc": 301, "/dev/sdc1": 302}
    monkeypatch.setattr(support_export, "_block_rdev", fake_rdevs.__getitem__)
    monkeypatch.setattr(support_export, "_emit_export_marker", lambda *args: None)
    exported = []

    def fake_worker(command, **kwargs):
        # Exercise request decoding and actual bundle writes/readback on an
        # ordinary directory. No mount command or process is started.
        report, _, _, _, exported_log, status, privacy = support_export._decode_worker_request(
            kwargs["input"].encode()
        )
        session, files = support_export.write_report_bundle(
            tmp_path, report.data, exported_log, status, privacy_reduced=privacy
        )
        support_export.verify_report_bundle(tmp_path, session, files)
        exported.append((status, files))
        receipt = support_export.ExportReceipt(
            True, True, "saved_verified_unmounted", report.sha256, session, status
        )
        return subprocess.CompletedProcess(command, 0, json.dumps(asdict(receipt)), "")

    original_read = os.read
    log_stat = log.stat()

    def log_read_error(fd, size):
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) == (log_stat.st_dev, log_stat.st_ino):
            raise OSError(errno.EIO, "simulated optional-log read failure")
        return original_read(fd, size)

    def export():
        return support_export.export_to_new_usb(
            evidence_path=evidence,
            discovery=_discovery(disks),
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=fake_worker,
        )

    with monkeypatch.context() as patch:
        patch.setattr(os, "read", log_read_error)
        receipt = export()
    assert receipt.ok and receipt.log_status == "unavailable"
    status, files = exported[0]
    assert status == "unavailable" and files["result.json"] == evidence_data
    assert not any(name.endswith(".log") for name in files)
    assert json.loads(files["COMPLETE"])["log_status"] == "unavailable"
    assert b"nwipe log: unavailable" in files["README.txt"]

    retry = export()
    assert retry.ok and retry.log_status == "complete"
    assert retry.session_name != receipt.session_name
    assert exported[1][1]["result.json"] == evidence_data
    assert exported[1][1]["nwipe.log"] == log_data
