"""Malformed authenticated evidence must fail with a bounded export refusal."""

from __future__ import annotations

import hashlib
import json

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import (
    EVIDENCE_MALFORMED,
    EVIDENCE_NOT_FINISHED,
    EVIDENCE_SCHEMA,
    prepare_terminal_evidence,
)


def _evidence_file(tmp_path, **changes):
    path = tmp_path / "result-test.json"
    payload = {
        "schema_version": 2,
        "outcome": "failed",
        "device": {"path": "/dev/sda"},
        "provenance": {"evidence_file": str(path)},
        "logfile": "",
        "log_checksum_sha256": None,
        "log_snapshot_size_bytes": 0,
    }
    payload.update(changes)
    data = json.dumps(payload).encode()
    path.write_bytes(data)
    path.with_name(path.name + ".sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  {path.name}\n"
    )
    return path


@pytest.mark.parametrize("version", [True, [2], {"version": 2}])
def test_malformed_schema_is_bounded_refusal(tmp_path, version):
    path = _evidence_file(tmp_path, schema_version=version)
    with pytest.raises(SafetyError, match=EVIDENCE_SCHEMA):
        prepare_terminal_evidence(path, "/dev/sda")


@pytest.mark.parametrize("outcome", [["failed"], {"name": "failed"}])
def test_malformed_outcome_is_bounded_refusal(tmp_path, outcome):
    path = _evidence_file(tmp_path, outcome=outcome)
    with pytest.raises(SafetyError, match=EVIDENCE_NOT_FINISHED):
        prepare_terminal_evidence(path, "/dev/sda")


def test_duplicate_evidence_field_is_not_exportable(tmp_path):
    path = tmp_path / "result-test.json"
    data = (
        b'{"schema_version":2,"outcome":"verified","outcome":"failed",'
        b'"device":{"path":"/dev/sda"},"provenance":{"evidence_file":"'
        + str(path).encode()
        + b'"},"logfile":"","log_snapshot_size_bytes":0}'
    )
    path.write_bytes(data)
    path.with_name(path.name + ".sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  {path.name}\n"
    )
    with pytest.raises(SafetyError, match=EVIDENCE_MALFORMED):
        prepare_terminal_evidence(path, "/dev/sda")
