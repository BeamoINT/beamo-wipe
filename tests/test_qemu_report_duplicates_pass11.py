"""QEMU gate refuses ambiguous guest report JSON using regular-file fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("ambiguous_file", ["COMPLETE", "result.json"])
def test_qemu_report_verifier_rejects_duplicate_fields(tmp_path, ambiguous_file):
    shell = (ROOT / "scripts" / "qemu-verify.sh").read_text()
    verifier = (
        shell.split("verify_guest_report() {", 1)[1]
        .split("<<'PY'\n", 1)[1]
        .split("\nPY\n", 1)[0]
    )
    session = tmp_path / "BEAMO-WIPE-REPORTS" / ("report-" + "a" * 24)
    session.mkdir(parents=True)
    result = (
        b'{"outcome":"failed","outcome":"verified"}'
        if ambiguous_file == "result.json"
        else b"{}"
    )
    result_sha = hashlib.sha256(result).hexdigest()
    entries = {
        "RESULT.txt": b"fixture summary\n",
        "result.json": result,
        "result.json.sha256": f"{result_sha}  result.json\n".encode(),
    }
    for name, data in entries.items():
        (session / name).write_bytes(data)
    complete = {
        "files": {
            name: hashlib.sha256(data).hexdigest() for name, data in entries.items()
        },
        "log_status": "complete",
        "manifest_scope": "content_only",
        "safe_to_remove": False,
        "schema_version": 1,
        "result_summary": "RESULT.txt",
        "share_copy": "",
        "share_summary": "",
        "privacy_policy_version": 0,
    }
    text = json.dumps(complete)
    if ambiguous_file == "COMPLETE":
        text = text.replace(
            '"log_status": "complete"',
            '"log_status": "unavailable", "log_status": "complete"',
        )
    (session / "COMPLETE").write_text(text)
    command = [
        "python3",
        "-c",
        verifier,
        str(tmp_path),
        "verified",
        "everyday",
        "prng",
        "Everyday",
        "local",
        "a" * 40,
    ]
    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode != 0
    assert "duplicate JSON field" in checked.stderr + checked.stdout
