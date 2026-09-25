# SPDX-License-Identifier: GPL-3.0-or-later
"""The click-through offers refresh on the same screens as the live wizard."""

import shutil
import subprocess
import re

import pytest

from beamo_wipe.gallery import gallery_html


def test_keyboard_setup_cannot_open_inventory_refresh():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the browser preview handler")
    source = gallery_html()
    script = source.split("<script>", 1)[1].split("</script>", 1)[0]
    handler = script[script.index("function requestRefresh() {"):script.index("function cancelRefresh() {")]
    program = f"""
let screen = "keyboard";
let timer = null;
let refreshFrom = "owner";
let draws = 0;
function draw() {{ draws++; }}
{handler}
requestRefresh();
if (screen !== "keyboard" || draws !== 0 || refreshFrom !== "owner")
  throw Error("keyboard setup opened inventory refresh");
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_keyboard_setup_has_no_refresh_utility():
    source = gallery_html()
    match = re.search(
        r'if \(!\[(.*?)\]\.includes\(screen\)\) \{\s*utilities\.prepend\(btn\(P\.refreshUtility',
        source,
        re.DOTALL,
    )
    assert match is not None
    assert '"keyboard"' in match.group(1)
