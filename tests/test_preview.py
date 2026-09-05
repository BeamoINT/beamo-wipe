# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from beamo_wipe.app import _parser
from beamo_wipe.demo import discovery_for_scenario
from beamo_wipe.gallery import gallery_html, write_gallery
from beamo_wipe.safety import confirm_spec, same_size_conflict

FORBIDDEN = (
    "plug and play",
    "no technical skills",
    "military certified",
    "dod certified",
    "nsa certified",
    "blancco replacement",
    "impossible to recover",
    "we invented",
    "works on any computer",
    "works on any mac",
)


def test_parser_preview_aliases():
    args = _parser().parse_args(["--preview", "--web"])
    assert args.demo
    assert args.web
    args = _parser().parse_args(["--empty"])
    assert args.empty
    args = _parser().parse_args(["--helper"])
    assert args.helper


def test_lsblk_json_forces_dry_run_without_env(monkeypatch):
    from beamo_wipe.app import _build_wizard
    from beamo_wipe.nwipe_runner import DryRunRunner

    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_LIVE", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    fixture = Path(__file__).resolve().parent / "fixtures" / "lsblk_same_size.json"
    args = _parser().parse_args(
        ["--lsblk-json", str(fixture), "--boot-device", "/dev/sdb"]
    )
    wiz = _build_wizard(args)
    assert wiz.dry_run
    assert isinstance(wiz.runner, DryRunRunner)


def test_dry_run_does_not_poweroff_the_machine(monkeypatch):
    """--dry-run / --lsblk-json is not the live USB. Shut down must not poweroff."""
    from beamo_wipe import app as app_mod

    powered = []
    monkeypatch.setattr(app_mod, "_shutdown", lambda: powered.append(True))
    monkeypatch.setattr(app_mod, "running_on_live_usb", lambda: False)
    fixture = Path(__file__).resolve().parent / "fixtures" / "lsblk_same_size.json"

    def fake_ui(wizard, fullscreen=False):
        wizard.wants_shutdown = True
        return 0

    monkeypatch.setattr("beamo_wipe.ui.tk_wizard.run_tk", fake_ui)
    monkeypatch.setattr("beamo_wipe.ui.console_wizard.run_console", fake_ui)
    code = app_mod.main(
        ["--lsblk-json", str(fixture), "--boot-device", "/dev/sdb", "--console"]
    )
    assert code == 0
    assert powered == []


def test_dry_run_env_does_not_build_nwipe_runner(monkeypatch):
    from beamo_wipe.app import _build_wizard
    from beamo_wipe.nwipe_runner import DryRunRunner

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.delenv("BEAMO_WIPE_LIVE", raising=False)
    fixture = Path(__file__).resolve().parent / "fixtures" / "lsblk_same_size.json"
    args = _parser().parse_args(
        ["--lsblk-json", str(fixture), "--boot-device", "/dev/sdb"]
    )
    wiz = _build_wizard(args)
    assert wiz.dry_run
    assert isinstance(wiz.runner, DryRunRunner)


def test_gallery_html_is_preview_only(tmp_path):
    path = write_gallery(tmp_path / "index.html")
    text = path.read_text(encoding="utf-8")
    assert text == gallery_html()
    assert "PREVIEW" in text
    assert "Beamo Wipe" in text
    assert "Not Apple Silicon" in text
    assert "./preview" in text
    blob = text.lower()
    assert "does not erase" in blob or "nothing is erased" in blob
    for phrase in FORBIDDEN:
        assert phrase not in blob


def test_helper_page_does_not_wipe():
    root = Path(__file__).resolve().parents[1]
    text = (root / "helper" / "index.html").read_text(encoding="utf-8")
    blob = text.lower()
    assert "does not erase" in blob
    assert "not apple silicon macs" in blob
    assert "intel mac" in blob
    for phrase in FORBIDDEN:
        assert phrase not in blob


def test_happy_demo_has_same_size_disks_for_serial_confirm():
    result = discovery_for_scenario("happy")
    assert result.boot_identified
    assert same_size_conflict(result.selectable)
    nvme = next(d for d in result.selectable if "nvme" in d.path)
    spec = confirm_spec(nvme, result.selectable)
    assert spec.token == nvme.serial[-4:]


def test_blocked_discovery_lists_no_targets():
    result = discovery_for_scenario("blocked")
    assert not result.boot_identified
    assert result.selectable == ()


def test_empty_discovery_only_boot():
    result = discovery_for_scenario("empty")
    assert result.boot_identified
    assert result.selectable == ()
    assert any(d.is_boot for d in result.disks)


def test_tk_last_chance_renders_safety_error():
    import inspect

    from beamo_wipe.ui.tk_wizard import TkWizard

    source = inspect.getsource(TkWizard._last)
    assert "self.w.error" in source


def test_tk_enter_is_always_the_gated_screen_action():
    """Enter/KP_Enter mean "this screen's primary action", everywhere.

    Buttons activate on Space only, so a focused button can never shadow the
    global Return handler — that handler is where the gates live (owner
    checkbox, token match, countdown). Pinning both halves of the contract.
    """
    import inspect

    from beamo_wipe.ui.tk_wizard import TkWizard, _Button

    button_src = inspect.getsource(_Button.__init__)
    assert '"<space>"' in button_src
    assert "<Return>" not in button_src and "<KP_Enter>" not in button_src

    init_src = inspect.getsource(TkWizard.__init__)
    assert 'bind("<Return>", self._on_return)' in init_src
    assert 'bind("<KP_Enter>", self._on_return)' in init_src
    assert 'bind("<KeyRelease-Return>", self._on_return_release)' in init_src
    assert 'bind("<KeyRelease-KP_Enter>", self._on_return_release)' in init_src
    assert 'bind("<KeyRelease-space>", self._on_space_release)' in init_src


def test_advanced_button_redraws_via_nav():
    import inspect

    from beamo_wipe.ui.tk_wizard import TkWizard

    source = inspect.getsource(TkWizard._method)
    assert "_nav(self.w.open_advanced)" in source


def test_last_chance_hint_does_not_say_enter_continues():
    import inspect

    from beamo_wipe import copy as C
    from beamo_wipe.ui.tk_wizard import TkWizard

    assert "continues" not in C.HINT_LAST_CHANCE.lower()
    assert "erases" in C.HINT_LAST_CHANCE.lower()
    source = inspect.getsource(TkWizard._last)
    assert "HINT_LAST_CHANCE" in source


def test_splash_escape_skips_splash():
    import inspect

    from beamo_wipe.ui.tk_wizard import TkWizard

    source = inspect.getsource(TkWizard._on_escape)
    assert "skip_splash" in source



def test_macos_preview_uses_modern_tk_without_changing_dry_run(tmp_path):
    import os
    import subprocess

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uname = fake_bin / "uname"
    uname.write_text("#!/bin/sh\nprintf 'Darwin\\n'\n")
    uname.chmod(0o755)
    python = fake_bin / "python3.14"
    python.write_text(
        '#!/bin/sh\nif [ "$1" = -c ]; then exit 0; fi\n'
        'printf "dry=%s demo=%s\\n" "$BEAMO_WIPE_DRY_RUN" "$BEAMO_WIPE_DEMO"\n'
        'printf "%s\\n" "$@"\n'
    )
    python.chmod(0o755)
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin"}
    env.pop("BEAMO_WIPE_PREVIEW_PYTHON", None)
    result = subprocess.run([str(root / "preview"), "--console"], env=env,
                            text=True, capture_output=True, check=True)
    assert result.stdout.splitlines() == [
        "dry=1 demo=1", "-m", "beamo_wipe", "--preview", "--console",
    ]
