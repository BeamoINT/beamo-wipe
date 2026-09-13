# SPDX-License-Identifier: GPL-3.0-or-later
"""Boot menus (#54): BIOS and UEFI entries carry Beamo Wipe identity.

Baseline (verified against live-build upstream `binary_syslinux` and
`binary_grub_cfg` plus the stock templates): live-build generates
`Live system (@FLAVOUR@)` / `Live system (... fail-safe mode)` entries
with a `Boot menu` title and no product identity or erasure statement.
The repo overrides only timeouts/defaults. These tests simulate
live-build's documented placeholder substitution over the repo override
files and pin the branded result; the built-ISO half of the gate lives
in scripts/qemu-verify.sh (cloud/VM only, shellchecked here).
"""

from __future__ import annotations

import re
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "packaging/live/config/bootloaders"
ISOLINUX = BOOT / "isolinux"
GRUB_PC = BOOT / "grub-pc"

PLACEHOLDER = re.compile(r"@[A-Z_]+@")


def _bootappend(name: str) -> str:
    """The exact kernel command line live-build is configured with."""
    text = (ROOT / "packaging/live/inside-docker.sh").read_text(encoding="utf-8")
    marker = f"--{name} \""
    (line,) = [ln for ln in text.splitlines() if marker in ln]
    return line.split(marker, 1)[1].rsplit('"', 1)[0]


def _subst(text: str, mapping: dict) -> str:
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


def _bios_menu() -> str:
    raw = (ISOLINUX / "live.cfg.in").read_text(encoding="utf-8")
    return _subst(
        raw,
        {
            "@FLAVOUR@": "amd64",
            "@LINUX@": "/live/vmlinuz",
            "@INITRD@": "/live/initrd.img",
            "@APPEND_LIVE@": _bootappend("bootappend-live"),
            "@APPEND_LIVE_FAILSAFE@": _bootappend("bootappend-live-failsafe"),
        },
    )


def _grub_menu() -> str:
    raw = (GRUB_PC / "grub.cfg").read_text(encoding="utf-8")
    live = _bootappend("bootappend-live")
    return _subst(
        raw,
        {
            "@KERNEL_LIVE@": "/live/vmlinuz-6.1.0-30-amd64",
            "@INITRD_LIVE@": "/live/initrd.img-6.1.0-30-amd64",
            "@APPEND_LIVE@": live,
            "@LB_BOOTAPPEND_LIVE_FAILSAFE@": _bootappend("bootappend-live-failsafe"),
            "@APPEND_VERIFY_CHECKSUMS@": f"{live} verify-checksums",
            "@ENABLE_INSTALL_MENU@": "false",
            "@ENABLE_MEMTEST@": "false",
            "@ENABLE_VERIFY_CHECKSUMS@": "true",
        },
    )


def _hotkeys(text: str, pattern: str) -> list:
    return re.findall(pattern, text)


def test_bios_menu_entries_carry_product_identity():
    menu = _bios_menu()
    labels = re.findall(r"(?m)^\tmenu label (.+)$", menu)
    assert len(labels) == 3, labels
    assert all("Beamo Wipe" in label for label in labels), labels
    assert "Debian" not in menu and "Live system (" not in menu


def test_bios_menu_keeps_default_and_recovery_entry():
    menu = _bios_menu()
    stanzas = re.split(r"(?m)^label ", menu)
    assert len(stanzas) == 4  # leading text plus normal, speech, failsafe
    assert "menu default" in stanzas[1]
    assert "menu default" not in stanzas[2]
    assert "menu default" not in stanzas[3]
    assert "failsafe" in stanzas[3].splitlines()[0]
    assert "noswap" in stanzas[3]  # real failsafe args, not the normal line


def test_bios_menu_states_booting_erases_nothing():
    menu = _bios_menu()
    helps = re.findall(r"(?m)^\ttext help\n(.+)\n\tendtext$", menu)
    assert len(helps) == 3, helps
    assert all("Nothing is erased" in line for line in helps), helps


def test_bios_boot_entries_use_inline_help_not_help_file_actions():
    # MENU HELP changes the entry into a help-file action. TEXT HELP adds
    # inline documentation while preserving the Linux boot action.
    # https://kernel.googlesource.com/pub/scm/boot/syslinux/syslinux/+/master/doc/menu.txt
    menu = _bios_menu()
    assert not re.search(r"(?im)^\s*menu\s+help\b", menu)
    for stanza in re.split(r"(?m)^label ", menu)[1:]:
        assert stanza.count("\ttext help\n") == 1
        assert stanza.count("\tendtext\n") == 1
        assert "\tlinux /live/vmlinuz\n" in stanza
        assert "\tinitrd /live/initrd.img\n" in stanza


def test_bios_menu_has_unique_hotkeys_and_no_placeholders_left():
    raw = (ISOLINUX / "live.cfg.in").read_text(encoding="utf-8")
    assert "@APPEND_LIVE@" in raw and "@APPEND_LIVE_FAILSAFE@" in raw
    assert "@LINUX@" in raw and "@INITRD_LIVE@" not in raw
    menu = _bios_menu()
    assert PLACEHOLDER.search(menu) is None
    keys = _hotkeys(menu, r"\^([A-Za-z])")
    assert len(keys) == 3 and len(set(keys)) == 3, keys


def test_bios_menu_title_and_wiring_preserved():
    title = (ISOLINUX / "menu.cfg").read_text(encoding="utf-8")
    assert "menu title Beamo Wipe" in title
    assert "include live.cfg" in title
    # live-build deletes this line when no installer is configured; the
    # exact placeholder must survive so the sed in binary_syslinux matches.
    assert "@OPTIONAL_INSTALLER_INCLUDE@" in title
    assert "menu begin utilities" in title


def test_uefi_menu_entries_carry_product_identity():
    menu = _grub_menu()
    titles = re.findall(r'menuentry "([^"]+)"', menu)
    live = [t for t in titles if "Beamo Wipe" in t]
    assert len(live) == 3, titles
    assert any("troubleshoot" in t for t in live), titles


def test_uefi_menu_states_booting_erases_nothing():
    menu = _grub_menu()
    titles = re.findall(r'menuentry "([^"]+)"', menu)
    live = [t for t in titles if "Beamo Wipe" in t]
    assert all("nothing is erased yet" in t for t in live), live


def test_uefi_menu_structure_survives_substitution():
    raw = (GRUB_PC / "grub.cfg").read_text(encoding="utf-8")
    assert "@KERNEL_LIVE@" in raw and "@INITRD_LIVE@" in raw
    assert "@APPEND_LIVE@" in raw and "@LB_BOOTAPPEND_LIVE_FAILSAFE@" in raw
    assert "@LINUX_LIVE@" not in raw  # explicit entries, nothing generated
    assert "//" not in raw  # live-build collapses // in every .cfg
    assert not re.search(r"(?m) +$", raw)  # and strips trailing blanks
    menu = _grub_menu()
    assert PLACEHOLDER.search(menu) is None
    assert menu.count("{") == menu.count("}")
    keys = _hotkeys(menu, r"--hotkey=([A-Za-z])")
    assert len(keys) >= 2 and len(set(keys)) == len(keys), keys


def test_uefi_recovery_and_utility_blocks_preserved():
    menu = _grub_menu()
    assert "noswap" in menu  # failsafe kernel line keeps safe args
    assert "UEFI Firmware Settings" in menu
    assert "Verify integrity of the boot medium" in menu
    assert "install_start.cfg" in menu  # inert without an installer


def test_built_iso_menu_gate_exists_in_qemu_verify():
    text = (ROOT / "scripts/qemu-verify.sh").read_text(encoding="utf-8")
    assert "live.cfg" in text and "grub.cfg" in text
    assert "Beamo Wipe" in text


def test_built_menu_verifier_accepts_syslinux_hotkey_markup(tmp_path):
    iso = tmp_path / "iso"
    (iso / "isolinux").mkdir(parents=True)
    (iso / "boot/grub").mkdir(parents=True)
    (iso / "isolinux/live.cfg").write_text(_bios_menu())
    (iso / "boot/grub/grub.cfg").write_text(_grub_menu())
    source = (ROOT / "scripts/qemu-verify.sh").read_text()
    gate = 'BIOS_LIVE=' + source.split('BIOS_LIVE=', 1)[1].split('if find "$SQUASH_MOUNT', 1)[0]
    result = subprocess.run(["bash", "-ceu", gate], capture_output=True, text=True,
                            env=dict(os.environ, ISO_MOUNT=str(iso)))
    assert result.returncode == 0, result.stdout + result.stderr
    (iso / "isolinux/live.cfg").write_text(_bios_menu().split('label live-amd64-failsafe')[0])
    missing = subprocess.run(["bash", "-ceu", gate], capture_output=True, text=True,
                             env=dict(os.environ, ISO_MOUNT=str(iso)))
    assert missing.returncode != 0
    assert "lost the troubleshooting entry" in missing.stderr
