"""Recovery must interpret the exact terminal evidence bound to its journal."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from beamo_wipe import evidence as evidence_module
from beamo_wipe.safety import SafetyError
from beamo_wipe.session_recovery import SessionStore
from test_session_recovery import BOOT, BUILD, armed, finish


def test_recovery_rejects_evidence_replacement_between_journal_read_and_result_check(
    tmp_path, monkeypatch
):
    directory = tmp_path / "private"
    monkeypatch.setattr("beamo_wipe.safety.DEFAULT_LOG_DIR", directory)
    first = SessionStore(directory, boot=BOOT, build=BUILD).open()
    second = SessionStore(directory, boot=BOOT, build=BUILD)
    try:
        discovery, request = armed(first)
        path = finish(first, discovery, request)
        first.close()
        second.open()
        original_recover = evidence_module.recover_result

        def replace_then_recover(evidence_path: Path, **kwargs):
            # The journal already read and authenticated the original bytes.
            # Replace them with another individually checksummed successful
            # record before the second read, while invalidating the original log.
            old_log = Path(request.logfile)
            original_log = old_log.read_bytes()
            other_log = directory / "nwipe-other.log"
            other_log.write_bytes(original_log)
            os.chmod(other_log, 0o600)
            old_log.write_text("corrupt old log\n")
            replacement = json.loads(path.read_text())
            replacement["logfile"] = str(other_log)
            data = (json.dumps(replacement, sort_keys=True) + "\n").encode()
            path.write_bytes(data)
            Path(str(path) + ".sha256").write_text(
                f"{hashlib.sha256(data).hexdigest()}  {path.name}\n"
            )
            return original_recover(evidence_path, **kwargs)

        monkeypatch.setattr(evidence_module, "recover_result", replace_then_recover)
        with pytest.raises(SafetyError, match="Terminal result cannot be proved"):
            second.terminal()
    finally:
        first.close()
        second.close()
