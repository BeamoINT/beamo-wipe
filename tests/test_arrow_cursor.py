# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #85: the live UI shows a familiar arrow cursor over ordinary
content instead of the X-server X cursor.

Baseline (fails before the fix, at 60d827a + #83/#84 WIP): the Tk root
toplevel sets no cursor, so app content inherits the X default on the
bare startx kiosk; the live launcher never sets the X root cursor.
See docs/evidence/arrow-cursor-85/README.md.
"""

import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "packaging/live/config/includes.chroot/usr/local/bin/beamo-wipe"
PACKAGES = ROOT / "packaging/live/config/package-lists/beamo.list.chroot"

CORE_TK_CURSORS = {"arrow", "hand2", "xterm"}


def test_live_launcher_sets_arrow_root_cursor():
    """Would fail while the launcher left the X root cursor unset."""
    text = LAUNCHER.read_text(encoding="utf-8")
    guard = 'if [ -n "${DISPLAY:-}" ]; then'
    assert guard in text
    assert "xsetroot -cursor_name left_ptr" in text
    line = next(
        ln for ln in text.splitlines() if "xsetroot -cursor_name left_ptr" in ln
    )
    assert "2>/dev/null" in line and "|| true" in line
    assert text.index(guard) < text.index(line) < text.index("exec python3")


def test_live_packages_provide_xsetroot_without_theme():
    """xsetroot ships in x11-xserver-utils; no cursor theme is needed."""
    names = {
        line.strip()
        for line in PACKAGES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert "x11-xserver-utils" in names
    for theme in ("dmz-cursor-theme", "xcursor-themes", "breeze-cursor-theme"):
        assert theme not in names


def test_tk_root_defaults_to_arrow():
    """Would fail while ordinary content inherited the X cursor."""
    from beamo_wipe.ui import tk_wizard as tk_mod

    source = inspect.getsource(tk_mod.TkWizard.__init__)
    assert 'cursor="arrow"' in source


def test_tk_text_surfaces_keep_xterm():
    """Would fail while entries/readers depended on an unset default."""
    from beamo_wipe.ui import tk_wizard as tk_mod

    assert 'cursor="xterm"' in inspect.getsource(tk_mod.TkWizard._reader)
    init = inspect.getsource(tk_mod.TkWizard._confirm)
    assert 'cursor="xterm"' in init
    keyboard = inspect.getsource(tk_mod.TkWizard._keyboard)
    assert 'cursor="xterm"' in keyboard


def test_only_core_cursor_names_are_used():
    """Guards: no theme-dependent or X-shaped cursor names anywhere."""
    text = (ROOT / "src/beamo_wipe/ui/tk_wizard.py").read_text(encoding="utf-8")
    names = set(re.findall(r'cursor="([^"]+)"', text))
    assert names <= CORE_TK_CURSORS, names
    assert "X_cursor" not in text
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "X_cursor" not in launcher


def effective_cursor(widget) -> str:
    """First non-empty cursor up the widget ancestry (Tk inheritance)."""
    node = widget
    while node is not None:
        try:
            value = node.cget("cursor")
        except Exception:
            value = ""
        if value:
            return value
        node = getattr(node, "master", None)
    return ""
