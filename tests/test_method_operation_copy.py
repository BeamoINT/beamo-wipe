# SPDX-License-Identifier: GPL-3.0-or-later
"""Method facts agree with real command construction and fake-device evidence."""

import json
import re

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.evidence import build_evidence
from beamo_wipe.gallery import gallery_html
from beamo_wipe.methods import METHODS
from beamo_wipe.storage_limits import VERIFICATION_SCOPE
from beamo_wipe.models import MethodId, Screen, WipeRequest, WipeResult
from beamo_wipe.nwipe_runner import build_nwipe_argv
from beamo_wipe.support_export import _bundle_files
from beamo_wipe.ui import console_wizard

CASES = [
    (MethodId.EVERYDAY, "prng", 1, "last", 1),
    (MethodId.EXTRA, "dodshort", 3, "last", 1),
    (MethodId.QUICK_ZERO, "zero", 1, "off", 0),
]


def at_method(method):
    wiz = make_demo_wizard()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.set_method(method)
    return wiz


@pytest.mark.parametrize("method,engine,writes,verify,reads", CASES)
@pytest.mark.parametrize("state", ["success", "failed", "ambiguous", "interrupted"])
def test_command_evidence_and_report(method, engine, writes, verify, reads, state):
    wiz = at_method(method)
    spec = METHODS[method]
    request = WipeRequest(
        wiz.selected.path,
        method,
        wiz.discovery.boot.path,
        "/tmp/beamo-wipe/nwipe-fake.log",
    )
    argv = build_nwipe_argv(request)
    assert {
        f"--method={engine}",
        f"--verify={verify}",
        "--rounds=1",
        "--noblank",
    } <= set(argv)
    assert argv[-1] == wiz.selected.path
    assert f"--exclude={wiz.discovery.boot.path}" in argv
    assert "--force" not in argv
    assert (spec.overwrite_passes, spec.verification_passes) == (writes, reads)
    log = f"{wiz.selected.name} | Erased |\n" if state != "ambiguous" else ""
    ev = build_evidence(
        disk=wiz.selected,
        discovery=wiz.discovery,
        method=method,
        request=request,
        result=WipeResult(state != "failed", 1 if state == "failed" else 0, "", ""),
        started_at_wall="",
        ended_at_wall="",
        started_mono=0,
        ended_mono=1,
        argv=argv,
        log_text=log,
        interrupted=state == "interrupted",
    )
    expected = (
        ("verified" if reads else "completed")
        if state == "success"
        else ("interrupted" if state == "interrupted" else "failed")
    )
    assert ev["outcome"] == expected
    assert ev["method"]["overwrite_passes"] == writes
    assert ev["method"]["verification_passes"] == reads
    assert ev["method"]["description"] == spec.description
    assert ev["verification"]["scope"] == VERIFICATION_SCOPE
    wiz.preview = False
    wiz.evidence = ev
    assert wiz.method_result == ev["result_description"]
    if state != "success":
        assert "not confirmed" in wiz.method_result
    elif reads:
        assert ev["verification"]["verified"] is True
        assert "accessible storage" in wiz.method_result
    else:
        assert ev["verification"]["verified"] is False
        assert "Verification was not performed" in wiz.method_result
    bundle = _bundle_files(json.dumps(ev).encode(), b"", "unavailable")
    assert json.loads(bundle["result.json"])["result_description"] == wiz.method_result


@pytest.mark.parametrize("method,engine,writes,verify,reads", CASES)
def test_cards_gallery_and_plain_console(
    method, engine, writes, verify, reads, monkeypatch, capsys
):
    spec = METHODS[method]
    card = C.METHOD_CARDS[method]
    assert f"{writes} overwrite" in card["blurb"]
    assert card["blurb"] + " " + card["pace"] == spec.description
    if reads:
        assert "1 separate read-back verification pass" in card["pace"]
    else:
        assert "Verification is not performed" in card["pace"]
    payload = json.loads(re.search(r"const P = (.*);", gallery_html()).group(1))
    assert payload["methods"][method.value]["summary"] == spec.summary
    wiz = at_method(method)

    def stop(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", stop)
    console_wizard._plain_loop(wiz)
    text = capsys.readouterr().out
    for other in METHODS.values():
        assert other.description in text
    wiz.wants_shutdown = False
    wiz.continue_method()
    wiz._erase_until = 0
    console_wizard._plain_loop(wiz)
    assert spec.summary in capsys.readouterr().out
    wiz.wants_shutdown = False
    wiz.screen = Screen.DONE
    console_wizard._plain_loop(wiz)
    text = capsys.readouterr().out
    assert spec.summary in text
    assert "No overwrite or verification was performed" in text


@pytest.mark.parametrize("method", list(METHODS))
@pytest.mark.parametrize("screen", [Screen.METHOD, Screen.LAST_CHANCE, Screen.DONE])
def test_curses_visible_facts_without_truncation(method, screen, monkeypatch):
    wiz = at_method(method)
    wiz.screen = screen

    class Terminal:
        def __init__(self):
            self.rows = {}

        def getmaxyx(self):
            return (25, 80)

        def addstr(self, y, x, text, attr=0):
            assert y < 25
            assert len(text) < 80
            self.rows[y] = text

        def getch(self):
            wiz.wants_shutdown = True
            return ord("q")

        def __getattr__(self, name):
            return lambda *args: None

    term = Terminal()
    monkeypatch.setattr(console_wizard.curses, "curs_set", lambda *args: None)
    monkeypatch.setattr(console_wizard.curses, "use_default_colors", lambda: None)
    console_wizard._loop(term, wiz)
    text = " ".join(term.rows[y] for y in sorted(term.rows))
    for spec in METHODS.values() if screen == Screen.METHOD else [METHODS[method]]:
        assert spec.description in text
    if screen == Screen.DONE:
        assert wiz.method_result in text
