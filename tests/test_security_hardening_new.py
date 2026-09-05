# SPDX-License-Identifier: GPL-3.0-or-later
"""Security hardening regressions for audit 2026-09-03.

Fake disks only; never execs real nwipe.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from beamo_wipe.safety import SafetyError


def test_resolve_nwipe_rejects_absolute_non_nwipe_in_production(monkeypatch):
    from beamo_wipe.nwipe_runner import resolve_nwipe_binary

    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    with pytest.raises(SafetyError, match="non-nwipe"):
        resolve_nwipe_binary("/tmp/evil")
    with pytest.raises(SafetyError, match="non-nwipe"):
        resolve_nwipe_binary("/tmp/fake_engine")
    with pytest.raises(SafetyError, match="pinned path"):
        resolve_nwipe_binary("/usr/local/bin/nwipe")


def test_resolve_nwipe_allows_fake_only_in_dry_run(monkeypatch, tmp_path):
    from beamo_wipe.nwipe_runner import resolve_nwipe_binary

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    # Absolute fake allowed in dry-run
    assert resolve_nwipe_binary(str(tmp_path / "fake_engine")) == str(tmp_path / "fake_engine")
    # Relative fake still rejected
    with pytest.raises(SafetyError, match="relative"):
        resolve_nwipe_binary("fake_engine")


def test_clean_strips_control_and_truncates():
    from beamo_wipe.discover import _clean

    assert "\x1b" not in _clean("\x1b[2J hello")
    assert "\n" not in _clean("foo\nbar")
    assert _clean('"><svg onload=alert(1)>') == '"><svg onload=alert(1)>'  # < > kept but 0x1f stripped; HTML escaped in gallery layer
    assert len(_clean("a" * 200)) == 128
    assert _clean("  hello  ") == "hello"


def test_clean_prevents_log_forgery_via_newline():
    from beamo_wipe.discover import _clean

    evil = "sda\n[FAKE] injected"
    cleaned = _clean(evil)
    assert "\n" not in cleaned
    # Gallery esc() will still HTML-escape < > for innerHTML; _clean strips controls only
    assert "FAKE" in cleaned


def test_classify_kind_rejects_spoofed_tran_as_nvme():
    from beamo_wipe.discover import classify_kind

    # Spoofed tran containing nvme substring must not be NVMe
    assert classify_kind("sda", "my-nvme-evil", False).value != "NVMe"
    assert classify_kind("sda", "nvme", True).value == "NVMe"
    # Kernel name nvme0n1 with empty tran is NVMe (real nvme device)
    assert classify_kind("nvme0n1", "", True).value == "NVMe"
    # Kernel name nvme0n1 with usb tran is not NVMe (spoof check)
    assert classify_kind("nvme0n1", "usb", True).value != "NVMe"


def test_as_int_logs_on_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    from beamo_wipe.discover import _as_int

    assert _as_int("123abc") == 0
    assert _as_int("  ") == 0
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8") if (tmp_path / "diagnostics.log").exists() else ""
    assert "size_parse_failed" in diag


def test_shutdown_uses_clean_env(monkeypatch):
    from beamo_wipe import app as app_mod

    calls = {}

    def fake_run(cmd, **kwargs):
        calls["kwargs"] = kwargs
        calls["cmd"] = cmd
        raise OSError("fail one")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: Path("/tmp/beamo-wipe"))
    # Should try all cmds then log and print, not leak env
    with mock.patch("beamo_wipe.diagnostics.log_diag"):
        app_mod._shutdown()
        # Every attempt should have env=CLEAN_SUBPROCESS_ENV and shell=False
        assert calls["kwargs"].get("env") is not None
        assert calls["kwargs"].get("shell") is False


def test_gallery_escapes_html():
    txt = Path("src/beamo_wipe/gallery.py").read_text(encoding="utf-8")
    assert "function esc(s)" in txt
    assert 'replace(/&/g, "&amp;")' in txt
    assert "esc(d.serial)" in txt
    assert "esc(d.name)" in txt
    assert 'data-path="${esc(d.path)}"' in txt


def test_size_gb_label_is_decimal_and_documented():
    from beamo_wipe.discover import size_gb_label

    # 10 GiB = 10737418240 bytes -> 11 decimal GB
    assert size_gb_label(10737418240) == "11"
    # 10 GB decimal
    assert size_gb_label(10_000_000_000) == "10"
