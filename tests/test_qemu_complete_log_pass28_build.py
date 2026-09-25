"""A QEMU verified result must retain a complete nwipe log in its report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from beamo_wipe.methods import METHODS
from beamo_wipe.models import MethodId
from beamo_wipe.support_export import _bundle_files
from test_result_presentations import STATUS, case_evidence


ROOT = Path(__file__).resolve().parents[1]


def _status_row(name: str, status: str = "Erased") -> str:
    return f"     {name} | {status} |  120 MB/s | 00:00:02 | QEMU/DISK\n"


def _verifier_source() -> str:
    shell = (ROOT / "scripts/qemu-verify.sh").read_text()
    return shell.split("verify_guest_report() {", 1)[1].split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]


def _engine_log(spec, target: str) -> bytes:
    labels = {"prng": "PRNG Stream", "dodshort": "DoD Short", "zero": "Fill With Zeros"}
    passes = spec.overwrite_passes
    lines = [
        f"method = {labels[spec.nwipe_method]}",
        f"verify = {1 if spec.verify == 'last' else 0} ({'last pass' if spec.verify == 'last' else 'off'})",
        "rounds = 1",
    ]
    for number in range(1, passes + 1):
        lines.append(f"Starting pass {number}/{passes}, round 1/1, on {target}")
        if number == passes and spec.verify == "last":
            lines.append(f"Verifying pass {number} of {passes}, round 1 of 1, on {target}")
            lines.append(f"Verified pass {number} of {passes}, round 1 of 1, on '{target}'.")
        lines.append(f"Finished pass {number}/{passes}, round 1/1, on {target}")
    lines.append(STATUS.rstrip("\n"))
    lines.append(_status_row(target.rsplit('/', 1)[-1]).rstrip("\n"))
    return ("\n".join(lines) + "\n").encode()


def _bundle(tmp_path):
    method_id = "everyday"
    spec = METHODS[MethodId(method_id)]
    _, evidence, _ = case_evidence(
        ("completed", MethodId(method_id), 0,
         STATUS + _status_row("{name}").rstrip("\n"), False, False)
    )
    evidence.update(source_commit="a" * 40, build_id="fixture")
    evidence["device"].update(
        path="/dev/vda", realpath="/dev/vda", name="vda",
        serial="0001", size_bytes=67108864, size_gb_label="0",
    )
    evidence["logfile"] = "/tmp/beamo-wipe/nwipe.log"
    evidence["nwipe"]["argv_redacted"] = [
        "nwipe", "--autonuke", "--nogui", "--nowait", "--quiet",
        f"--method={spec.nwipe_method}", f"--verify={spec.verify}",
        "--rounds=1", "--logfile=/tmp/beamo-wipe/nwipe.log",
        "--PDFreportpath=noPDF", f"--exclude={evidence['boot_device']}",
        "--noblank", evidence["device"]["path"],
    ]
    engine_log = _engine_log(spec, evidence["device"]["path"])
    evidence["log_checksum_sha256"] = hashlib.sha256(engine_log).hexdigest()
    evidence["log_snapshot_size_bytes"] = len(engine_log)
    files = _bundle_files(json.dumps(evidence).encode(), engine_log, "complete")
    session = tmp_path / "BEAMO-WIPE-REPORTS" / ("report-" + "a" * 24)
    session.mkdir(parents=True)
    for name, content in files.items():
        (session / name).write_bytes(content)

    command = [
        sys.executable, "-c", _verifier_source(), str(tmp_path),
        evidence["outcome"], method_id, spec.nwipe_method, spec.title,
        "fixture", "a" * 40,
    ]
    valid = subprocess.run(command, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    return session, command, files, evidence


def _replace_exported_log(session, log: bytes) -> None:
    complete = json.loads((session / "COMPLETE").read_bytes())
    result = json.loads((session / "result.json").read_bytes())
    log_digest = hashlib.sha256(log).hexdigest()
    log_sidecar = f"{log_digest}  nwipe.log\n".encode()
    result["log_checksum_sha256"] = log_digest
    result["log_snapshot_size_bytes"] = len(log)
    result_raw = json.dumps(result).encode()
    result_digest = hashlib.sha256(result_raw).hexdigest()
    result_sidecar = f"{result_digest}  result.json\n".encode()
    updates = {
        "nwipe.log": log,
        "nwipe.log.sha256": log_sidecar,
        "result.json": result_raw,
        "result.json.sha256": result_sidecar,
    }
    for name, content in updates.items():
        (session / name).write_bytes(content)
        complete["files"][name] = hashlib.sha256(content).hexdigest()
    (session / "COMPLETE").write_text(json.dumps(complete))


@pytest.mark.parametrize("log_status", ["unavailable", "tail", "complete"])
def test_qemu_gate_rejects_verified_result_without_complete_exported_log(tmp_path, log_status):
    session, command, files, _ = _bundle(tmp_path)

    complete = json.loads(files["COMPLETE"])
    (session / "nwipe.log").unlink()
    del complete["files"]["nwipe.log"]
    if log_status == "tail":
        tail = b"partial engine log\n"
        (session / "nwipe-tail.log").write_bytes(tail)
        complete["files"]["nwipe-tail.log"] = hashlib.sha256(tail).hexdigest()
    complete["log_status"] = log_status
    (session / "COMPLETE").write_text(json.dumps(complete))

    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "complete nwipe log" in checked.stderr


@pytest.mark.parametrize("case", ["other_disk", "later_failure"])
def test_qemu_gate_rejects_complete_log_without_unambiguous_target_success(tmp_path, case):
    session, command, files, evidence = _bundle(tmp_path)
    target_name = evidence["device"]["path"].rsplit("/", 1)[-1]
    wrong_log = (
        (STATUS + _status_row("sda")).encode()
        if case == "other_disk"
        else (STATUS + _status_row(target_name) + _status_row(target_name, "-FAILED-")).encode()
    )
    _replace_exported_log(session, wrong_log)

    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "target status row" in checked.stderr


def test_qemu_gate_accepts_progress_status_before_final_target_success(tmp_path):
    session, command, files, evidence = _bundle(tmp_path)
    target_name = evidence["device"]["path"].rsplit("/", 1)[-1]
    log = files["nwipe.log"].replace(
        _status_row(target_name).encode(),
        (_status_row(target_name, "Wiping") + _status_row(target_name)).encode(),
    )
    _replace_exported_log(session, log)

    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("change", ["wrong_method", "missing_verification", "out_of_order"])
def test_qemu_gate_rejects_unproved_engine_method_in_guest_log(tmp_path, change):
    session, command, files, _ = _bundle(tmp_path)
    log = files["nwipe.log"].decode()
    if change == "wrong_method":
        log = log.replace("method = PRNG Stream", "method = Fill With Zeros")
    elif change == "missing_verification":
        log = "\n".join(line for line in log.splitlines() if "Verif" not in line) + "\n"
    else:
        lines = log.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("Starting pass"))
        verifying = next(i for i, line in enumerate(lines) if line.startswith("Verifying pass"))
        lines[start], lines[verifying] = lines[verifying], lines[start]
        log = "\n".join(lines) + "\n"
    _replace_exported_log(session, log.encode())

    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "engine method log" in checked.stderr


@pytest.mark.parametrize("contradiction", [
    "method = Fill With Zeros",
    "verify = 0 (off)",
    "rounds = 2",
])
def test_qemu_gate_rejects_conflicting_later_engine_setting(tmp_path, contradiction):
    session, command, files, _ = _bundle(tmp_path)
    log = files["nwipe.log"].replace(
        b"rounds = 1\n", f"rounds = 1\n{contradiction}\n".encode()
    )
    _replace_exported_log(session, log)

    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "engine method log" in checked.stderr


@pytest.mark.parametrize("field", ["log_checksum_sha256", "log_snapshot_size_bytes"])
def test_qemu_gate_binds_report_snapshot_metadata_to_exported_log(tmp_path, field):
    session, command, files, _ = _bundle(tmp_path)
    result = json.loads(files["result.json"])
    if field == "log_checksum_sha256":
        result[field] = "0" * 64
    else:
        result[field] += 1
    raw = json.dumps(result).encode()
    digest = hashlib.sha256(raw).hexdigest()
    sidecar = f"{digest}  result.json\n".encode()
    (session / "result.json").write_bytes(raw)
    (session / "result.json.sha256").write_bytes(sidecar)
    complete = json.loads(files["COMPLETE"])
    complete["files"]["result.json"] = digest
    complete["files"]["result.json.sha256"] = hashlib.sha256(sidecar).hexdigest()
    (session / "COMPLETE").write_text(json.dumps(complete))

    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "guest nwipe log snapshot" in checked.stderr


@pytest.mark.parametrize("change", ["wrong_target", "wrong_serial", "wrong_size"])
def test_qemu_gate_binds_reported_device_to_the_disposable_guest_target(tmp_path, change):
    session, command, files, _ = _bundle(tmp_path)
    result = json.loads(files["result.json"])
    complete = json.loads(files["COMPLETE"])
    if change == "wrong_target":
        result["device"].update(path="/dev/sdz", realpath="/dev/sdz", name="sdz")
        result["nwipe"]["argv_redacted"][-1] = "/dev/sdz"
        log = files["nwipe.log"].replace(b"/dev/vda", b"/dev/sdz").replace(
            b"vda | Erased |", b"sdz | Erased |"
        )
        log_digest = hashlib.sha256(log).hexdigest()
        result["log_checksum_sha256"] = log_digest
        result["log_snapshot_size_bytes"] = len(log)
        log_sidecar = f"{log_digest}  nwipe.log\n".encode()
        (session / "nwipe.log").write_bytes(log)
        (session / "nwipe.log.sha256").write_bytes(log_sidecar)
        complete["files"]["nwipe.log"] = log_digest
        complete["files"]["nwipe.log.sha256"] = hashlib.sha256(log_sidecar).hexdigest()
    elif change == "wrong_serial":
        result["device"]["serial"] = "9999"
    else:
        result["device"]["size_bytes"] += 512
    raw = json.dumps(result).encode()
    digest = hashlib.sha256(raw).hexdigest()
    sidecar = f"{digest}  result.json\n".encode()
    (session / "result.json").write_bytes(raw)
    (session / "result.json.sha256").write_bytes(sidecar)
    complete["files"]["result.json"] = digest
    complete["files"]["result.json.sha256"] = hashlib.sha256(sidecar).hexdigest()
    (session / "COMPLETE").write_text(json.dumps(complete))

    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode != 0, checked.stdout + checked.stderr
    assert "guest target identity" in checked.stderr
