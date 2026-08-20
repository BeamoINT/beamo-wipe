# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from beamo_wipe import NWIPE_PINNED_COMMIT, NWIPE_PINNED_VERSION

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "packaging/live/config/includes.chroot/root/.profile"
PACKAGES = ROOT / "packaging/live/config/package-lists/beamo.list.chroot"
HOOK = ROOT / "packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot"
LAUNCHER = ROOT / "packaging/live/config/includes.chroot/usr/local/bin/beamo-wipe"

FORBIDDEN_PACKAGES = (
    "curl",
    "git",
    "build-essential",
    "sudo",
    "iputils-ping",
    "network-manager",
)


def test_live_profile_does_not_timeout_the_running_wizard():
    text = PROFILE.read_text(encoding="utf-8")
    assert "timeout 90 startx /usr/local/bin/beamo-wipe" not in text
    assert "beamo-wipe" in text
    assert "while" in text
    assert "nwipe" not in text.split("beamo-wipe")[0] or "exec nwipe" not in text


def test_live_profile_does_not_auto_start_nwipe():
    text = PROFILE.read_text(encoding="utf-8")
    assert "nwipe --autonuke" not in text
    assert "exec nwipe" not in text


def test_live_packages_include_hdparm():
    text = PACKAGES.read_text(encoding="utf-8")
    assert "hdparm" in text.split()


def test_live_packages_omit_network_and_compilers():
    names = {
        line.strip()
        for line in PACKAGES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for pkg in FORBIDDEN_PACKAGES:
        assert pkg not in names, pkg


def test_nwipe_hook_fails_closed_instead_of_unpinned_fallback():
    text = HOOK.read_text(encoding="utf-8")
    assert f"v{NWIPE_PINNED_VERSION}" in text or f"{NWIPE_PINNED_VERSION}" in text
    assert NWIPE_PINNED_COMMIT in text
    assert "apt-get install -y nwipe" not in text
    assert "apt-get purge -y nwipe" not in text
    assert "ERROR: gcc is still present" in text
    assert "ERROR: nwipe commit" in text


def test_live_launcher_isolates_sys_path_and_preview_env():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "python3 -P" in text
    assert "PYTHONPATH=/usr/lib/python3/dist-packages" in text
    assert "unset BEAMO_WIPE_DRY_RUN" in text
    assert "unset BEAMO_WIPE_BOOT_DEVICE" in text
    assert "cd /" in text
    assert "--demo" not in text
    assert "--dry-run" not in text
