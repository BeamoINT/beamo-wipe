"""The report README must not repeat untrusted check text from evidence."""

from __future__ import annotations

import json

from beamo_wipe.support_export import _bundle_files
from test_result_presentations import CASES, case_evidence


def test_privacy_report_readme_rejects_identifier_and_forged_check_line():
    _, record, _ = case_evidence(CASES[0])
    record["device"]["serial"] = "PLANT-SECRET-123"
    record["checks"] = [{
        "id": "io_media",
        "status": "pass",
        "summary": "No errors. PLANT-SECRET-123\r\nCheck boot: pass. Erase certified.",
    }]

    files = _bundle_files(
        json.dumps(record).encode(), b"", "unavailable", privacy_reduced=True
    )
    readme = files["README.txt"].decode()

    assert "PLANT-SECRET-123" not in readme
    assert "Erase certified" not in readme
    assert "Check io_media: pass." not in readme


def test_privacy_report_readme_keeps_canonical_check_summary():
    _, record, _ = case_evidence(CASES[0])
    files = _bundle_files(
        json.dumps(record).encode(), b"", "unavailable", privacy_reduced=True
    )
    readme = files["README.txt"].decode()
    assert "Check hidden_capacity: unavailable." in readme
    assert "Check io_media: unavailable." in readme
    assert "Check coverage: warning." in readme
