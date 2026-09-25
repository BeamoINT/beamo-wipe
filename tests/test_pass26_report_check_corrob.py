"""A report README must corroborate advisory pass claims with its own log."""

from __future__ import annotations

import json

from beamo_wipe import engine_checks
from beamo_wipe.models import MethodId
from beamo_wipe.support_export import _bundle_files
from test_result_presentations import ERASED, STATUS, case_evidence


def _claim_with_pass_checks():
    _, claim, _ = case_evidence(
        ("verified", MethodId.EVERYDAY, 0, STATUS + ERASED, False, False)
    )
    claim["checks"] = [
        {"id": "hidden_capacity", "status": "pass", "summary": engine_checks.HIDDEN_NONE},
        {"id": "io_media", "status": "pass", "summary": engine_checks.IO_CLEAN},
    ]
    return claim


def test_readme_omits_uncorroborated_pass_checks_without_log():
    claim = _claim_with_pass_checks()
    files = _bundle_files(json.dumps(claim).encode(), b"", "unavailable")
    readme = files["README.txt"].decode()
    assert "Check hidden_capacity: pass." not in readme
    assert "Check io_media: pass." not in readme


def test_readme_omits_pass_checks_when_exported_log_contradicts_them():
    claim = _claim_with_pass_checks()
    device = claim["device"]["path"]
    name = claim["device"]["name"]
    log = (
        f"*** HIDDEN SECTORS DETECTED ! *** on {device}\n"
        f"Error Summary\n  {name} | 2 | 0 | 0\n***\n"
    ).encode()
    files = _bundle_files(json.dumps(claim).encode(), log, "complete")
    readme = files["README.txt"].decode()
    assert "Check hidden_capacity: pass." not in readme
    assert "Check io_media: pass." not in readme


def test_readme_keeps_pass_checks_corrobated_by_exported_log():
    claim = _claim_with_pass_checks()
    device = claim["device"]["path"]
    name = claim["device"]["name"]
    log = (
        f"No hidden sectors on {device}\n"
        f"Error Summary\n  {name} | 0 | 0 | 0\n***\n"
    ).encode()
    files = _bundle_files(json.dumps(claim).encode(), log, "complete")
    readme = files["README.txt"].decode()
    assert "Check hidden_capacity: pass." in readme
    assert "Check io_media: pass." in readme

    # A matching final tail cannot rule out an earlier warning or error.
    tail_files = _bundle_files(json.dumps(claim).encode(), log, "tail")
    tail_readme = tail_files["README.txt"].decode()
    assert "Check hidden_capacity: pass." not in tail_readme
    assert "Check io_media: pass." not in tail_readme
