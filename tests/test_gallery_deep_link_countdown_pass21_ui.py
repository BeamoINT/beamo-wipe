# SPDX-License-Identifier: GPL-3.0-or-later
"""A preview deep link to review must actually advance its countdown."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize("ready", (False, True))
def test_last_chance_deep_link_starts_countdown_unless_already_ready(ready):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")

    (script,) = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    countdown = script[script.index("function startCount() {"):script.index("function currentProgress()")]
    deep_link = script[script.index("function applyHash() {"):script.index("if (location.hash) applyHash()")]
    fragment = "#s=last&disk=0" + ("&ready=1" if ready else "")
    program = f"""
let screen = 'splash', mode = 'happy', selected = null, token = '', owner = false;
let method = 'everyday', tLeft = 5, textSize = 'standard', timer = null;
let progressKey = '', demoFrac = null, demoPct = null, showMore = false;
let reportWanted = false, reportShareRedacted = false;
let callback = null, draws = 0;
const P = {{methods: {{everyday: {{}}}}, progress: {{states: {{}}}}}};
const location = {{hash: {fragment!r}}};
function setInterval(fn) {{ callback = fn; return 1; }}
function clearInterval() {{}}
function boot(scenario) {{ mode = scenario; screen = 'splash'; selected = null; tLeft = 5; }}
function selectable() {{ return [{{token: 'ABCD'}}]; }}
function draw() {{ draws += 1; }}
{countdown}
{deep_link}
applyHash();
if (screen !== 'last') throw Error('not on last chance');
if (!!callback !== {str(not ready).lower()}) throw Error('wrong countdown timer state');
if (callback) {{
  callback();
  if (tLeft !== 4 || draws !== 2) throw Error('countdown did not advance');
}}
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
