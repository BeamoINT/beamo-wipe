"""Held Escape should leave only the current preview overlay."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize("start_screen", ["refresh_confirm", "report_help"])
def test_gallery_escape_repeat_does_not_cross_two_screens(start_screen):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    scripts = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    assert len(scripts) == 1
    source = scripts[0]
    start = source.index('document.addEventListener("keydown", e => {')
    end = source.index("function renderOtherDevices()", start)
    handler = source[start:end]
    program = f"""
let screen = {start_screen!r};
let refreshFrom = 'limits', reportHelpFrom = 'limits';
let callback, redraws = 0;
const main = {{querySelector() {{ return {{focus() {{}}}}; }}}};
const document = {{addEventListener(_type, fn) {{ callback = fn; }}}};
function draw() {{ redraws += 1; }}
{handler}
const event = repeat => ({{key: 'Escape', repeat, preventDefault() {{}}}});
callback(event(false));
if (screen !== 'limits') throw Error('first Escape did not close overlay: ' + screen);
callback(event(true));
if (screen !== 'limits' || redraws !== 1)
  throw Error('held Escape crossed another screen: ' + screen);
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_gallery_enter_repeat_cannot_activate_new_last_chance_focus():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    scripts = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    assert len(scripts) == 1
    source = scripts[0]
    assert '(focused || btnsL.querySelector("button")).focus()' in source
    start = source.index('document.addEventListener("keydown", e => {')
    end = source.index("function renderOtherDevices()", start)
    handler = source[start:end]
    program = f"""
// Method's Continue action has just drawn Last chance, whose safe Back button
// receives focus. A held Enter now delivers a repeat keydown to that button.
let screen = 'last', callback;
const document = {{addEventListener(_type, fn) {{ callback = fn; }}}};
{handler}
const repeated = {{key: 'Enter', repeat: true, prevented: false,
  preventDefault() {{ this.prevented = true; }}}};
callback(repeated);
if (!repeated.prevented) screen = 'method'; // Browser default activates Back.
if (screen !== 'last') throw Error('held Enter left Last chance');
const deliberate = {{key: 'Enter', repeat: false, prevented: false,
  preventDefault() {{ this.prevented = true; }}}};
callback(deliberate);
if (deliberate.prevented) throw Error('new Enter press was blocked');
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
