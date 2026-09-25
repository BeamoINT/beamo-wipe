# SPDX-License-Identifier: GPL-3.0-or-later
"""Runner diagnostics must not copy a selected device's private path."""

from __future__ import annotations

from unittest.mock import Mock

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner


def test_ambiguous_completion_diagnostic_omits_device_path(tmp_path, monkeypatch):
    runner = NwipeRunner()
    proc = Mock()
    proc.poll.return_value = 0
    runner._proc = proc
    monkeypatch.setattr(runner, "_refresh_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "_read_log_tail", lambda *_args, **_kwargs: "incomplete log")
    messages = []
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner._try_log_diag",
        lambda area, code, detail="": messages.append((area, code, detail)),
    )
    secret = "SERIAL_PRIVATE_123"
    request = WipeRequest(
        f"/dev/{secret}", MethodId.EVERYDAY, "/dev/boot", str(tmp_path / "nwipe.log")
    )
    result = runner.poll(request)
    assert result is not None and not result.ok
    assert any(code == "verification_ambiguous" for _area, code, _detail in messages)
    assert secret not in repr(messages)
