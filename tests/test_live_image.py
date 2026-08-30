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
    "openssh-server",
    "wget",
    "nmap",
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
    assert "git clone nwipe failed after" in text
    assert "GIT_CONFIG_NOSYSTEM=1" in text
    assert "GIT_CONFIG_GLOBAL=/dev/null" in text
    assert "GIT_CONFIG_SYSTEM=/dev/null" in text


def test_live_launcher_isolates_sys_path_and_preview_env():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "python3 -sP" in text
    assert "PYTHONPATH=/usr/lib/python3/dist-packages" in text
    assert "PYTHONNOUSERSITE=1" in text
    assert "unset BEAMO_WIPE_DRY_RUN" in text
    assert "unset BEAMO_WIPE_BOOT_DEVICE" in text
    assert "unset LD_PRELOAD" in text
    assert "unset PYTHONSTARTUP" in text
    assert "PATH=/usr/sbin:/usr/bin:/sbin:/bin" in text
    assert "umask 077" in text
    assert "cd /" in text
    assert "--demo" not in text
    assert "--dry-run" not in text


def test_nwipe_hook_hides_engine_and_extra_gettys():
    text = HOOK.read_text(encoding="utf-8")
    assert "/usr/lib/beamo-wipe/nwipe" in text
    assert "ERROR: nwipe is still on PATH" in text
    assert "/usr/sbin/nwipe" in text
    assert "nwipe is not run directly" in text
    assert 'systemctl mask "getty@${tty}.service"' in text or "getty@tty2.service" in text
    assert "NAutoVTs=1" in text
    assert "systemd-networkd.service" in text
    assert "sshd.service" in text


def test_iso_build_uses_https_debian_mirrors():
    text = (ROOT / "packaging/live/inside-docker.sh").read_text(encoding="utf-8")
    assert "https://deb.debian.org/debian/" in text
    assert "https://security.debian.org/" in text
    assert "ip=frommedia" in text
    assert "--bootappend-live-failsafe" in text
    failsafe = [
        line
        for line in text.splitlines()
        if "--bootappend-live-failsafe" in line
    ]
    assert failsafe
    assert "noswap" in failsafe[0]
    assert "ip=frommedia" in failsafe[0]
    assert "nopersistence" in failsafe[0]
    assert "http://deb.debian.org/debian/" not in text
    bootstrap = (ROOT / "packaging/live/config/bootstrap").read_text(encoding="utf-8")
    assert "https://deb.debian.org/debian/" in bootstrap
    assert "https://security.debian.org/" in bootstrap
    assert "http://deb.debian.org/" not in bootstrap
    assert "http://security.debian.org/" not in bootstrap
    binary = (ROOT / "packaging/live/config/binary").read_text(encoding="utf-8")
    assert "ip=frommedia" in binary
    assert 'LB_FIRMWARE_BINARY="false"' in binary
    assert 'LB_FIRMWARE_CHROOT="false"' in binary
    failsafe_cfg = [
        line
        for line in binary.splitlines()
        if line.startswith("LB_BOOTAPPEND_LIVE_FAILSAFE=")
    ]
    assert failsafe_cfg
    assert "noswap" in failsafe_cfg[0]
    assert "ip=frommedia" in failsafe_cfg[0]
    assert "username=root" in failsafe_cfg[0]
    assert "nopersistence" in failsafe_cfg[0]


def test_staged_chroot_package_matches_src():
    src = ROOT / "src/beamo_wipe"
    staged = (
        ROOT
        / "packaging/live/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe"
    )
    if not staged.is_dir():
        return
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".pyc" or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(src)
        other = staged / rel
        assert other.is_file(), f"missing staged copy of {rel}"
        assert other.read_bytes() == path.read_bytes(), f"staged copy drifted: {rel}"


def test_xorg_does_not_force_vesa_on_every_gpu():
    text = (
        ROOT / "packaging/live/config/includes.chroot/etc/X11/xorg.conf.d/10-beamo.conf"
    ).read_text(encoding="utf-8")
    assert 'Driver "vesa"' not in text
    assert "AllowMouseOpenFail" in text
    assert 'Section "Device"' not in text


def test_live_config_xinit_cannot_hijack_kiosk():
    """Debian live-config 0140-xinit writes an infinite startx loop on tty1
    before ~/.profile. Without nox11autologin (and a stub profile.d file),
    the wizard never starts."""
    binary = (ROOT / "packaging/live/config/binary").read_text(encoding="utf-8")
    docker = (ROOT / "packaging/live/inside-docker.sh").read_text(encoding="utf-8")
    live_line = [
        line
        for line in binary.splitlines()
        if line.startswith("LB_BOOTAPPEND_LIVE=") and "FAILSAFE" not in line
    ]
    assert live_line
    assert "nox11autologin" in live_line[0]
    failsafe = [
        line
        for line in binary.splitlines()
        if line.startswith("LB_BOOTAPPEND_LIVE_FAILSAFE=")
    ]
    assert failsafe
    assert "nox11autologin" in failsafe[0]
    assert "nox11autologin" in docker
    stub = (
        ROOT
        / "packaging/live/config/includes.chroot/etc/profile.d/zz-live-config_xinit.sh"
    )
    assert stub.is_file()
    stub_text = stub.read_text(encoding="utf-8")
    assert "while true" not in stub_text
    assert not any(line.strip().startswith("startx") for line in stub_text.splitlines())
    hook = HOOK.read_text(encoding="utf-8")
    assert "0140-xinit" in hook


def test_extra_gettys_are_masked_as_unit_symlinks():
    """systemctl mask is a no-op in the live-build chroot (not PID 1)."""
    text = HOOK.read_text(encoding="utf-8")
    assert 'ln -sfn /dev/null "/etc/systemd/system/getty@${tty}.service"' in text or (
        'ln -sfn /dev/null /etc/systemd/system/getty@${tty}.service' in text
    )
    assert "getty@tty2" in text or "getty@${tty}" in text


def test_kiosk_lock_runs_before_profile_d_xinit():
    lock = (
        ROOT
        / "packaging/live/config/includes.chroot/etc/profile.d/00-beamo-kiosk-lock.sh"
    )
    assert lock.is_file()
    text = lock.read_text(encoding="utf-8")
    assert "set +m" in text
    assert "trap" in text
    assert "TSTP" in text


def test_live_profile_console_if_x_dies_after_socket():
    """Xorg creates X0 before InitOutput. If startx then dies, wait+return
    would skip --console and leave a socket that poisons the next startx."""
    text = PROFILE.read_text(encoding="utf-8")
    start = text.find("beamo_after_startx()")
    assert start != -1
    helper = text[start : text.find("\nbeamo_wipe_ui()")]
    assert "wait" in helper
    assert "rm -f /tmp/.X11-unix/X0" in helper
    assert "beamo-wipe --console" in helper
    idx = text.find('if [ -S /tmp/.X11-unix/X0 ]; then')
    assert idx != -1
    rest = text[idx:]
    end = rest.find("\n      fi")
    assert end != -1
    block = rest[:end]
    assert "beamo_after_startx" in block


def test_kiosk_profile_disables_job_control_suspend():
    text = PROFILE.read_text(encoding="utf-8")
    assert "set +m" in text
    assert "stty susp undef" in text
    assert "stty intr undef" in text
    assert "trap '' TSTP" in text or 'trap "" TSTP' in text
    assert "rm -f /tmp/.X11-unix/X0" in text
    assert "kill -0" in text


def test_live_kiosk_ignores_sigint():
    text = (ROOT / "src/beamo_wipe/app.py").read_text(encoding="utf-8")
    assert "signal.SIGINT" in text
    assert "signal.SIGTSTP" in text

