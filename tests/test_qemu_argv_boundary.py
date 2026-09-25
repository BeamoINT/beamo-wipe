"""The hosted QEMU receipt must reject unsafe recorded nwipe commands."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from beamo_wipe.models import MethodId
from beamo_wipe.support_export import _bundle_files
from test_result_presentations import STATUS, case_evidence


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("extra", ["--force", "/dev/sdc", "--exclude=/dev/sdc"])
def test_qemu_report_rejects_unsafe_argv(tmp_path, extra):
    _, evidence, log = case_evidence(
        ("completed", MethodId.EVERYDAY, 0,
         STATUS + "     {name} | Erased |  120 MB/s | 00:00:02 | QEMU/DISK",
         False, False)
    )
    evidence.update(source_commit="a" * 40, build_id="fixture")
    target = evidence["device"]["path"]
    boot = evidence["boot_device"]
    evidence["logfile"] = "/tmp/beamo-wipe/nwipe.log"
    evidence["nwipe"]["argv_redacted"] = [
        "nwipe",
        "--autonuke",
        "--nogui",
        "--nowait",
        "--quiet",
        "--method=prng",
        "--verify=last",
        "--rounds=1",
        "--logfile=/tmp/beamo-wipe/nwipe.log",
        "--PDFreportpath=noPDF",
        f"--exclude={boot}",
        "--noblank",
        extra,
        target,
    ]
    files = _bundle_files(json.dumps(evidence).encode(), log.encode(), "complete")
    session = tmp_path / "BEAMO-WIPE-REPORTS" / ("report-" + "a" * 24)
    session.mkdir(parents=True)
    for name, content in files.items():
        (session / name).write_bytes(content)
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    verifier = (
        source.split("verify_guest_report() {", 1)[1]
        .split("<<'PY'\n", 1)[1]
        .split("\nPY", 1)[0]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-",
            str(tmp_path),
            "verified",
            "everyday",
            "prng",
            "Everyday",
            "fixture",
            "a" * 40,
        ],
        input=verifier,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "guest argv" in result.stderr
