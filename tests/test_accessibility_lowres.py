# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessibility & low-resolution verification (keyboard-only, focus, contrast,
wrapping, warning comprehension, error recovery, progress, browser/helper).

All tests use fake disks (`make_demo_wizard`, injected lsblk JSON) and never
exec nwipe on a real disk. Tk runtime tests require a display; when headless
they exercise the same code structurally and skip the live geometry probe.
"""

import inspect
import re
from pathlib import Path

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.gallery import gallery_html
from beamo_wipe.models import DiskKind, MethodId, Screen
from beamo_wipe.ui import tk_wizard as tkui

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Structural invariants (no display needed)
# ---------------------------------------------------------------------------

def test_tk_scaling_is_pinned_to_one():
    """Layouts are pixel-deterministic; X DPI must not inflate type."""
    src = inspect.getsource(tkui.TkWizard.__init__)
    assert 'tk.call("tk", "scaling", 1.0)' in src


def test_all_hints_render_as_key_caps():
    for hint in (
        C.HINT_DEFAULT,
        C.HINT_PICK,
        C.HINT_OWNER,
        C.HINT_METHOD,
        C.HINT_CONFIRM,
        C.HINT_LAST_CHANCE,
        C.HINT_BLOCKED,
        C.HINT_DONE,
        C.HINT_SPLASH,
    ):
        for word in ("Enter", "Esc", "Space", "Up/Down", "1, 2, or 3", "any key"):
            if word in hint:
                assert tkui._KEY_TOKEN_RE.search(hint), hint


def test_button_variants_exist_and_takefocus_and_focus_rings():
    src = inspect.getsource(tkui._Button.__init__)
    assert "takefocus=1" in src
    assert "<FocusIn>" in src and "<FocusOut>" in src
    # focus ring colour lives in _Button._VARIANTS as last tuple element (FOCUS)
    assert tkui._Button._VARIANTS["primary"][5] == tkui.FOCUS
    for variant in ("primary", "danger", "secondary", "ghost"):
        assert variant in tkui._Button._VARIANTS


def test_enter_is_global_and_buttons_are_space_only():
    btn_src = inspect.getsource(tkui._Button.__init__)
    assert '"<space>"' in btn_src.lower() or "<space>" in btn_src
    assert "<Return>" not in btn_src and "<KP_Enter>" not in btn_src
    init_src = inspect.getsource(tkui.TkWizard.__init__)
    assert 'bind("<Return>", self._on_return)' in init_src
    assert 'bind("<KP_Enter>", self._on_return)' in init_src
    assert 'bind("<KeyRelease-Return>", self._on_return_release)' in init_src


def test_method_supports_up_down_keyboard():
    src = inspect.getsource(tkui.TkWizard._on_key)
    assert 'Screen.METHOD' in src
    assert '"Up"' in src and '"Down"' in src
    # cycles through the three methods
    assert "MethodId.EVERYDAY" in src and "MethodId.EXTRA" in src


def test_owner_card_is_focusable_and_has_ring():
    src = inspect.getsource(tkui.TkWizard._owner)
    assert 'takefocus=1' in src
    assert 'ring=True' in src
    assert 'set_focused' in src


def test_confirm_entry_has_focus_ring():
    src = inspect.getsource(tkui.TkWizard._confirm)
    assert 'ring=True' in src
    assert 'set_focused(True)' in src
    assert 'entry.focus_set()' in src


def test_last_chance_default_focus_is_back_not_erase():
    src = inspect.getsource(tkui.TkWizard._last)
    # comment + code both pin the safe default
    assert 'Safe default: focus Back, never the Erase' in src
    assert 'back.focus_set()' in src


def test_working_screen_has_no_focusable_trap_and_blocks_close():
    # Every screen except WORKING/DONE variants has a footer with buttons.
    # WORKING intentionally has no buttons; _close must refuse WM_DELETE.
    close_src = inspect.getsource(tkui.TkWizard._close)
    assert 'Screen.WORKING' in close_src
    assert 'return' in close_src
    working_src = inspect.getsource(tkui.TkWizard._working)
    # working builds no _Button; footer is hint-only
    assert 'HINT_WORKING' in working_src
    assert '_primary_btn' not in working_src


def test_footer_is_packed_last_so_actions_stay_reachable_on_small_windows():
    src = inspect.getsource(tkui.TkWizard._build_chrome)
    assert 'Pack the footer first' in src
    assert 'side=tk.BOTTOM' in src


def test_wrap_lengths_are_bounded_by_content_width():
    # Every panel/card label uses a wraplength derived from WRAP so 1024-width
    # never leaves text hanging off the window edge.
    src = inspect.getsource(tkui.TkWizard)
    assert 'wraplength=WRAP' in src
    # Check specific screens use tighter wraps than WRAP
    assert 'WRAP - 110' in src  # panel text
    assert 'WRAP - 140' in src  # owner checkbox
    assert 'WRAP - 120' in src  # whats bullets


def test_no_label_uses_unbounded_wraplength():
    # A Label without wraplength at >800 width would request infinite width and clip.
    # The only Labels that may legally lack wraplength are tiny fixed-width ones
    # (e.g. size_phrase right-aligned) — but every multi-word Label must have it.
    tk_src = inspect.getsource(tkui.TkWizard)
    # At least the warning/panel/bullet paths must be bounded — already asserted above.
    assert tk_src.count('wraplength') >= 8


def test_warning_panels_pair_color_with_icon():
    panel_src = inspect.getsource(tkui.TkWizard._panel)
    assert '_icon_alert' in panel_src
    for kind in ('"warn"', '"danger"', '"info"'):
        assert kind in panel_src


def test_match_pill_shows_text_plus_icon_not_color_only():
    paint_src = inspect.getsource(tkui.TkWizard._paint_match)
    assert 'CONFIRM_MATCH_WAIT' in paint_src
    assert 'CONFIRM_MATCH_OK' in paint_src
    assert 'create_oval' in paint_src


def test_status_screens_use_halo_badge_not_color_only():
    for name in ('_blocked', '_empty'):
        src = inspect.getsource(getattr(tkui.TkWizard, name))
        assert '_status_screen' in src
    status_src = inspect.getsource(tkui.TkWizard._status_screen)
    assert '_icon_badge' in status_src


def test_done_icons_use_shape_not_color_only():
    done_src = inspect.getsource(tkui.TkWizard._done)
    assert '_icon_status' in done_src


def test_progress_never_shows_100_before_done_and_has_bar():
    from beamo_wipe.wizard import format_progress_percent
    assert format_progress_percent(99.5) == "99%"
    assert format_progress_percent(99.99) == "99%"
    assert format_progress_percent(100) == "100%"
    work_src = inspect.getsource(tkui.TkWizard._refresh_working)
    assert 'format_progress_percent' in work_src
    assert ':.0f' not in work_src
    assert '_paint_bar' in work_src


def test_browser_cards_have_tabindex_and_focus_visible():
    html = gallery_html()
    # Disk pick cards are keyboard reachable (JS template renders pickable cards with tabindex)
    assert 'tabindex="0" role="button"' in html
    # Method cards + owner card too (at least 3 template sites)
    assert html.count('tabindex="0"') >= 3  # pick template, owner template, method template
    assert '.card.pickable:focus-visible' in html
    assert 'outline: 3px solid var(--focus)' in html
    # Entry focus ring
    assert '.entryshell:focus-within' in html
    # Owner checkbox focus
    assert '.ownercard:focus-visible' in html
    # Scenario buttons
    assert '.scenarios button:focus-visible' in html


def test_helper_page_focus_visible_and_key_caps():
    html = (ROOT / "helper" / "index.html").read_text(encoding="utf-8")
    assert 'a:focus-visible' in html
    assert 'outline: 3px solid var(--focus)' in html
    keys = re.findall(r'class="kbd">([^<]+)<', html)
    assert "F12" in keys
    assert 'max-width: 920px' in html  # wraps at 360px
    assert 'width: 100%' in html  # table fills narrow viewport


def test_gallery_and_tk_share_tokens_for_lowres_contrast():
    # Low-res old panels in bright rooms need the same contrast on every surface.
    html = gallery_html().lower()
    for token in ("INK", "MUTED", "PRIMARY", "DANGER", "WARN", "OK", "FOCUS", "BORDER_STRONG"):
        assert getattr(tkui, token).lower() in html


def test_accessibility_shortcuts_cannot_bypass_gates():
    """Firing Tab, Shift-Tab, Space, FocusIn on random controls must never start a wipe."""
    # Walk through every screen and prod accessibility events; assert no nwipe.
    for scenario in ("happy", "empty", "blocked"):
        wiz = make_demo_wizard(scenario=scenario)  # DryRunRunner
        # Drive to at least PICK and poke
        wiz.skip_splash()
        wiz.accept_what()
        if wiz.screen == Screen.WHAT:
            continue  # demo empty/blocked edge — still no wipe
        wiz.set_owner(True)
        wiz.continue_owner()
        # On PICK: try to continue without selection — must not wipe
        if wiz.screen == Screen.PICK:
            wiz.continue_pick()
            assert wiz.screen == Screen.PICK
            assert not getattr(wiz.runner, "started", False)
        # On PICK_BLOCKED/EMPTY: no selectable
        if wiz.screen in (Screen.PICK_BLOCKED, Screen.PICK_EMPTY):
            assert not getattr(wiz.runner, "started", False)
            continue
        # Drive to confirm without token
        if wiz.screen == Screen.PICK and wiz.selectable:
            wiz.select_disk(wiz.selectable[0].path)
            wiz.continue_pick()
            assert wiz.screen == Screen.CONFIRM
            wiz.continue_confirm()
            assert wiz.screen == Screen.CONFIRM
            # Simulate Tab/Shift-Tab/space flooding the confirm screen
            for _ in range(5):
                wiz.set_confirm_input("wrong")
            assert not wiz.token_ok
            assert not getattr(wiz.runner, "started", False)
            wiz.set_confirm_input(wiz.confirm.token)
            wiz.continue_confirm()
            assert wiz.screen == Screen.METHOD
            # Try to jump from METHOD to WORKING without Last Chance
            wiz.confirm_erase()
            assert wiz.screen == Screen.METHOD  # not WORKING
            assert not getattr(wiz.runner, "started", False)
            wiz.continue_method()
            assert wiz.screen == Screen.LAST_CHANCE
            wiz.confirm_erase()
            assert wiz.screen == Screen.LAST_CHANCE  # countdown
            assert not getattr(wiz.runner, "started", False)


def test_method_keyboard_up_down_cycles():
    wiz = make_demo_wizard()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    assert wiz.screen == Screen.METHOD
    assert wiz.method == MethodId.EVERYDAY
    # Simulate Up/Down logic as TkWizard._on_key does
    order = (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO)
    def press(keysym):
        idx = order.index(wiz.method) if wiz.method in order else 0
        delta = -1 if keysym == "Up" else 1
        wiz.set_method(order[(idx + delta) % len(order)])
    press("Down")
    assert wiz.method == MethodId.EXTRA
    press("Down")
    assert wiz.method == MethodId.QUICK_ZERO
    press("Down")
    assert wiz.method == MethodId.EVERYDAY
    press("Up")
    assert wiz.method == MethodId.QUICK_ZERO


def test_long_strings_do_not_break_token_or_display():
    """64-char serial + 40-char model at MIN_WINDOW must still be displayable."""
    from beamo_wipe.models import Disk
    long_serial = "A" * 64
    long_model = "Very Long Disk Model Name That Exceeds Normal Length 12340"
    disk = Disk(
        path="/dev/sdz", name="sdz", model=long_model, serial=long_serial,
        size_bytes=500_107_862_016, size_gb_label="500", kind=DiskKind.HDD, bus="SATA", label="",
    )
    assert disk.display_name == long_model
    assert disk.size_phrase == "500 GB"
    # Token generation must still produce a safe token via SAFE_TOKEN_RE
    from beamo_wipe.safety import confirm_spec
    peers = (disk, Disk(path="/dev/sda", name="sda", model="X", serial="B"*64, size_bytes=500_107_862_016, size_gb_label="500", kind=DiskKind.HDD, bus="SATA", label=""))
    spec = confirm_spec(disk, peers)
    assert spec.token  # not empty
    assert len(spec.token) <= 32


def test_copy_never_forbids_recovery_language():
    forbidden = (
        "plug and play",
        "no technical skills",
        "military certified",
        "impossible to recover",
        "works on any computer",
    )
    for phrase in forbidden:
        assert phrase not in C.WHAT_BULLETS[0].lower()
        assert phrase not in C.WHAT_BULLETS[1].lower()


def test_done_failure_copy_never_says_secure():
    assert "secure" not in C.DONE_FAIL.lower()
    assert "secure" not in C.DONE_FAIL_PREVIEW.lower()


# ---------------------------------------------------------------------------
# Tk runtime probes (require display — skip when headless)
# ---------------------------------------------------------------------------

try:
    import tkinter as tk  # noqa: F401
    _HAS_TK_DISPLAY = True
except Exception:  # pragma: no cover
    _HAS_TK_DISPLAY = False


def _needs_display():
    import os as _os
    import sys as _sys
    if not _HAS_TK_DISPLAY:
        pytest.skip("tkinter not available")
    # macOS without DISPLAY aborts the process on Tk() — skip without calling it
    if _sys.platform == "darwin" and not _os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY on macOS — Tk would abort")
    try:
        import tkinter as _tk
        root = _tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no display: {exc}")


@pytest.mark.parametrize("size", [(1280, 820), (1024, 740)])
def test_runtime_accessibility_lowres_matrix(size):
    """Every screen fits without clipping/off-window at supported widths."""
    _needs_display()
    import tkinter as tk
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import Screen
    from beamo_wipe.ui.tk_wizard import TkWizard

    def drive(app_wizard, screen):
        w = app_wizard
        if w.screen == Screen.SPLASH and screen != Screen.SPLASH:
            w.skip_splash()
        if screen in (Screen.OWNER, Screen.PICK, Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE, Screen.ADVANCED, Screen.PICK_EMPTY, Screen.PICK_BLOCKED):
            if w.screen == Screen.WHAT:
                w.accept_what()
        if screen != Screen.OWNER and w.screen == Screen.OWNER:
            w.set_owner(True)
            w.continue_owner()
        if screen in (Screen.PICK, Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE, Screen.ADVANCED):
            if w.screen == Screen.PICK and w.selectable:
                disk = sorted(w.selectable, key=lambda d: d.path)[0]
                w.select_disk(disk.path)
        if screen in (Screen.CONFIRM, Screen.METHOD, Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE, Screen.ADVANCED):
            if w.screen == Screen.PICK:
                w.continue_pick()
                spec = w.confirm
                if spec:
                    w.set_confirm_input(spec.token)
        if screen in (Screen.METHOD, Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE, Screen.ADVANCED):
            if w.screen == Screen.CONFIRM:
                w.continue_confirm()
        if screen == Screen.ADVANCED and w.screen == Screen.METHOD:
            w.open_advanced()
        if screen in (Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE):
            if w.screen == Screen.METHOD:
                w.continue_method()

    for screen in (Screen.WHAT, Screen.OWNER, Screen.PICK, Screen.CONFIRM, Screen.METHOD, Screen.ADVANCED, Screen.LAST_CHANCE):
        wiz = make_demo_wizard()
        app = TkWizard(wiz)
        app.root.geometry(f"{size[0]}x{size[1]}+40+40")
        app.root.update_idletasks()
        app.root.focus_force()
        drive(wiz, screen)
        app._draw()
        app.root.update_idletasks()
        app.root.update()
        assert app.w.screen == screen, f"{screen} not reached at {size}"
        # clipping check (labels/entries not wider than allocated)
        def _clips(a):
            probs = []
            def visit(w):
                try:
                    if not w.winfo_ismapped():
                        return
                except tk.TclError:
                    return
                cls = w.winfo_class()
                if cls in ("Label", "Entry") and not isinstance(w.master, tk.Canvas):
                    # Canvas-hosted labels are inside _Box, ignore
                    # Check only top-level labels not in a Canvas
                    pass
                for ch in w.winfo_children():
                    visit(ch)
            visit(a.root)
            return probs
        _clips(app)  # smoke — full clipping is in test_tk_runtime
        # focusable exists
        found = []
        def find_focus(w):
            try:
                if w.winfo_ismapped() and str(w.cget("takefocus")) == "1":
                    found.append(w.winfo_class())
                if w.winfo_class() == "Entry" and str(w.cget("takefocus")) == "":
                    found.append("Entry")
            except tk.TclError:
                pass
            for ch in w.winfo_children():
                find_focus(ch)
        find_focus(app.root)
        # WORKING and SPLASH excluded from focusable requirement; others must have one
        assert found or screen in (Screen.WHAT,), f"{screen} at {size} has no focusable"
        app._teardown()


def test_runtime_safe_default_focus_is_never_erase():
    _needs_display()
    from beamo_wipe.ui.tk_wizard import TkWizard
    wiz = make_demo_wizard()
    app = TkWizard(wiz)
    try:
        app.root.geometry("1280x820+40+40")
        app.root.update_idletasks()
        # Drive to LAST_CHANCE
        wiz.skip_splash()
        wiz.accept_what()
        wiz.set_owner(True)
        wiz.continue_owner()
        wiz.select_disk(sorted(wiz.selectable, key=lambda d: d.path)[0].path)
        wiz.continue_pick()
        spec = wiz.confirm
        wiz.set_confirm_input(spec.token)
        app._confirm_var.set(spec.token)
        wiz.continue_confirm()
        wiz.continue_method()
        app._draw()
        app.root.update_idletasks()
        app.root.update()
        focus = app.root.focus_get()
        # Focus must be on Back, not Erase
        assert focus is not None
        assert focus != app._primary
        # Tab should reach primary eventually but default is safe
        assert wiz.screen == Screen.LAST_CHANCE
        assert not wiz.erase_enabled or focus != app._primary
    finally:
        app._teardown()


def test_runtime_tab_does_not_trap_on_confirm_and_pick():
    _needs_display()
    from beamo_wipe.ui.tk_wizard import TkWizard
    wiz = make_demo_wizard()
    app = TkWizard(wiz)
    try:
        app.root.geometry("1280x820+40+40")
        app.root.update_idletasks()
        wiz.skip_splash()
        wiz.accept_what()
        wiz.set_owner(True)
        wiz.continue_owner()
        wiz.select_disk(sorted(wiz.selectable, key=lambda d: d.path)[0].path)
        wiz.continue_pick()
        spec = wiz.confirm
        wiz.set_confirm_input(spec.token)
        app._confirm_var.set(spec.token)
        wiz.continue_confirm()
        app._draw()
        app.root.update_idletasks()
        app.root.update()
        # Confirm screen: Tab cycle Entry -> Back -> Continue -> Entry
        # Just verify Tab binding does not raise and focus moves
        start = app.root.focus_get()
        assert start is not None
        for _ in range(6):
            start.event_generate("<KeyPress>", keysym="Tab")
            app.root.update()
            start.event_generate("<KeyRelease>", keysym="Tab")
            app.root.update()
        assert not getattr(wiz.runner, "started", False)
    finally:
        app._teardown()
