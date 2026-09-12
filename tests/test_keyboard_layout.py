# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard layout selector. Fake devices only; apply is injected."""

from __future__ import annotations

from pathlib import Path

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.diagnostic_report import create_report
from beamo_wipe.evidence import build_evidence
from beamo_wipe.keyboard import (
    APPLY_FAILED,
    DEFAULT_LAYOUT,
    LAYOUTS,
    TOOLS_MISSING,
    UNAVAILABLE,
    apply_layout,
    is_allowed,
)
from beamo_wipe.models import MethodId, Screen, WipeResult
from beamo_wipe.ui import console_wizard as console


ROOT = Path(__file__).resolve().parents[1]
KIOSK = ROOT / "packaging/live/config/includes.chroot/usr/local/sbin/beamo-wipe-kiosk"
SERVICE = ROOT / "packaging/live/config/includes.chroot/etc/systemd/system/beamo-wipe-kiosk.service"
XORG = ROOT / "packaging/live/config/includes.chroot/etc/X11/xorg.conf.d/10-beamo.conf"
CONSOLE_KEYBOARD = ROOT / "packaging/live/config/includes.chroot/etc/default/keyboard"


class _Apply:
    def __init__(self, *, ok=True, message="", fail_ids=()):
        self.ok = ok
        self.message = message
        self.fail_ids = set(fail_ids)
        self.calls = []

    def __call__(self, layout_id, **_kw):
        from beamo_wipe.keyboard import ApplyResult

        self.calls.append(layout_id)
        if layout_id in self.fail_ids or not self.ok:
            return ApplyResult(False, self.message or APPLY_FAILED, layout_id)
        return ApplyResult(True, self.message, layout_id)


def _wiz(applier=None):
    wiz = make_demo_wizard()
    wiz._apply_keyboard = applier or _Apply()
    return wiz


def _authorized(wiz):
    wiz.skip_intro()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    disk = sorted(wiz.selectable, key=lambda item: item.path)[0]
    wiz.select_disk(disk.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.owner_ok
    assert wiz.confirm_input
    assert wiz.selected is not None


def test_allowlist_is_qwerty_azerty_qwertz():
    assert set(LAYOUTS) == {"us", "fr", "de"}
    assert LAYOUTS["us"].family == "qwerty"
    assert LAYOUTS["fr"].family == "azerty"
    assert LAYOUTS["de"].family == "qwertz"
    assert LAYOUTS["fr"].dead_keys and LAYOUTS["de"].dead_keys
    assert not LAYOUTS["us"].dead_keys
    assert LAYOUTS["fr"].digits_need_shift
    assert not is_allowed("dvorak")
    assert not is_allowed("us;fr")
    assert not is_allowed("us\nfr")


def test_apply_rejects_non_allowlisted_argv(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("beamo_wipe.keyboard.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(argv, **kw):
        raise AssertionError(argv)

    monkeypatch.setattr("beamo_wipe.keyboard.subprocess.run", fake_run)
    result = apply_layout("dvorak", graphical=True)
    assert not result.ok
    assert result.message == UNAVAILABLE


@pytest.mark.parametrize("layout_id", ["us", "fr", "de"])
def test_apply_uses_exact_allowlisted_argv(monkeypatch, layout_id):
    seen = []

    def which(name):
        return f"/usr/bin/{name}"

    def fake_run(argv, **kw):
        seen.append(tuple(argv))
        assert kw.get("shell") is not True
        class Result:
            returncode = 0
        return Result()

    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("beamo_wipe.keyboard.shutil.which", which)
    monkeypatch.setattr("beamo_wipe.keyboard.subprocess.run", fake_run)
    result = apply_layout(layout_id, graphical=True)
    assert result.ok
    spec = LAYOUTS[layout_id]
    assert ("/usr/bin/setxkbmap", *spec.xkb_argv[1:]) in seen
    assert ("/usr/bin/loadkeys", spec.console_map) in seen


def test_missing_tools_are_visible(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("beamo_wipe.keyboard.shutil.which", lambda _name: None)
    result = apply_layout("fr", graphical=True)
    assert not result.ok
    assert result.message == TOOLS_MISSING


def test_failed_apply_does_not_change_layout_or_clear_auth():
    applier = _Apply(ok=False, message=APPLY_FAILED)
    wiz = _wiz(applier)
    _authorized(wiz)
    assert not wiz.set_keyboard_layout("fr")
    assert wiz.keyboard_layout == "us"
    assert wiz.owner_ok
    assert wiz.selected is not None
    assert wiz.confirm_input
    assert wiz.screen == Screen.LAST_CHANCE
    assert APPLY_FAILED in (wiz.error or "")
    assert applier.calls == ["fr"]


@pytest.mark.parametrize("layout_id", ["fr", "de"])
def test_successful_layout_change_clears_full_confirmation_flow(layout_id):
    wiz = _wiz()
    _authorized(wiz)
    assert wiz.set_keyboard_layout(layout_id)
    assert wiz.keyboard_layout == layout_id
    assert not wiz.owner_ok
    assert wiz.confirm_input == ""
    assert wiz.selected is None
    assert wiz._authorized_operation is None
    assert wiz._erase_until is None
    assert wiz.screen == Screen.WHAT
    wiz.accept_what()
    assert wiz.screen == Screen.OWNER
    wiz.continue_owner()
    assert wiz.screen == Screen.OWNER


def test_repeated_same_layout_does_not_invalidate():
    wiz = _wiz()
    _authorized(wiz)
    assert wiz.set_keyboard_layout("us")
    assert wiz.owner_ok
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.set_keyboard_layout("fr")
    assert wiz.set_keyboard_layout("de")
    assert wiz.set_keyboard_layout("us")
    assert wiz.keyboard_layout == "us"
    assert not wiz.owner_ok
    assert wiz.screen == Screen.WHAT


def test_splash_then_keyboard_then_what():
    wiz = _wiz()
    assert wiz.screen == Screen.SPLASH
    assert wiz.keyboard_layout == DEFAULT_LAYOUT
    wiz.skip_splash()
    assert wiz.screen == Screen.KEYBOARD
    wiz.set_keyboard_layout("fr")
    wiz.set_typing_check("azerty 123")
    assert wiz.typing_check == "azerty 123"
    wiz.accept_keyboard()
    assert wiz.screen == Screen.WHAT
    assert wiz.typing_check == ""
    assert wiz.keyboard_layout == "fr"


def test_typing_check_never_enters_evidence_or_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz = _wiz()
    wiz.skip_splash()
    secret = "édeadkey-SECRET-99"
    wiz.set_typing_check(secret)
    assert secret in wiz.typing_check
    disk = sorted(wiz.selectable, key=lambda item: item.path)[0]
    result = WipeResult(True, 0, "completed", str(tmp_path / "nwipe.log"), "completed")
    ev = build_evidence(
        disk=disk,
        discovery=wiz.discovery,
        method=MethodId.EVERYDAY,
        request=None,
        result=result,
        started_at_wall="",
        ended_at_wall="",
        started_mono=0,
        ended_mono=1,
        argv=[],
        log_text="",
        interrupted=False,
        cancelled=False,
    )
    blob = str(ev)
    assert secret not in blob
    assert "édeadkey" not in blob
    report = create_report("discovery_failed", wiz.discovery, ui="console", session_started=0)
    assert secret.encode() not in report
    # Even a failed layout apply may log the allowlisted id, never the check text.
    wiz._apply_keyboard = _Apply(ok=False)
    wiz.set_keyboard_layout("fr")
    for path in tmp_path.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert secret not in text


def test_unavailable_layout_is_visible_and_rejected():
    wiz = _wiz()
    wiz.skip_splash()
    assert not wiz.set_keyboard_layout("dvorak")
    assert wiz.keyboard_layout == "us"
    assert UNAVAILABLE in (wiz.error or "")


def test_open_keyboard_from_later_screen_and_back_without_change():
    wiz = _wiz()
    _authorized(wiz)
    wiz.open_keyboard()
    assert wiz.screen == Screen.KEYBOARD
    wiz.set_typing_check("hello")
    wiz.back()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.owner_ok
    assert wiz.selected is not None
    assert wiz.typing_check == ""


def test_console_keyboard_and_plain_check_field(monkeypatch, capsys):
    wiz = _wiz()
    wiz.skip_splash()
    answers = iter(["2", "azerty", ""])

    def fake_input(_prompt=""):
        try:
            return next(answers)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wiz)
    text = capsys.readouterr().out
    assert C.TITLE_KEYBOARD in text
    assert "AZERTY" in text
    assert "QWERTZ" in text
    assert "dead keys" in text.lower()
    assert wiz.keyboard_layout == "fr"
    assert wiz.screen == Screen.WHAT
    assert "azerty" not in (wiz.typing_check or "")


def test_curses_keyboard_keeps_check_and_actions_on_80x24(monkeypatch):
    wiz = _wiz()
    wiz.skip_splash()
    rows = {}

    class Terminal:
        def getmaxyx(self):
            return 24, 80

        def addstr(self, y, x, text, attr=0):
            assert 0 <= y < 24
            assert len(text) < 80
            rows[y] = text

        def getch(self):
            wiz.wants_shutdown = True
            return -1

        def __getattr__(self, name):
            return lambda *a, **k: None

    monkeypatch.setattr(console.curses, "curs_set", lambda *a, **k: None)
    monkeypatch.setattr(console.curses, "use_default_colors", lambda *a, **k: None)
    console._loop(Terminal(), wiz)
    shown = " ".join(rows[y] for y in sorted(rows))
    assert C.TITLE_KEYBOARD.split()[0] in shown or "Check your keyboard" in shown or "QWERTY" in shown
    assert "QWERTY" in shown and "AZERTY" in shown and "QWERTZ" in shown
    assert "Enter continues" in shown or "1/2/3" in shown
    assert max(rows) < 24


def test_rendered_keyboard_screen_keeps_check_field_and_layouts(monkeypatch):
    from test_adaptive_layout import _texts, _buttons
    from test_tk_runtime import _needs_display
    from beamo_wipe.ui.tk_wizard import TkWizard

    _needs_display()
    wiz = _wiz()
    app = TkWizard(wiz)
    try:
        app.root.geometry("1280x820+40+40")
        wiz.skip_splash()
        app._draw()
        app.root.update_idletasks()
        app.root.update()
        shown = _texts(app.root)
        assert C.TITLE_KEYBOARD in shown
        assert "QWERTY" in shown and "AZERTY" in shown and "QWERTZ" in shown
        assert C.KEYBOARD_CHECK_LABEL in shown
        labels = [b.itemcget(b._label, "text") for b in _buttons(app)]
        assert C.BTN_CONTINUE in labels
        wiz.set_keyboard_layout("fr")
        app._draw()
        app.root.update()
        assert wiz.keyboard_layout == "fr"
        wiz.set_typing_check("azé 12")
        assert "azé 12" == wiz.typing_check
        wiz.accept_keyboard()
        app._draw()
        app.root.update()
        assert wiz.screen == Screen.WHAT
        assert wiz.typing_check == ""
    finally:
        app._teardown()


def test_kiosk_restart_returns_to_shipped_us_qwerty():
    service = SERVICE.read_text(encoding="utf-8")
    kiosk = KIOSK.read_text(encoding="utf-8")
    xorg = XORG.read_text(encoding="utf-8")
    default = CONSOLE_KEYBOARD.read_text(encoding="utf-8")
    assert "Restart=always" in service
    assert "setxkbmap" not in kiosk
    assert "loadkeys" not in kiosk
    assert 'Option "XkbLayout" "us"' in xorg
    assert "XKBLAYOUT=\"us\"" in default
    wiz = _wiz()
    wiz.skip_splash()
    wiz.set_keyboard_layout("fr")
    wiz.set_typing_check("secret-check")
    wiz.reset_for_preview()
    assert wiz.screen == Screen.SPLASH
    assert wiz.keyboard_layout == DEFAULT_LAYOUT
    assert wiz.typing_check == ""
    assert not wiz.owner_ok
    assert wiz.confirm_input == ""
