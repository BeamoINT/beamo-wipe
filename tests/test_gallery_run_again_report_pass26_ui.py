# SPDX-License-Identifier: GPL-3.0-or-later
"""The completed preview must retain the report-loss decision on restart."""

import re
import shutil
import subprocess

import pytest

from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize("screen", ("stopped", "done"))
@pytest.mark.parametrize("report_wanted", (False, True))
def test_run_again_from_result_requires_discard_decision(screen, report_wanted):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    (script,) = re.findall(r"<script>(.*?)</script>", gallery_html(), re.S)
    callbacks = re.findall(
        r'btnsR\.append\(btn\(P\.buttons\.runAgain,\s*(.*?)\s*,\s*"primary"\)\);',
        script,
        re.S,
    )
    assert len(callbacks) == 2
    helper = ""
    if "function requestAnotherPreview() {" in script:
        helper = script[
            script.index("function requestAnotherPreview() {"):
            script.index("function closePreview() {")
        ]
    program = f"""
let screen = {screen!r}, reportWanted = {str(report_wanted).lower()},
    anotherPending = false, shutdownFrom = 'owner', fail = false, mode = 'happy';
let draws = 0, bootCalls = 0;
function draw() {{ draws++; }}
function boot() {{ bootCalls++; screen = 'splash'; reportWanted = false; }}
{helper}
const runAgain = {callbacks[0 if screen == "stopped" else 1]};
runAgain();
if (screen !== 'shutdown_confirm' || shutdownFrom !== {screen!r} ||
    !anotherPending || reportWanted !== {str(report_wanted).lower()} ||
    bootCalls !== 0 || draws !== 1)
  throw Error(`result restarted without preserving discard decision: ${{screen}}`);
"""
    result = subprocess.run([node, "-e", program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
