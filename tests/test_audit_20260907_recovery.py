# SPDX-License-Identifier: GPL-3.0-or-later
"""Malformed report regression checks; temporary files only, no devices."""

import pytest

from beamo_wipe import diagnostic_report as diagnostic
from beamo_wipe import support_export
from beamo_wipe.models import DiscoveryResult
from beamo_wipe.safety import SafetyError


def _report():
    return diagnostic.create_report(
        "discovery_failed", DiscoveryResult(error="private"),
        ui="console", session_started=0,
    )


@pytest.mark.parametrize("boundary", ["prepare", "bundle"])
@pytest.mark.parametrize("field", [b'"raw_logs":', b'"ui":', b'"code":'])
def test_duplicate_report_fields_cannot_hide_private_export_bytes(tmp_path, field, boundary):
    original = _report()
    data = original.replace(field, field + b'"private SERIAL secret",' + field, 1)
    assert data != original
    with pytest.raises(SafetyError, match="diagnostic report"):
        if boundary == "prepare":
            diagnostic.verified_report(data)
        else:
            support_export.write_report_bundle(tmp_path, data, b"", "unavailable")
    assert not list(tmp_path.rglob("diagnostic.json"))


def test_unique_report_remains_exportable_and_readback_verified(tmp_path):
    data = _report()
    assert diagnostic.verified_report(data).data == data
    session, files = support_export.write_report_bundle(tmp_path, data, b"", "unavailable")
    support_export.verify_report_bundle(tmp_path, session, files)
    assert files["diagnostic.json"] == data


def test_linked_diagnostic_log_cannot_modify_another_file(tmp_path):
    import os
    from beamo_wipe.diagnostics import log_diag

    directory = tmp_path / "logs"
    directory.mkdir(mode=0o700)
    unrelated = tmp_path / "unrelated.json"
    original = b'{"preserve":"user evidence"}\n'
    unrelated.write_bytes(original)
    unrelated.chmod(0o644)
    os.link(unrelated, directory / "diagnostics.log")
    assert log_diag("audit", "check", log_dir=directory) is False
    assert unrelated.read_bytes() == original
    assert unrelated.stat().st_mode & 0o777 == 0o644
