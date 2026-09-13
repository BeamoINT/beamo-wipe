# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessible boot option (#55): a speech entry must reach --accessible.

The BIOS/UEFI menus pass ``beamo.ui=accessible`` on the kernel command line;
the kiosk supervisor translates that into ``beamo-wipe --accessible`` so a
blind owner never has to operate the graphical wizard first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_boot_menus import _bios_menu, _bootappend, _grub_menu

ROOT = Path(__file__).resolve().parents[1]
KIOSK = ROOT / "packaging/live/config/includes.chroot/usr/local/sbin/beamo-wipe-kiosk"
PACKAGE_LIST = ROOT / "packaging/live/config/package-lists/beamo.list.chroot"
QEMU_VERIFY = ROOT / "scripts/qemu-verify.sh"


def _bios_stanzas(menu: str) -> list:
    return re.split(r"(?m)^label ", menu)[1:]


def test_bios_menu_has_exactly_one_speech_stanza():
    menu = _bios_menu()
    speech = [s for s in _bios_stanzas(menu) if s.splitlines()[0].strip().endswith("-speech")]
    assert len(speech) == 1
    stanza = speech[0]
    assert "speech" in stanza.split("menu label", 1)[1].splitlines()[0]
    assert stanza.split("append", 1)[1].strip() == _bootappend("bootappend-live") + " beamo.ui=accessible"
    assert stanza.split("append", 1)[1].strip() != _bootappend("bootappend-live-failsafe")
    assert "Nothing is erased" in stanza


def test_bios_menu_default_and_hotkeys_survive_speech_entry():
    menu = _bios_menu()
    stanzas = _bios_stanzas(menu)
    assert "menu default" in stanzas[0]
    assert all("menu default" not in s for s in stanzas[1:])
    keys = re.findall(r"\^([A-Za-z])", menu)
    assert len(keys) == len(set(keys)) == 3, keys
    assert keys[1] == "s"


def test_uefi_menu_has_exactly_one_speech_entry():
    menu = _grub_menu()
    entries = re.findall(r'menuentry "([^"]+)" --hotkey=([a-z]) \{\n\tlinux\t([^\n]+)', menu)
    speech = [e for e in entries if "speech" in e[0]]
    assert len(speech) == 1, entries
    title, hotkey, linux = speech[0]
    assert hotkey == "s"
    assert linux.endswith("beamo.ui=accessible")
    assert _bootappend("bootappend-live") in linux
    assert _bootappend("bootappend-live-failsafe") not in linux
    titles = re.findall(r'menuentry "([^"]+)"', menu)
    live = [t for t in titles if "Beamo Wipe" in t]
    assert "start the erase guide" in live[0]
    assert "speech" in live[1]
    assert "troubleshoot" in live[2]
    config = (ROOT / "packaging/live/config/bootloaders/grub-pc/config.cfg").read_text()
    assert "set default=0" in config


def _boot_ui_mode(tmp_path: Path, cmdline: str | None) -> subprocess.CompletedProcess:
    source = KIOSK.read_text(encoding="utf-8")
    match = re.search(r"boot_ui_mode\(\) \{\n.*?\n\}\n", source, re.S)
    assert match, "boot_ui_mode function not found in kiosk script"
    if cmdline is None:
        path = tmp_path / "no-such-cmdline"
    else:
        path = tmp_path / "cmdline"
        path.write_text(cmdline, encoding="utf-8")
    return subprocess.run(
        ["sh", "-c", match.group(0) + '\nboot_ui_mode "$1"', "sh", str(path)],
        capture_output=True,
        text=True,
    )


def test_kiosk_boot_ui_mode_recognises_exact_token(tmp_path):
    result = _boot_ui_mode(
        tmp_path, "BOOT_IMAGE=/live/vmlinuz boot=live components beamo.ui=accessible quiet"
    )
    assert result.returncode == 0
    assert result.stdout == "accessible\n"


def test_kiosk_boot_ui_mode_rejects_other_or_partial_tokens(tmp_path):
    for cmdline in (
        "boot=live components",
        "boot=live beamo.ui=accessibleX",
        "boot=live xbeamo.ui=accessible",
        "boot=live beamo.ui=console",
    ):
        result = _boot_ui_mode(tmp_path, cmdline)
        assert result.returncode == 0, cmdline
        assert result.stdout == "", cmdline


def test_kiosk_boot_ui_mode_missing_file_is_empty_success(tmp_path):
    result = _boot_ui_mode(tmp_path, None)
    assert result.returncode == 0
    assert result.stdout == ""


def test_kiosk_script_wires_accessible_mode():
    text = KIOSK.read_text(encoding="utf-8")
    for needle in (
        "--accessible",
        "beamo.ui=accessible",
        "Beamo Wipe is starting with speech. Please wait. Nothing is erased yet.",
        "The spoken screen could not start. A keyboard text screen is showing instead. Speech is not available on it.",
        "espeak-ng",
        "startx /usr/local/bin/beamo-wipe",
        "BEAMO_WIPE_GRAPHICAL_UNAVAILABLE=1 /usr/local/bin/beamo-wipe --console",
    ):
        assert needle in text, needle


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_kiosk_script_is_shellcheck_clean():
    result = subprocess.run(
        ["shellcheck", "-s", "sh", str(KIOSK)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout


def test_package_list_installs_espeak_ng():
    text = PACKAGE_LIST.read_text(encoding="utf-8")
    assert re.search(r"(?m)^espeak-ng$", text)


def test_main_starts_reader_before_startup_stages(monkeypatch):
    import beamo_wipe.app as app
    from beamo_wipe.ui import accessible_wizard

    monkeypatch.setattr(app, "running_on_live_usb", lambda: True)
    events = []
    handle = object()
    monkeypatch.setattr(
        accessible_wizard, "start_live_reader", lambda: events.append("start") or handle
    )
    monkeypatch.setattr(
        accessible_wizard,
        "stop_live_reader",
        lambda reader: events.append(("stop", reader)),
    )
    monkeypatch.setattr(
        app,
        "_build_wizard_with_accessible_stages",
        lambda args, fullscreen: events.append("build") or None,
    )
    assert app._main(["--accessible", "--fullscreen"]) == 0
    assert events.index("start") < events.index("build")
    assert events.count(("stop", handle)) == 1


def test_main_passes_reader_to_run_accessible_and_stops_once(monkeypatch):
    import beamo_wipe.app as app
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.ui import accessible_wizard

    monkeypatch.setattr(app, "running_on_live_usb", lambda: True)
    events = []
    handle = object()
    monkeypatch.setattr(accessible_wizard, "start_live_reader", lambda: handle)
    monkeypatch.setattr(
        accessible_wizard,
        "stop_live_reader",
        lambda reader: events.append(("stop", reader)),
    )
    monkeypatch.setattr(
        app,
        "_build_wizard_with_accessible_stages",
        lambda args, fullscreen: make_demo_wizard(),
    )
    seen = []

    def fake_run(wizard, fullscreen=False, reader=None):
        seen.append(reader)
        return 0

    monkeypatch.setattr(accessible_wizard, "run_accessible", fake_run)
    assert app._main(["--accessible", "--fullscreen"]) == 0
    assert seen == [handle]
    assert events == [("stop", handle)]


def test_main_console_starts_no_reader(monkeypatch):
    import beamo_wipe.app as app
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.ui import accessible_wizard

    calls = []
    monkeypatch.setattr(
        accessible_wizard,
        "start_live_reader",
        lambda: calls.append("start") or object(),
    )
    monkeypatch.setattr(
        accessible_wizard,
        "stop_live_reader",
        lambda reader: calls.append(("stop", reader)),
    )
    monkeypatch.setattr(
        app, "_build_wizard_with_console_stages", lambda args: make_demo_wizard()
    )
    import beamo_wipe.ui.console_wizard as console_wizard

    monkeypatch.setattr(console_wizard, "run_console", lambda wizard: 0)
    assert app._main(["--console"]) == 0
    assert calls == []


def test_main_demo_accessible_starts_no_reader(monkeypatch):
    import beamo_wipe.app as app
    from beamo_wipe.ui import accessible_wizard

    calls = []
    monkeypatch.setattr(
        accessible_wizard,
        "start_live_reader",
        lambda: calls.append("start") or object(),
    )
    monkeypatch.setattr(
        accessible_wizard,
        "stop_live_reader",
        lambda reader: calls.append(("stop", reader)),
    )
    seen = []
    monkeypatch.setattr(
        accessible_wizard,
        "run_accessible",
        lambda wizard, fullscreen=False, reader=None: seen.append(reader) or 0,
    )
    assert app._main(["--demo", "--accessible"]) == 0
    assert calls == []


def test_start_live_reader_failure_paths(monkeypatch):
    from beamo_wipe.ui import accessible_wizard as module

    monkeypatch.setattr("beamo_wipe.safety.running_on_live_usb", lambda: True)
    handle = object()

    def raise_pulse(argv, **kw):
        raise subprocess.CalledProcessError(1, "pulseaudio")

    monkeypatch.setattr(module.subprocess, "run", raise_pulse)
    monkeypatch.setattr(module.subprocess, "Popen", lambda argv, **kw: handle)
    assert module.start_live_reader() is handle

    def missing_orca(argv, **kw):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kw: None)
    monkeypatch.setattr(module.subprocess, "Popen", missing_orca)
    assert module.start_live_reader() is None


def test_start_live_reader_off_live_usb_starts_nothing(monkeypatch):
    from beamo_wipe.ui import accessible_wizard as module

    monkeypatch.setattr("beamo_wipe.safety.running_on_live_usb", lambda: False)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **kw: calls.append(a))
    assert module.start_live_reader() is None
    assert calls == []


def test_run_accessible_does_not_stop_a_reader_it_does_not_own(monkeypatch):
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.ui import accessible_wizard as module

    monkeypatch.setattr("beamo_wipe.safety.running_on_live_usb", lambda: True)
    calls = []

    class Reader:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

    class Window:
        def __init__(self, *args):
            pass

        def run(self):
            return 0

    monkeypatch.setattr(module, "AccessibleWizard", Window)
    reader = Reader()
    assert module.run_accessible(make_demo_wizard(), reader=reader) == 0
    assert calls == []


def test_safety_unchanged_by_ui_token():
    import beamo_wipe.safety as safety
    from beamo_wipe.app import _parser, apply_live_session_overrides
    import beamo_wipe.app as app
    from beamo_wipe.discover import identify_boot_path

    assert safety.is_live_environment(
        cmdline="boot=live components beamo.ui=accessible",
        live_medium_mounted=True,
    ) is True

    payload = json.loads(
        (ROOT / "src/beamo_wipe/demo_lsblk.json").read_text(encoding="utf-8")
    )
    base = identify_boot_path(
        payload["blockdevices"], cmdline="boot=live components"
    )
    with_token = identify_boot_path(
        payload["blockdevices"], cmdline="boot=live components beamo.ui=accessible"
    )
    assert with_token == base

    import unittest.mock as mock

    args = _parser().parse_args(["--accessible"])
    with mock.patch.object(app, "running_on_live_usb", lambda: True):
        apply_live_session_overrides(args)
    assert args.accessible is True


def _qemu_gate() -> str:
    source = QEMU_VERIFY.read_text()
    return "BIOS_LIVE=" + source.split("BIOS_LIVE=", 1)[1].split('if find "$SQUASH_MOUNT', 1)[0]


def _run_gate(tmp_path: Path, bios: str, grub: str) -> subprocess.CompletedProcess:
    iso = tmp_path / "iso"
    (iso / "isolinux").mkdir(parents=True)
    (iso / "boot/grub").mkdir(parents=True)
    (iso / "isolinux/live.cfg").write_text(bios)
    (iso / "boot/grub/grub.cfg").write_text(grub)
    return subprocess.run(
        ["bash", "-ceu", _qemu_gate()],
        capture_output=True,
        text=True,
        env=dict(os.environ, ISO_MOUNT=str(iso)),
    )


def test_built_menu_verifier_requires_the_speech_entries(tmp_path):
    assert _run_gate(tmp_path / "ok", _bios_menu(), _grub_menu()).returncode == 0

    menu = _bios_menu()
    no_speech = menu.split("label live-amd64-speech")[0] + "label live-amd64-failsafe" + menu.split(
        "label live-amd64-failsafe", 1
    )[1]
    failed = _run_gate(tmp_path / "bios", no_speech, _grub_menu())
    assert failed.returncode != 0
    assert "lost the speech entry" in failed.stderr

    grub_no_token = _grub_menu().replace(" beamo.ui=accessible", "")
    failed = _run_gate(tmp_path / "uefi", _bios_menu(), grub_no_token)
    assert failed.returncode != 0
    assert "ISO UEFI speech entry lost beamo.ui=accessible" in failed.stderr


def test_docs_teach_the_speech_entry():
    boot_card = (ROOT / "docs/boot-card.md").read_text(encoding="utf-8")
    helper = (ROOT / "helper/index.html").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    reader_doc = (ROOT / "docs/screen-reader.md").read_text(encoding="utf-8")
    for text in (boot_card, helper, readme, reader_doc):
        assert re.search(r"speech", text, re.I)
    assert "**S**" in boot_card
    assert '<span class="kbd">S</span>' in helper
    assert "**S**" in readme
    assert "**S**" in reader_doc
