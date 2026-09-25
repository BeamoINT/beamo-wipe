# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview splash must honor its visible any-key instruction."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


def test_splash_any_key_advances_without_stealing_scenario_controls():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    (script,) = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    start = script.index('document.addEventListener("keydown"')
    end = script.index("function renderOtherDevices()", start)
    handler = script[start:end]
    program = r"""
let screen = 'splash', renders = 0, onKey;
const main = {querySelector() { return {focus() {}}; }};
const document = {addEventListener(_type, fn) { onKey = fn; }};
function draw() { renders++; }
function cancelRefresh() {}
function requestRefresh() {}
function refreshPreview() {}
""" + handler + r"""
const scenarioTarget = {closest(selector) {
  return selector === '.scenarios' ? {} : null;
}};
let prevented = false;
onKey({key:' ', repeat:false, target:scenarioTarget,
  preventDefault() { prevented = true; }});
if (screen !== 'splash' || prevented || renders !== 0)
  throw Error('scenario button key was stolen');
const splashTarget = {closest() { return null; }};
onKey({key:'a', repeat:false, target:splashTarget,
  preventDefault() { prevented = true; }});
if (screen !== 'keyboard' || renders !== 1 || !prevented)
  throw Error('splash ignored its any-key instruction');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
