# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute build-evidence boundaries with disposable files and processes."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from beamo_wipe import __version__
from beamo_wipe import release_manifest as rm

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("method_id", ["everyday", "extra", "quick_zero"])
@pytest.mark.parametrize("privacy_reduced", [False, True])
def test_qemu_report_verifier_accepts_production_bundles(tmp_path, method_id, privacy_reduced):
    from beamo_wipe.methods import METHODS
    from beamo_wipe.models import MethodId
    from beamo_wipe.support_export import _bundle_files
    from test_result_presentations import case_evidence

    method = MethodId(method_id)
    spec = METHODS[method]
    _, evidence, log = case_evidence(("completed", method, 0, "{name} | Erased |", False, False))
    evidence.update(source_commit="a" * 40, build_id="fixture")
    evidence["nwipe"]["argv_redacted"] = [
        f"--method={spec.nwipe_method}", f"--verify={spec.verify}",
        "--rounds=1", "--noblank", "--quiet", "--autonuke",
    ]
    files = _bundle_files(json.dumps(evidence).encode(), log.encode(), "complete", privacy_reduced=privacy_reduced)
    session = tmp_path / "BEAMO-WIPE-REPORTS" / ("report-" + "a" * 24)
    session.mkdir(parents=True)
    for name, content in files.items():
        (session / name).write_bytes(content)
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = source.split("verify_guest_report() {", 1)[1].split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]

    def verify():
        return subprocess.run(
            [sys.executable, "-", str(tmp_path), evidence["outcome"], method_id,
             spec.nwipe_method, spec.title, "fixture", "a" * 40],
            input=block, text=True, capture_output=True,
        )

    result = verify()
    assert result.returncode == 0, result.stderr
    complete = json.loads(files["COMPLETE"])
    complete["result_summary"] = "missing.txt"
    (session / "COMPLETE").write_text(json.dumps(complete))
    result = verify()
    assert result.returncode != 0 and "summary declaration" in result.stderr


@pytest.fixture
def build_provenance(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion="{__version__}"\n')
    for name in ("NOTICE", "THIRD_PARTY.md"):
        (tmp_path / name).write_text(name)
    dist = tmp_path / "dist"
    dist.mkdir()
    iso = dist / f"beamo-wipe-{__version__}-amd64.iso"
    iso.write_bytes(b"disposable ISO fixture")
    monkeypatch.setattr(rm, "ROOT", tmp_path)
    monkeypatch.setattr(rm, "git_commit", lambda: "a" * 40)
    monkeypatch.setattr(rm, "git_dirty", lambda: (False, []))
    monkeypatch.setattr(rm, "git_tag_for_commit", lambda c: None)
    monkeypatch.setattr(rm, "git_remote_url", lambda: rm.EXPECTED_REMOTE)
    monkeypatch.setattr(rm, "live_build_inputs", lambda: {"src/beamo_wipe/": "b" * 64})
    monkeypatch.setattr(rm, "_run", lambda *a, **kw: "main")
    manifest = rm.generate_manifest(build_only=True)
    dest = dist / f"beamo-wipe-{__version__}-amd64.manifest.json"
    rm.write_manifest(manifest, dest)
    return tmp_path, dest, iso


def test_build_provenance_can_precede_qemu_but_cannot_pass_release(build_provenance):
    _, dest, iso = build_provenance
    rm.verify_build_manifest(dest)
    with pytest.raises(RuntimeError, match="measured gate evidence"):
        rm.verify_manifest(dest)
    iso.write_bytes(b"tampered fixture")
    with pytest.raises(RuntimeError, match="ISO checksum mismatch"):
        rm.verify_build_manifest(dest)


def test_finalize_requires_all_executed_gates_and_image_inventory(build_provenance):
    from beamo_wipe.ci_evidence import finalize, collect_inventory
    from beamo_wipe.verification_evidence import REQUIRED_GATES, build_gate_receipt

    root, dest, _ = build_provenance
    evidence = root / "dist/evidence"
    evidence.mkdir()
    image = root / "mounted-fixture"
    (image / "var/lib/dpkg").mkdir(parents=True)
    (image / "etc/apt").mkdir(parents=True)
    (image / "var/lib/dpkg/status").write_text("Package: base-files\nStatus: install ok installed\nVersion: 1\nArchitecture: amd64\n")
    (image / "etc/apt/sources.list").write_text("deb https://deb.debian.org/debian bookworm main\n")
    collect_inventory(image, evidence / "packages.json", "a" * 40)
    for gate in REQUIRED_GATES:
        log = f"fixture execution of {gate}\n".encode()
        (evidence / f"{gate}.log").write_bytes(log)
        receipt = build_gate_receipt(
            gate=gate, status="pass", command=f"fixture {gate}", source_commit="a" * 40,
            build_id=rm.build_env()["release_build_id"], environment={"runner": "fixture"},
            measured=dict(passed=1, failed=0, errors=0, skipped=0, xfailed=0, deselected=0, total=1),
            skips=[], log_sha256=hashlib.sha256(log).hexdigest(),
        )
        if gate == "qemu":
            with pytest.raises(RuntimeError, match="missing required gate"):
                finalize(root)
        (evidence / f"{gate}.receipt.json").write_text(json.dumps(receipt))
    finalize(root)
    rm.verify_manifest(dest)
    assert json.loads(dest.read_text())["test_evidence"]["measured"] is True
    for line in (root / "dist/SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert digest == hashlib.sha256((root / "dist" / name).read_bytes()).hexdigest()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_gate_runner_records_real_process_status_and_log(tmp_path, exit_code):
    from beamo_wipe.ci_evidence import run_gate
    receipt = run_gate(
        "preview", [sys.executable, "-c", f"print('executed'); raise SystemExit({exit_code})"],
        root=ROOT, evidence_dir=tmp_path, build_id="local",
    )
    assert receipt["status"] == ("pass" if exit_code == 0 else "fail")
    assert receipt["measured"]["passed"] == int(exit_code == 0)
    assert receipt["measured"]["failed"] == int(exit_code != 0)
    log = tmp_path / "preview.log"
    assert b"executed" in log.read_bytes()
    assert receipt["log_sha256"] == hashlib.sha256(log.read_bytes()).hexdigest()
    assert json.loads((tmp_path / "preview.receipt.json").read_text()) == receipt


def test_qemu_host_log_parser_accepts_actual_whitespace(tmp_path):
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = source.split('python3 - "$logf" "$nwipe_method" "$verify" <<\'PY\'\n', 1)[1].split("\nPY", 1)[0]
    log = tmp_path / "nwipe.log"
    log.write_text("method = PRNG Stream\nverify = 1 (last pass)\nrounds = 1\nStarting pass 1/1, round 1/1, on /dev/loop0\nVerifying pass 1 of 1, round 1 of 1, on /dev/loop0\nVerified pass 1 of 1, round 1 of 1, on /dev/loop0\nFinished pass 1/1, round 1/1, on /dev/loop0\n| Erased |\n")
    result = subprocess.run([sys.executable, "-", str(log), "prng", "last"], input=block, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_qemu_rejects_host_disk_even_when_another_argument_mentions_loop(tmp_path):
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = "record_qemu_cmdline() {" + source.split("record_qemu_cmdline() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    block += 'record_qemu_cmdline "$1" qemu-system-x86_64 -nic none -drive file=/dev/sda -name loop-fixture\n'
    result = subprocess.run(["bash", "-c", block, "test", str(tmp_path / "argv")], capture_output=True)
    assert result.returncode != 0


def test_gate_runner_collects_pytest_counts_and_skip_reason(tmp_path):
    from beamo_wipe.ci_evidence import run_gate, load_receipts

    suite = tmp_path / "test_fixture.py"
    suite.write_text("import pytest\ndef test_pass(): pass\ndef test_skip(): pytest.skip('fixture reason')\n")
    evidence = tmp_path / "evidence"
    receipt = run_gate("tests", [sys.executable, "-m", "pytest", str(suite),
                       "--junitxml=" + str(evidence / "tests.xml")],
                       root=ROOT, evidence_dir=evidence, build_id="local")
    assert receipt["measured"] == dict(passed=1, failed=0, errors=0, skipped=1,
                                       xfailed=0, deselected=0, total=2)
    assert receipt["skips"][0]["reason"] == "fixture reason"
    assert load_receipts(evidence) == [receipt]
    (evidence / "tests.log").write_text("tampered")
    with pytest.raises(RuntimeError, match="log digest"):
        load_receipts(evidence)


def test_gate_runner_refuses_stale_evidence(tmp_path):
    from beamo_wipe.ci_evidence import run_gate

    (tmp_path / "preview.log").write_text("older execution")
    with pytest.raises(RuntimeError, match="stale evidence"):
        run_gate("preview", [sys.executable, "-c", "raise SystemExit(0)"],
                 root=ROOT, evidence_dir=tmp_path, build_id="local")


def test_guest_readback_does_not_treat_io_failure_as_a_changed_pattern(tmp_path):
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = "assert_guest_overwrite() {" + source.split("assert_guest_overwrite() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    block += '''
qemu-io() { return 1; }
qemu-img() { return 1; }
log() { :; }
RUN_ROOT="$1"
EVIDENCE_DIR="$1"
HOST_METHOD_BYTES=67108864
assert_guest_overwrite everyday prng unused
'''
    result = subprocess.run(["bash", "-c", block, "test", str(tmp_path)], capture_output=True)
    assert result.returncode != 0


@pytest.mark.parametrize("failed_resource", ["target", "report", "boot", "squash", "iso", "none"])
@pytest.mark.parametrize("original_status", [0, 7])
def test_qemu_cleanup_fails_closed_and_retains_attached_backing_files(tmp_path, failed_resource, original_status):
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    block = "cleanup() {" + source.split("cleanup() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    target = tmp_path / "target.raw"
    target.write_bytes(b"attached fixture")
    block += '''
RUN_ROOT="$1"
TARGET_RAW="$1/target.raw"
TARGET="$1/target.qcow2"
NWIPE_BIN="$1/nwipe"
REPORT_RAW="$1/report.raw"
ISO="$1/boot.iso"
REPORT_MOUNTED=0
SQUASH_MOUNTED=1
ISO_MOUNTED=1
SQUASH_MOUNT=squash
ISO_MOUNT=iso
CLEANED_UP=0
BIOS_PID="" UEFI_PID="" REPORT_LOOP=/dev/loop997 BOOT_LOOP=/dev/loop998 LOOP=/dev/loop999
failed_resource="$2"
stop_pid() { :; }
detach_owned_loop() { test "$1" != "$failed_resource"; }
sudo() { test "$2" != "$failed_resource"; }
trap cleanup EXIT
exit "$3"
'''
    result = subprocess.run(["bash", "-c", block, "test", str(tmp_path), failed_resource, str(original_status)], capture_output=True)
    assert (result.returncode == 0) == (failed_resource == "none" and original_status == 0)
    if failed_resource == "none":
        assert result.returncode == original_status
    if failed_resource == "target":
        assert target.read_bytes() == b"attached fixture"
