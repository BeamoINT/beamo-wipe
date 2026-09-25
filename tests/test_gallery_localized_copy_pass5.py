# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview help and stop screens should honor the selected language."""

from __future__ import annotations

import json
import re

import pytest

from beamo_wipe import lang
from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize("language", ("fr", "de"))
def test_help_and_stop_screen_copy_comes_from_translation_payload(language):
    html = gallery_html(language)
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    payload = json.loads(script.split("const P = ", 1)[1].split(";\n", 1)[0])
    for field, constant in (
        ("helpReadHint", "HINT_READ_KEYS"),
        ("helpNoDiskHint", "HINT_ESC_NO_SELECTION"),
        ("stopKeepConnected", "POWER_KEEP_CONNECTED"),
    ):
        assert payload[field] == lang.translated(language, "copy", constant)
    for english in (
        'aria-label="Report requirements"',
        'aria-label="Identify the disk"',
        'aria-label="Supported storage limits"',
        'renderHint("Nothing is saved here. Esc returns.")',
        'renderHint("Esc returns with no disk selected.")',
        'renderHint("Keep the disk and Beamo USB connected.")',
        "Preview only. Nothing on this computer was erased.",
        "Review stop again (preview)",
    ):
        assert english not in script
