"""The privileged report worker must reject ambiguous request JSON."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import (
    LOG_STATUS_MALFORMED,
    REQUEST_MALFORMED,
    _decode_worker_request,
)


def _request(evidence: bytes = b"{}") -> dict:
    parent = dict(
        path="/dev/sdc", size_bytes=64_000_000, model="Report", serial="R1", wwn=""
    )
    return {
        "evidence": base64.b64encode(evidence).decode("ascii"),
        "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "volume": dict(
            parent=parent,
            path="/dev/sdc1",
            size_bytes=64_000_000,
            fstype="vfat",
            fsver="FAT32",
            uuid="AAAA-BBBB",
        ),
        "baseline": [],
        "protected_rdevs": [],
        "log": "",
        "log_status": "unavailable",
        "privacy_reduced": False,
    }


@pytest.mark.parametrize("where", ["top", "nested", "evidence"])
def test_worker_request_rejects_duplicate_fields(where):
    if where == "evidence":
        data = json.dumps(
            _request(b'{"outcome":"failed","outcome":"verified"}'),
            separators=(",", ":"),
        ).encode()
    else:
        data = json.dumps(_request(), separators=(",", ":")).encode()
        assert _decode_worker_request(data)[5] == "unavailable"
    if where == "top":
        data = data.replace(
            b'"log_status":"unavailable"',
            b'"log_status":"complete","log_status":"unavailable"',
            1,
        )
    elif where == "nested":
        data = data.replace(
            b'"path":"/dev/sdc1"',
            b'"path":"/dev/sdb1","path":"/dev/sdc1"',
            1,
        )
    with pytest.raises(SafetyError, match=REQUEST_MALFORMED):
        _decode_worker_request(data)


@pytest.mark.parametrize("status", [[], {}, ["unavailable"], {"status": "unavailable"}])
def test_worker_request_rejects_non_string_log_status(status):
    request = _request()
    request["log_status"] = status
    with pytest.raises(SafetyError, match=LOG_STATUS_MALFORMED):
        _decode_worker_request(json.dumps(request).encode())
