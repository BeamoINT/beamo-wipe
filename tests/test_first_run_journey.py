# SPDX-License-Identifier: GPL-3.0-or-later
"""First-run journey: guidance, defaults, progress, and recovery.

Fake disks only; never a real disk. Every test preserves the fail-closed
boundaries (boot USB never selectable, no auto-start, token+5s+checkbox).
"""

from __future__ import annotations

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.discover import discover
from beamo_wipe.models import DiscoveryResult, Screen
from beamo_wipe.safety import SafetyError, require_live_or_dry_run, selectable_disks


def test_gate_refusal_names_next_action():
    with pytest.raises(SafetyError) as exc:
        require_live_or_dry_run(env={}, cmdline="")
    message = str(exc.value)
    assert "preview" in message.lower()
    assert "USB" in message or "usb" in message.lower()


def test_cli_marks_test_flags_ignored_on_live():
    from beamo_wipe.app import _parser

    text = " ".join(_parser().format_help().split())
    for flag in ("--dry-run", "--lsblk-json", "--boot-device"):
        assert flag in text
    assert text.count("ignored on the live USB") >= 3


def test_live_overrides_still_clear_and_log(monkeypatch, tmp_path):
    from beamo_wipe.app import apply_live_session_overrides, _parser

    monkeypatch.setattr("beamo_wipe.app.running_on_live_usb", lambda: True)
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    args = _parser().parse_args(["--demo", "--dry-run", "--boot-device", "/dev/sda"])
    apply_live_session_overrides(args)
    assert args.demo is False
    assert args.dry_run is False
    assert args.boot_device is None
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert "live_overrides_cleared" in diag


def test_blocked_error_labels_support_detail():
    base = make_demo_wizard()
    blocked = DiscoveryResult(
        error=C.IDENTIFY_ERROR,
        boot_identified=False,
        diagnostic="TimeoutExpired: lsblk",
    )
    from beamo_wipe.wizard import Wizard

    wiz = Wizard(blocked, base.runner, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK_BLOCKED
    assert "Support detail" in (wiz.error or "")
    assert "TimeoutExpired" in (wiz.error or "")


def test_empty_shows_boot_read_only_and_never_selectable():
    wiz = make_demo_wizard(scenario="empty")
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK_EMPTY
    assert wiz.selectable == ()
    detail = wiz.empty_detail
    assert wiz.discovery.boot is not None
    assert wiz.discovery.boot.path in detail
    assert "not erasable" in detail.lower()
    # Boot disk is listed for identification but never in the safe set.
    assert wiz.discovery.boot.path not in {d.path for d in selectable_disks(wiz.discovery)}


def test_discover_timing_is_logged(monkeypatch, tmp_path):
    from beamo_wipe import demo as _demo
    from beamo_wipe.app import _build_wizard, _parser

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    lsblk_json = tmp_path / "lsblk.json"
    lsblk_json.write_text(
        (_demo.HERE / "demo_lsblk.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    args = _parser().parse_args(
        ["--lsblk-json", str(lsblk_json), "--boot-device", "/dev/sdb"]
    )
    wiz = _build_wizard(args)
    assert wiz.discovery.boot_identified
    assert len(selectable_disks(wiz.discovery)) >= 1
    diag = (tmp_path / "diagnostics.log").read_text(encoding="utf-8")
    assert '"timing"' in diag or "timing" in diag


def test_malformed_node_never_mints_bare_dev():
    result = discover(
        lsblk_payload={"blockdevices": [{"name": "", "type": "disk"}]},
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    assert not result.boot_identified
    assert C.IDENTIFY_ERROR.lower() in (result.error or "").lower()
    assert all(d.path != "/dev/" for d in result.disks)


def test_cancel_keeps_interrupted_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz = make_demo_wizard(scenario="happy")
    wiz.preview = False
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    assert wiz.screen == Screen.PICK
    disk = sorted(wiz.selectable, key=lambda d: d.path)[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    assert wiz.confirm is not None
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = wiz.now  # skip the 5s wait without touching the gate
    wiz.confirm_erase()
    assert wiz.screen == Screen.WORKING
    wiz.cancel_wipe()
    assert wiz.screen == Screen.DONE
    assert wiz.wipe_result is not None and not wiz.wipe_result.ok
    assert wiz.wipe_result.summary == "interrupted"
    assert (wiz.evidence or {}).get("outcome") == "interrupted"
