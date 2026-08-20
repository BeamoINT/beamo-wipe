# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "packaging/live/config/includes.chroot/root/.profile"
PACKAGES = ROOT / "packaging/live/config/package-lists/beamo.list.chroot"
HOOK = ROOT / "packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot"


def test_live_profile_does_not_timeout_the_running_wizard():
    text = PROFILE.read_text(encoding="utf-8")
    assert "timeout 90 startx /usr/local/bin/beamo-wipe" not in text
    assert "beamo-wipe" in text
    assert "while" in text
    assert "nwipe" not in text.split("beamo-wipe")[0] or "exec nwipe" not in text


def test_live_packages_include_hdparm():
    text = PACKAGES.read_text(encoding="utf-8")
    assert "hdparm" in text.split()


def test_nwipe_hook_fails_closed_instead_of_unpinned_fallback():
    text = HOOK.read_text(encoding="utf-8")
    assert "v0.42" in text
    assert "apt-get install -y nwipe" not in text
