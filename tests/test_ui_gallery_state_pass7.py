# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview must show the live report choices and survive bad deep links."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from beamo_wipe import copy as C
from beamo_wipe.gallery import gallery_html


def _script() -> str:
    scripts = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    assert len(scripts) == 1
    return scripts[0]


def test_preview_report_help_includes_separate_redacted_sharing_choice():
    html = gallery_html()
    payload = json.loads(html.split("const P = ", 1)[1].split(";\n", 1)[0])
    assert payload["reportShareRedacted"] == C.REPORT_SHARE_REDACTED
    script = _script()
    assert 'id="report-share"' in script
    assert "let reportShareRedacted = false" in script
    assert "reportShareRedacted = false;" in script.split("function boot(m)", 1)[1]


def test_held_key_does_not_reverse_redacted_sharing_choice():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for JavaScript behavior checks")
    script = _script()
    start = script.index("share.onkeydown =")
    end = script.index("btnsL.append", start)
    handler = script[start:end]
    setup = (
        "let share = {}; let reportShareRedacted = false; let updates = 0; "
        "const syncShare = () => { updates += 1; };"
    )
    action = (
        "const event = repeat => ({key: ' ', repeat, preventDefault() {}}); "
        "share.onkeydown(event(false)); share.onkeydown(event(true)); "
        "if (!reportShareRedacted || updates !== 1) throw Error('held key reversed consent');"
    )
    result = subprocess.run(
        [node, "-e", setup + "\n" + handler + "\n" + action],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_invalid_deep_link_method_keeps_default_and_valid_method_works():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for JavaScript behavior checks")
    script = _script()
    function = script.split("function applyHash() {", 1)[1].split("\nif (location.hash)", 1)[0]
    program = """
const P = {methods: {everyday: {operation:'default'}, extra:{operation:'extra'}}, progress:{states:{}}};
let location = {hash:'#s=last&disk=0&method=bogus'};
let method = 'everyday', selected = null, token = '', owner = false;
let tLeft=5, textSize='standard', progressKey='', demoFrac=null, demoPct=null;
let showMore=false, reportWanted=false, screen='splash';
const selectable = () => [{token:'123'}];
const boot = () => {method='everyday'; selected=null;};
const draw = () => {if (screen === 'last') {if (!P.methods[method]) throw Error('broken review');}};
const startCount = () => {};
function applyHash() {""" + function + """
applyHash();
if (method !== 'everyday') throw Error('invalid method survived');
location.hash='#s=last&disk=0&method=extra';
applyHash();
if (method !== 'extra') throw Error('valid method lost');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "screen,repeat,expected_refreshes",
    (("owner", True, 0), ("working", False, 0),
     ("owner", False, 1), ("refresh_confirm", False, 1)),
)
def test_f5_never_reloads_browser_or_repeats_inventory_action(
    screen, repeat, expected_refreshes
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for JavaScript behavior checks")
    script = _script()
    listener = script.split('document.addEventListener("keydown", e => {', 1)[1].split("\n});", 1)[0]
    program = """
let handler;
const document = {addEventListener(_name, fn) {handler=fn;}};
let screen = """ + json.dumps(screen) + """;
let refreshes=0;
const requestRefresh=()=>{refreshes += 1;};
const refreshPreview=()=>{refreshes += 1;};
const draw=()=>{};
let refreshFrom='owner', shutdownFrom='owner', reportHelpFrom='owner';
let event={key:'F5', repeat:""" + json.dumps(repeat) + """, defaultPrevented:false,
  preventDefault(){this.defaultPrevented=true;}};
document.addEventListener("keydown", e => {""" + listener + "\n});\n" + """
handler(event);
if (!event.defaultPrevented || refreshes !== """ + str(expected_refreshes) + """)
  throw Error('F5 reached browser reload or repeated refresh');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
