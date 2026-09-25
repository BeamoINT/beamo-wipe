# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview deep links must honor prerequisites of their destination screens."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize(
    ("fragment", "expected"),
    (
        ("#s=limits", "pick"),
        ("#s=advanced", "pick"),
        ("#scenario=blocked&s=pick", "blocked"),
        ("#scenario=empty&s=pick", "empty"),
        ("#s=limits&disk=0", "limits"),
        ("#s=advanced&disk=0", "advanced"),
    ),
)
def test_preview_hash_respects_disk_and_inventory_prerequisites(fragment, expected):
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
if (screen !== {expected!r}) throw Error('bad screen: ' + screen);
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("screen", ("splash", "keyboard", "owner"))
def test_preview_hash_does_not_preselect_a_disk_before_picker(screen):
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
const location = {{hash: '#s={screen}&disk=0&typed=1'}};
function boot() {{ screen = 'splash'; selected = null; }}
function selectable() {{ return [{{token: 'ABCD'}}]; }}
function draw() {{}}
{handler}
applyHash();
if (selected !== null || token !== '') throw Error('disk preselected before picker');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
