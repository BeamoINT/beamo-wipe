"""Malformed preview deep links must not strand the click-through."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize(
    ("fragment", "expected"),
    (
        ("#s=confirm", "pick"),
        ("#s=confirm&disk=bogus", "pick"),
        ("#s=confirm&disk=0junk", "pick"),
        ("#s=working", "pick"),
        ("#scenario=blocked&s=confirm&disk=0", "blocked"),
        ("#scenario=empty&s=confirm&disk=0", "empty"),
        ("#s=unrecognized", "splash"),
        ("#s=confirm&disk=0", "confirm"),
    ),
)
def test_preview_hash_never_opens_an_invalid_screen(fragment, expected):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    script, = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    handler = script[script.index("function applyHash() {"):script.index("if (location.hash) applyHash()")]
    program = f"""
let screen = 'splash', mode = 'happy', selected = null, token = '', owner = false;
let method = 'everyday', tLeft = 5, textSize = 'standard';
let progressKey = '', demoFrac = null, demoPct = null, showMore = false;
let reportWanted = false, reportShareRedacted = false;
const P = {{methods: {{everyday: {{}}}}, progress: {{states: {{}}}}}};
const location = {{hash: {fragment!r}}};
function boot(scenario) {{ mode = scenario; screen = 'splash'; selected = null; }}
function selectable() {{ return ['blocked', 'empty'].includes(mode) ? [] : [{{token: 'ABCD'}}]; }}
function draw() {{}}
{handler}
applyHash();
if (screen !== {expected!r}) throw Error('bad screen: ' + screen);
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
