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
    assert "apple silicon macs are not supported" in blob
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


def test_tk_return_activates_focused_button():
    import inspect

    from beamo_wipe.ui.tk_wizard import _Button

    source = inspect.getsource(_Button.__init__)
    assert "<Return>" in source or "<KP_Enter>" in source
