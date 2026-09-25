"""The click-through's final review must last five visible seconds."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize("return_action", ("escape", "button"))
def test_refresh_confirmation_cannot_consume_preview_review_countdown(return_action):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    scripts = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    assert len(scripts) == 1
    source = scripts[0]
    assert "btn(P.buttons.back, cancelRefresh)" in source
    refresh = source[source.index("function requestRefresh() {"):source.index("function headerCaption(")]
    keys = source[source.index('document.addEventListener("keydown", e => {'):source.index("function renderOtherDevices()")]
    countdown = source[source.index("function startCount() {"):source.index("function currentProgress()")]
    program = f"""
let screen = 'last', refreshFrom = 'owner', shutdownFrom = 'owner', reportHelpFrom = 'owner';
let tLeft = 5, timer = null, callback, intervalCallback, nextId = 0;
const document = {{addEventListener(_name, fn) {{ callback = fn; }}}};
const main = {{querySelector() {{ return {{focus() {{}}}}; }}}};
const draw = () => {{}};
const setInterval = fn => {{ intervalCallback = fn; return ++nextId; }};
const clearInterval = () => {{ intervalCallback = null; }};
{refresh}
{keys}
{countdown}
startCount();
requestRefresh();
if (screen !== 'refresh_confirm') throw Error('refresh confirmation did not open');
for (let i = 0; i < 5; i++) if (intervalCallback) intervalCallback();
{"callback({key:'Escape', repeat:false, preventDefault() {}});" if return_action == "escape" else "cancelRefresh();"}
if (screen !== 'last') throw Error('review did not resume');
if (tLeft !== 5) throw Error('offscreen countdown consumed review: ' + tLeft);
if (!intervalCallback) throw Error('review countdown did not restart');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
