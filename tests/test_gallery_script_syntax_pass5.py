# SPDX-License-Identifier: GPL-3.0-or-later
"""The browser preview must ship executable JavaScript in every language."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize("language", ("en", "fr", "de"))
def test_generated_gallery_script_parses(language, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for JavaScript syntax validation")
    scripts = re.findall(r"<script>(.*?)</script>", gallery_html(language), re.S)
    assert len(scripts) == 1
    script = tmp_path / f"gallery-{language}.js"
    script.write_text(scripts[0], encoding="utf-8")
    result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
