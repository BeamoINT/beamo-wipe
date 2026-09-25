"""Keyboard method selection keeps focus on the rebuilt choice."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


def test_keyboard_method_selection_keeps_focus():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    (script,) = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    method = script.index('} else if (screen === "method")')
    start = script.index('    main.querySelectorAll(".card.pickable").forEach(el => {', method)
    end = script.index('    main.querySelector("#limits")', start)
    handler = script[start:end]
    program = """
let method = 'everyday';
let active = {id: 'body'};
let redraws = 0;
const oldCard = {dataset: {id: 'extra'}, focus() { active = this; }};
const newCard = {dataset: {id: 'extra'}, focus() { active = this; }};
let cards = [oldCard];
const main = {
  querySelectorAll() { return cards; },
  querySelector(selector) {
    return selector === '[data-id="extra"]' ? cards[0] : null;
  },
};
function draw() { redraws += 1; cards = [newCard]; active = {id: 'body'}; }
""" + handler + """
oldCard.focus();
oldCard.onkeydown({key: ' ', repeat: false, preventDefault() {}});
if (method !== 'extra') throw Error('method did not change');
if (active !== newCard) throw Error('keyboard focus was lost after method selection');
oldCard.onkeydown({key: ' ', repeat: true, preventDefault() {}});
if (redraws !== 1) throw Error('held Space redrew the method choice');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_keyboard_setup_choices_keep_focus():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    (script,) = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    start = script.index('    main.querySelectorAll("[data-layout]").forEach(el => {')
    end = script.index('    const box = main.querySelector("#kbcheck")', start)
    handlers = script[start:end]
    program = """
let keyboardLayout = 'us', owner = true, token = 'old', selected = {};
let textSize = 'standard', active = {id: 'body'};
const oldLayout = {dataset: {layout: 'fr'}, focus() { active = this; }};
const newLayout = {dataset: {layout: 'fr'}, focus() { active = this; }};
const oldSize = {dataset: {text: 'large'}, focus() { active = this; }};
const newSize = {dataset: {text: 'large'}, focus() { active = this; }};
let layouts = [oldLayout], sizes = [oldSize];
const main = {
  querySelectorAll(selector) { return selector === '[data-layout]' ? layouts : sizes; },
  querySelector(selector) {
    if (selector === '[data-layout="fr"]') return layouts[0];
    if (selector === '[data-text="large"]') return sizes[0];
    return null;
  },
};
function draw() {
  layouts = [newLayout]; sizes = [newSize]; active = {id: 'body'};
}
""" + handlers + """
oldLayout.focus();
oldLayout.onkeydown({key: ' ', repeat: false, preventDefault() {}});
if (keyboardLayout !== 'fr' || active !== newLayout)
  throw Error('layout selection lost keyboard focus');
oldSize.focus();
oldSize.onclick();
if (textSize !== 'large' || active !== newSize)
  throw Error('text-size selection lost keyboard focus');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_text_size_utility_keeps_focus():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    (script,) = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    start = script.index('  if (!["splash", "keyboard", "working"')
    end = script.index('  if (screen === "last") {\n    const focused', start)
    handler = script[start:end]
    program = """
const P = {textSizes: [{id: 'standard', label: 'Standard'},
  {id: 'large', label: 'Large'}], textSizeUtility: 'Text size'};
let screen = 'owner', textSize = 'standard', active = {id: 'body'};
let oldButton;
const newButton = {focus() { active = this; }};
const utilities = {append(button) { oldButton = button; }};
const document = {getElementById(id) {
  return id === 'text-size-utility' ? newButton : null;
}};
function btn(_label, onclick) { return {onclick, focus() { active = this; }}; }
function draw() { active = {id: 'body'}; }
""" + handler + """
oldButton.focus();
oldButton.onclick();
if (textSize !== 'large' || active !== newButton)
  throw Error('text-size utility lost keyboard focus');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
