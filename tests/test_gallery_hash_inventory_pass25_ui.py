# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview inventory pages must describe the selected fake scenario."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize(
    ("fragment", "expected"),
    (
        ("#scenario=happy&s=blocked", "pick"),
        ("#scenario=happy&s=empty", "pick"),
        ("#scenario=blocked&s=empty", "blocked"),
        ("#scenario=empty&s=blocked", "empty"),
    ),
)
def test_hash_inventory_screen_matches_scenario(fragment, expected):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    (script,) = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    handler = script[script.index("function applyHash() {"):script.index("if (location.hash) applyHash()")]
    program = f"""
let screen = 'splash', mode = 'happy', selected = null, token = '', owner = false;
let method = 'everyday', tLeft = 5, textSize = 'standard', timer = null;
let progressKey = '', demoFrac = null, demoPct = null, showMore = false;
let reportWanted = false, reportShareRedacted = false;
const P = {{methods: {{everyday: {{}}}}, progress: {{states: {{}}}}}};
const location = {{hash: {fragment!r}}};
function boot(scenario) {{ mode = scenario; screen = 'splash'; selected = null; }}
function selectable() {{ return ['blocked', 'empty'].includes(mode) ? [] : [{{token: 'ABCD'}}]; }}
function draw() {{}}
{handler}
applyHash();
if (screen !== {expected!r}) throw Error('misleading inventory screen: ' + screen);
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
