# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser preview choices must not reverse on keyboard auto-repeat."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


def _script() -> str:
    scripts = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    assert len(scripts) == 1
    return scripts[0]


def _run_handler(segment: str, setup: str, action: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for JavaScript behavior checks")
    program = setup + "\n" + segment + "\n" + action
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_held_space_does_not_reverse_owner_checkbox():
    script = _script()
    start = script.index("card.onclick = toggle;")
    end = script.index("btnsL.append", start)
    segment = script[start:end]
    _run_handler(
        segment,
        "let card = {}; let toggles = 0; const toggle = () => { toggles += 1; };",
        "const event = repeat => ({key: ' ', repeat, preventDefault() {}}); "
        "card.onkeydown(event(false)); card.onkeydown(event(true)); "
        "if (toggles !== 1) throw Error('held Space toggled owner ' + toggles + ' times');",
    )


@pytest.mark.parametrize("key", (" ", "Enter"))
def test_held_key_does_not_reverse_report_preference(key):
    script = _script()
    start = script.index("wanted.onkeydown =")
    end = script.index("const share =", start)
    segment = script[start:end]
    _run_handler(
        segment,
        "let wanted = {}; let toggles = 0; let reportWanted = false; "
        "const syncWanted = () => { toggles += 1; };",
        "const event = repeat => ({key: " + json.dumps(key) + ", repeat, preventDefault() {}}); "
        "wanted.onkeydown(event(false)); wanted.onkeydown(event(true)); "
        "if (toggles !== 1 || !reportWanted) throw Error('held key reversed report preference');",
    )
