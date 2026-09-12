# SPDX-License-Identifier: GPL-3.0-or-later
"""Session keyboard layouts. Allowlisted argv only; never a shell string."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
from typing import Mapping, Optional, Sequence, Tuple

# Shipped on the live image: x11-xserver-utils (setxkbmap) and kbd (loadkeys).
# xkb-data and console-setup ship many maps; only these three are offered.
DEFAULT_LAYOUT = "us"

# Binaries we may exec. Names only; resolved with shutil.which at apply time.
_SETXKBMAP = "setxkbmap"
_LOADKEYS = "loadkeys"
_ALLOWED_BINARIES = frozenset({_SETXKBMAP, _LOADKEYS})


@dataclass(frozen=True)
class KeyboardLayout:
    id: str
    title: str
    family: str
    note: str
    xkb_layout: str
    console_map: str
    dead_keys: bool
    digits_need_shift: bool

    @property
    def xkb_argv(self) -> Tuple[str, ...]:
        return (_SETXKBMAP, "-layout", self.xkb_layout, "-option", "")

    @property
    def console_argv(self) -> Tuple[str, ...]:
        return (_LOADKEYS, self.console_map)


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    message: str
    layout_id: str = ""


LAYOUTS: Mapping[str, KeyboardLayout] = {
    "us": KeyboardLayout(
        id="us",
        title="QWERTY (US)",
        family="qwerty",
        note=(
            "Letters and digits match a US QWERTY keyboard. "
            "Numbers do not need Shift."
        ),
        xkb_layout="us",
        console_map="us",
        dead_keys=False,
        digits_need_shift=False,
    ),
    "fr": KeyboardLayout(
        id="fr",
        title="AZERTY (French)",
        family="azerty",
        note=(
            "Letters match a French AZERTY keyboard. Digit keys usually need Shift. "
            "Accented letters use dead keys: press the accent, then the letter."
        ),
        xkb_layout="fr",
        console_map="fr",
        dead_keys=True,
        digits_need_shift=True,
    ),
    "de": KeyboardLayout(
        id="de",
        title="QWERTZ (German)",
        family="qwertz",
        note=(
            "Letters match a German QWERTZ keyboard. Y and Z are swapped from QWERTY. "
            "Some accents use dead keys: press the accent, then the letter."
        ),
        xkb_layout="de",
        console_map="de",
        dead_keys=True,
        digits_need_shift=False,
    ),
}

LAYOUT_ORDER = ("us", "fr", "de")

UNAVAILABLE = "That keyboard layout is not available."
APPLY_FAILED = (
    "Could not change the keyboard layout. The previous layout is still in use."
)
TOOLS_MISSING = (
    "Keyboard layout tools are not available on this computer. "
    "The previous layout is still in use."
)
SESSION_ONLY = (
    "This change lasts until this USB session restarts. "
    "It does not change firmware or BIOS keyboards."
)
LIMITS = (
    "Only US QWERTY, French AZERTY, and German QWERTZ are offered. "
    "This USB does not include other layouts. "
    + SESSION_ONLY
)
CONSOLE_DEAD_KEYS = (
    "On the text console, dead keys may not compose. "
    "Check letters and digits here. Confirm tokens use letters and digits only."
)


def layout_for(layout_id: str) -> Optional[KeyboardLayout]:
    if not isinstance(layout_id, str):
        return None
    return LAYOUTS.get(layout_id)


def is_allowed(layout_id: str) -> bool:
    return layout_for(layout_id) is not None


def _run_allowlisted(argv: Sequence[str]) -> bool:
    if not argv or argv[0] not in _ALLOWED_BINARIES:
        return False
    spec = layout_for(argv[2] if argv[0] == _SETXKBMAP and len(argv) >= 3 else "")
    if argv[0] == _SETXKBMAP:
        if spec is None or tuple(argv) != spec.xkb_argv:
            return False
    elif argv[0] == _LOADKEYS:
        match = next((item for item in LAYOUTS.values() if tuple(argv) == item.console_argv), None)
        if match is None:
            return False
    resolved = shutil.which(argv[0])
    if not resolved:
        return False
    try:
        proc = subprocess.run(
            [resolved, *argv[1:]],
            check=False,
            timeout=3,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def apply_layout(layout_id: str, *, graphical: Optional[bool] = None) -> ApplyResult:
    """Apply one allowlisted layout. Never interpolates untrusted text."""
    spec = layout_for(layout_id)
    if spec is None:
        return ApplyResult(False, UNAVAILABLE, "")
    if graphical is None:
        graphical = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    x_tool = shutil.which(_SETXKBMAP)
    c_tool = shutil.which(_LOADKEYS)
    if graphical and not x_tool:
        return ApplyResult(False, TOOLS_MISSING, spec.id)
    if not graphical and not c_tool:
        return ApplyResult(False, TOOLS_MISSING, spec.id)
    x_ok = True
    if graphical:
        x_ok = _run_allowlisted(spec.xkb_argv)
        if not x_ok:
            return ApplyResult(False, APPLY_FAILED, spec.id)
    c_ok = True
    if c_tool:
        c_ok = _run_allowlisted(spec.console_argv)
        if not graphical and not c_ok:
            return ApplyResult(False, APPLY_FAILED, spec.id)
    if graphical and not c_ok:
        return ApplyResult(
            True,
            "The graphical layout changed. The text console could not be updated. "
            + SESSION_ONLY,
            spec.id,
        )
    return ApplyResult(True, "", spec.id)
