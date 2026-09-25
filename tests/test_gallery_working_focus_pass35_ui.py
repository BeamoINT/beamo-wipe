# SPDX-License-Identifier: GPL-3.0-or-later
"""Progress redraws must leave the preview's keyboard controls reachable."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


def test_working_progress_redraw_keeps_keyboard_focus():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    (script,) = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    start = script.index("function draw() {")
    end = script.index('document.addEventListener("keydown"', start)
    draw = script[start:end]
    program = r"""
let active = null, more = null;
class Bucket {
  constructor() { this.children = []; this.style = {}; this.textContent = ''; }
  set innerHTML(value) {
    if (this.children.includes(active) || (this === elements.main && active === more)) active = null;
    this.children = [];
    this.html = value;
    if (this === elements.main && value.includes('id="more"'))
      more = {id:'more', matches() { return false; }, focus() { active = this; }};
  }
  append(button) { this.children.push(button); }
  prepend(button) { this.children.unshift(button); }
  querySelectorAll() {
    return this === elements.foot
      ? [...elements.utilities.children, ...elements.btnsL.children, ...elements.btnsR.children]
      : this.children;
  }
  querySelector() { return null; }
}
const elements = Object.fromEntries(
  ['step','journey','sfill','main','btnsL','btnsR','foot','utilities','hint']
    .map(id => [id, new Bucket()]));
const document = {
  get activeElement() { return active || {matches() { return false; }}; },
  getElementById(id) { return id === 'more' ? more : elements[id] || null; },
  querySelector() { return new Bucket(); },
};
const P = {
  journey: ['Prepare','Erase','Result'], methods: {everyday: {summary:'Summary'}},
  titles: {working:'Working'}, eraseProgress:'Progress', previewBanner:'Preview',
  stop: {ask:'Stop erase'}, sounds: {toggleOff:'Enable sounds', toggleOn:'Disable sounds', hear:'Hear sounds'},
  hints: {default:'Hint', working:'Working hint'},
};
let screen = 'working', renderedScreen = null, showMore = false;
let selected = {path:'/dev/fake'}, method = 'everyday', soundsOn = false;
function applyTextSize() {}
function stepInfo() { return [2, 'Erase', 'Working']; }
function headerCaption(info) { return info[1]; }
function renderHint() {}
function summaryCard() { return '<div>Fake disk</div>'; }
function moreLink() { return '<button id="more">More</button>'; }
function bindMore() {}
function powerText() { return 'Power'; }
function currentProgress() { return {percent: 20, percentText:'20%', timingText:'Time', animate:false}; }
function esc(value) { return value; }
function btn(label, onclick) {
  return {textContent: label, disabled:false, onclick,
    matches(selector) { return selector === '.foot button'; },
    focus() { active = this; }};
}
""" + draw + r"""
draw();
for (let i = 0; i < 3; i++) {
  const oldButton = elements.btnsL.children[i];
  oldButton.focus();
  draw();
  const newButton = elements.btnsL.children[i];
  if (oldButton === newButton) throw Error('working controls were not rebuilt');
  if (document.activeElement !== newButton)
    throw Error('progress redraw lost keyboard focus on ' + oldButton.textContent);
}
more.focus();
draw();
if (document.activeElement !== more)
  throw Error('progress redraw lost keyboard focus on Show more');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
