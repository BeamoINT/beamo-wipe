# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-session power policy from shipped files and fake processes only."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import MethodId, Screen, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.sleep_inhibit import WHAT, SleepInhibit, inhibit_argv
from beamo_wipe.wizard import Wizard

ROOT = Path(__file__).resolve().parents[1]
CHROOT = ROOT / "packaging/live/config/includes.chroot"
LOGIND = CHROOT / "etc/systemd/logind.conf.d/beamo-kiosk.conf"
SLEEP = CHROOT / "etc/systemd/sleep.conf.d/beamo-kiosk.conf"
XORG = CHROOT / "etc/X11/xorg.conf.d/10-beamo.conf"
HOOK = ROOT / "packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot"
LAUNCHER = CHROOT / "usr/local/bin/beamo-wipe"
KIOSK = CHROOT / "etc/systemd/system/beamo-wipe-kiosk.service"
PACKAGES = ROOT / "packaging/live/config/package-lists/beamo.list.chroot"
QEMU = ROOT / "scripts/qemu-verify.sh"
HELPER = ROOT / "helper/index.html"
RECEIPT = ROOT / "docs/evidence/live-session-power-20260910.md"
POLICY = ROOT / "docs/live-session-power.md"


def test_logind_ignores_lid_idle_sleep_keys_and_short_power_press():
    text = LOGIND.read_text(encoding="utf-8")
    for line in (
        "HandlePowerKey=ignore",
        "HandleSuspendKey=ignore",
        "HandleHibernateKey=ignore",
        "HandleLidSwitch=ignore",
        "HandleLidSwitchExternalPower=ignore",
        "HandleLidSwitchDocked=ignore",
        "IdleAction=ignore",
        "NAutoVTs=1",
    ):
        assert line in text
    assert "HandlePowerKey=poweroff" not in text
    assert "HandleLidSwitch=suspend" not in text
    assert "IdleAction=suspend" not in text


def test_sleep_conf_refuses_os_sleep_and_not_poweroff():
    text = SLEEP.read_text(encoding="utf-8")
    assert "AllowSuspend=no" in text
    assert "AllowHibernation=no" in text
    assert "AllowSuspendThenHibernate=no" in text
    assert "AllowHybridSleep=no" in text
    assert "AllowPowerOff" not in text


def test_xorg_blanks_display_without_requesting_os_sleep():
    text = XORG.read_text(encoding="utf-8")
    assert 'Option "BlankTime" "10"' in text
    assert 'Option "StandbyTime" "0"' in text
    assert 'Option "SuspendTime" "0"' in text
    assert 'Option "OffTime" "0"' in text
    assert "screensaver" in text.lower() or "display blanking" in text.lower()
    assert "does not suspend" in text.lower()


def test_launcher_requests_a_key_or_mouse_unblank():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "xset s 600 s blank s on" in text
    assert "xset dpms 0 0 0" in text
    assert "DISPLAY" in text
    assert "x11-xserver-utils" in PACKAGES.read_text(encoding="utf-8")


def test_hook_masks_sleep_units_and_does_not_overwrite_logind():
    text = HOOK.read_text(encoding="utf-8")
    assert "cat > /etc/systemd/logind.conf.d/beamo-kiosk.conf" not in text
    assert "missing live-session power policy" in text
    for unit in (
        "sleep.target",
        "suspend.target",
        "hibernate.target",
        "hybrid-sleep.target",
        "suspend-then-hibernate.target",
    ):
        assert unit in text
    assert "poweroff.target" not in text
    assert "reboot.target" not in text


def test_kiosk_restart_does_not_block_wizard_poweroff():
    text = KIOSK.read_text(encoding="utf-8")
    assert "Restart=no" in text
    assert "ExecStart=/usr/local/sbin/beamo-wipe-kiosk" in text


def test_no_desktop_power_manager_package():
    names = {
        line.strip()
        for line in PACKAGES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for pkg in (
        "xfce4-power-manager",
        "gnome-settings-daemon",
        "power-profiles-daemon",
        "upower",
        "pm-utils",
        "acpi-support",
    ):
        assert pkg not in names


def test_qemu_verify_inspects_squashfs_power_policy():
    text = QEMU.read_text(encoding="utf-8")
    assert "HandleLidSwitch=ignore" in text
    assert "AllowSuspend=no" in text
    assert 'Option "BlankTime" "10"' in text
    assert "suspend.target" in text
    assert "no host block" in text.lower() or "no /dev" in text


def test_ac_reminder_and_blanking_copy_are_visible_and_honest():
    assert "battery" in C.POWER_REMINDER.lower()
    assert "wall power" in C.POWER_REMINDER.lower()
    assert "power cut" in C.POWER_REMINDER.lower()
    assert "display" in C.POWER_BLANKING.lower()
    assert "not sleep" in C.POWER_BLANKING.lower()
    assert "wall power" in C.WORKING_PULSE.lower()
    helper = HELPER.read_text(encoding="utf-8").lower()
    assert "wall power" in helper
    assert "not sleep" in helper
    assert "impossible to recover" not in helper
    blob = " ".join(
        [C.POWER_REMINDER, C.POWER_BLANKING, C.WORKING_PULSE]
    ).lower()
    assert "never sleeps" not in blob
    assert "firmware cannot" not in blob


def test_inhibit_blocks_sleep_not_shutdown():
    argv = inhibit_argv()
    assert argv[0] == "/usr/bin/systemd-inhibit"
    assert "--what=sleep:idle" in argv
    assert "--mode=block" in argv
    assert "shutdown" not in WHAT
    assert "--what=shutdown" not in argv
    assert argv[-2:] == ["/bin/sleep", "infinity"]


def test_inhibit_is_live_only_and_releases(monkeypatch):
    started = []

    class FakeProc:
        def __init__(self):
            self._code = None

        def poll(self):
            return self._code

        def terminate(self):
            self._code = 0

        def kill(self):
            self._code = 9

        def wait(self, timeout=None):
            return self._code

    def fake_popen(argv, **kwargs):
        started.append((argv, kwargs["env"]["PATH"]))
        return FakeProc()

    inhibit = SleepInhibit()
    monkeypatch.delenv("BEAMO_WIPE_LIVE", raising=False)
    with patch("beamo_wipe.sleep_inhibit.subprocess.Popen", fake_popen):
        inhibit.start()
        assert started == []
        monkeypatch.setenv("BEAMO_WIPE_LIVE", "1")
        monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
        inhibit.start()
        assert started == []
        monkeypatch.delenv("BEAMO_WIPE_DRY_RUN")
        inhibit.start()
        assert inhibit.active
        assert started[0][0] == inhibit_argv()
        inhibit.stop()
        assert not inhibit.active


def test_inhibitor_stop_failure_keeps_its_process_for_retry(monkeypatch):
    """A failed stop must not lose the only handle to a live sleep inhibitor."""
    class FakeProc:
        def __init__(self):
            self.fail = True
            self.code = None

        def poll(self):
            return self.code

        def terminate(self):
            if self.fail:
                raise OSError("terminate denied")
            self.code = -15

        def kill(self):
            if self.fail:
                raise OSError("kill denied")
            self.code = -9

        def wait(self, timeout=None):
            return self.code

    proc = FakeProc()
    inhibit = SleepInhibit()
    inhibit._proc = proc
    monkeypatch.setenv("BEAMO_WIPE_LIVE", "1")
    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    started = []
    monkeypatch.setattr("beamo_wipe.sleep_inhibit.subprocess.Popen", lambda *a, **kw: started.append(a))
    inhibit.stop()
    assert inhibit._proc is proc
    inhibit.start()
    assert inhibit._proc is proc
    assert started == [], "do not overwrite a handle to an inhibitor that may still run"
    proc.fail = False
    inhibit.stop()
    assert inhibit._proc is None


def test_failed_engine_spawn_releases_sleep_inhibitor(tmp_path, monkeypatch):
    """All paths are fake; no disk or systemd process is opened."""
    import beamo_wipe.nwipe_runner as runner_module

    runner = NwipeRunner()
    runner._sleep_inhibit = Mock()
    runner._acquire_wipe_lock = Mock()
    runner._release_wipe_lock = Mock()
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    monkeypatch.setattr(runner_module, "resolve_nwipe_binary", lambda _binary: "/usr/lib/beamo-wipe/nwipe")
    monkeypatch.setattr(runner_module, "require_real_live_for_nwipe", lambda: None)
    monkeypatch.setattr(runner_module, "pinned_nwipe_already_running", lambda **_kw: False)
    monkeypatch.setattr(runner_module, "_verify_pinned_nwipe", lambda _path: None)
    monkeypatch.setattr(runner_module, "assert_existing_is_block_device", lambda *_a, **_kw: None)
    monkeypatch.setattr(runner_module, "assert_not_boot", lambda *_a, **_kw: None)
    monkeypatch.setattr(runner_module, "assert_size_unchanged", lambda *_a: None)
    monkeypatch.setattr(runner_module, "assert_local_device_transport", lambda _path: None)
    monkeypatch.setattr(runner_module, "block_rdev", lambda path: 1 if path == "/dev/vda" else 2)
    monkeypatch.setattr(runner_module, "_recheck_identity_under_lock", lambda _request: None)
    monkeypatch.setattr(runner_module, "truncate_log_file", lambda *_a: None)
    # A child-reported exec failure names the executable and is proven
    # reaped; a generic parent OSError after fork cannot release ownership.
    monkeypatch.setattr(
        runner_module.subprocess,
        "Popen",
        Mock(side_effect=FileNotFoundError(2, "fake spawn failure", "/usr/lib/beamo-wipe/nwipe")),
    )
    request = WipeRequest(
        "/dev/vda", MethodId.EVERYDAY, "/dev/sdb", str(tmp_path / "nwipe.log"),
        device_rdev=1, device_size_bytes=500_000_000_000, boot_rdev=2,
    )
    with pytest.raises(OSError, match="fake spawn failure"):
        runner.start(request)
    runner._sleep_inhibit.start.assert_called_once()
    runner._sleep_inhibit.stop.assert_called_once()


@pytest.mark.parametrize("screen", [Screen.WORKING, Screen.CHECKING, Screen.STOPPING])
def test_shutdown_stays_blocked_while_erase_may_be_running(screen):
    wiz = make_demo_wizard()
    wiz.preview = False
    wiz.screen = screen
    wiz.shutdown()
    assert wiz.screen == screen
    assert not wiz.wants_shutdown


@pytest.mark.parametrize("probe_error", [False, True])
def test_live_shutdown_refuses_unowned_pinned_engine(monkeypatch, probe_error):
    """A legacy/manual nwipe process may not hold this wizard's runner lock."""
    def process_probe(**_kwargs):
        if probe_error:
            raise OSError("process state unknown")
        return True

    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running",
        process_probe,
    )
    wiz = Wizard(make_demo_wizard().discovery, NwipeRunner(), dry_run=False)
    wiz.shutdown()
    assert not wiz.wants_shutdown
    assert wiz.screen == Screen.SPLASH

    wiz.screen = Screen.SHUTDOWN_CONFIRM
    wiz._shutdown_from = Screen.SPLASH
    wiz.shutdown_generation += 1
    wiz.confirm_shutdown_without_saving(wiz.shutdown_generation)
    assert not wiz.wants_shutdown


def test_live_shutdown_allows_confirmed_quiescent_engine(monkeypatch):
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running",
        lambda **_kwargs: False,
    )
    wiz = Wizard(make_demo_wizard().discovery, NwipeRunner(), dry_run=False)
    wiz.shutdown()
    assert wiz.wants_shutdown


def test_receipts_do_not_claim_untested_lid_or_firmware():
    receipt = RECEIPT.read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")
    assert "2026-09-10" in receipt
    assert "Not run" in receipt
    assert "Do not claim lid close never sleeps" in receipt
    assert "firmware" in receipt.lower()
    assert "QEMU guests have no lid switch" in receipt
    assert "held power button" in receipt.lower()
    assert "does not" in policy.lower() and "firmware" in policy.lower()
    assert "fake" in receipt.lower() or "fake-device" in receipt.lower()
