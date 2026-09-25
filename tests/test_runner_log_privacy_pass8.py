"""A failed nwipe log read must not disclose the selected media in diagnostics."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from beamo_wipe.nwipe_runner import NwipeRunner


@pytest.mark.parametrize("failure", ["open", "not_regular", "read"])
def test_log_read_diagnostics_omit_log_filename(tmp_path, monkeypatch, failure):
    secret = "PRIVATE_SERIAL_4821"
    monkeypatch.chdir(tmp_path)
    log = Path(f"nwipe-{secret}.log")
    runner = NwipeRunner()
    messages = []
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner._try_log_diag",
        lambda area, code, detail="": messages.append((area, code, detail)),
    )
    if failure == "open":
        def refuse_open(path, *args, **kwargs):
            if str(path) == str(log):
                raise PermissionError("refused")
            return original_open(path, *args, **kwargs)

        original_open = os.open
        monkeypatch.setattr(os, "open", refuse_open)
    elif failure == "not_regular":
        log.mkdir()
    else:
        log.write_text("safe test data", encoding="utf-8")
        def refuse_read(*args, **kwargs):
            raise OSError("refused")

        monkeypatch.setattr(os, "fdopen", refuse_read)

    assert runner._read_log_tail(str(log), 100) == ""
    assert messages
    assert secret not in repr(messages)
