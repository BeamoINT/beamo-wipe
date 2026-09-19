# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #109: browser preview must match Tk/console semantics, not colors."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from html import unescape
from pathlib import Path

import pytest

from beamo_wipe import copy as C
from beamo_wipe import identity as ident
from beamo_wipe import progress as P
from beamo_wipe.gallery import (
    _progress_preview_payload,
    gallery_html,
)
from beamo_wipe.ui import tk_wizard as tkui


def _payload(html: str) -> dict:
    marker = "const P = "
    start = html.index(marker) + len(marker)
    end = html.index(";\n", start)
    return json.loads(html[start:end])


def _chrome() -> str | None:
    return shutil.which("google-chrome") or shutil.which("chromium")


def test_gallery_parity_is_not_only_color_tokens():
    """Would pass on origin/main: CSS hex tokens matched while Show more and
    progress states did not."""
    html = gallery_html()
    source = html
    assert "demoPct / 100 * stages.length" not in source
    assert "demoPct = Math.min(p, 100)" not in source
    assert ident.SYSTEM_PATH_NOTE in source
    assert '"pathNote"' in source
    assert "progress.states" in source or '"states"' in source
    assert "aria-controls" in source
    assert "currentProgress" in source
    assert 'id="pulse">${P.working}' not in source


def test_show_more_uses_translated_system_path_note():
    gallery_html("en")
    html_de = gallery_html("de")
    payload = _payload(html_de)
    assert payload["pathNote"] == "Systemname (keine stabile Identität)"
    assert "Systemname" in html_de
    assert "System name (not a stable identity)" not in html_de
    assert payload["buttons"]["more"] == "Mehr anzeigen"
    assert ident.SYSTEM_PATH_NOTE == "System name (not a stable identity)"


def test_show_more_button_semantics_match_tk():
    html = gallery_html()
    assert C.BTN_MORE in html
    assert C.BTN_LESS in html
    assert 'aria-expanded="${showMore}"' in html
    assert "aria-controls" in html
    tk_src = Path(tkui.__file__).read_text(encoding="utf-8")
    assert "BTN_MORE" in tk_src
    assert "focus_set" in tk_src


def test_progress_states_match_progress_view():
    states = _progress_preview_payload()["states"]
    writing = states["writing"]
    assert writing["percent"] == 42.0
    assert writing["percentText"] == "42%"
    assert "100%" not in writing["percentText"]
    assert P.STAGE_NOT_REPORTED in states["preparing"]["stepText"]
    assert states["preparing"]["animate"] is True
    assert P.STALE_MEANING in states["stale"]["timingText"]
    assert "(old)" in states["stale"]["percentText"]
    assert P.PHASE_NOTE_VERIFYING in states["verifying"]["timingText"]
    assert states["mismatch"]["stepText"] == P.STAGE_MISMATCH
    assert P.phase_display("Stopping") in states["stopping"]["timingText"]
    assert P.PROGRESS_UNKNOWN.split()[0] in states["unknown"]["statusText"]
    extra = states["extra_writing"]
    assert "Overwrite 2 of 3" in extra["stepText"]
    assert extra["percentText"] != "100%"


def test_progress_demo_never_paints_100_percent():
    demo = _progress_preview_payload()["demo"]
    for method, frames in demo.items():
        assert frames[0]["state"]["percent"] is None
        assert frames[0]["state"]["animate"] is True
        for frame in frames:
            pct = frame["state"]["percent"]
            if pct is not None:
                assert pct < 100.0, method
                assert "100%" not in frame["state"]["percentText"]
        assert frames[-1]["frac"] <= 0.96


def test_gallery_html_embeds_progress_and_cancel_copy():
    html = gallery_html()
    payload = _payload(html)
    stale = payload["progress"]["states"]["stale"]
    assert P.STALE_NEXT in stale["timingText"]
    stopping = payload["progress"]["states"]["stopping"]
    assert stopping["timingText"].startswith("Stopping")
    assert json.dumps(stopping["timingText"])[1:-1] in html
    assert C.STOP_TITLE in html
    assert C.STOP_KEEP in html
    assert C.STOP_CONFIRM in html
    assert C.BUSY_STOPPING_TITLE in html
    assert "stop-timing" in html
    assert C.VIEWS["cancelled"].message in html
    assert C.VIEWS["stop_unconfirmed"].message in html


def test_tk_and_console_already_use_progress_view():
    tk_src = Path(tkui.__file__).read_text(encoding="utf-8")
    assert "progress_view" in tk_src
    assert "timing_text" in tk_src
    from beamo_wipe.ui import console_wizard as cui

    con = Path(cui.__file__).read_text(encoding="utf-8")
    assert "progress_view" in con
    assert "status_text" in con


def test_chrome_show_more_progress_and_cancel(tmp_path):
    """Rendered gallery: disclosure, ProgressView frames, stop overlay."""
    chrome = _chrome()
    if not chrome:
        pytest.skip("Chrome is unavailable")
    check = """<script>
    window.addEventListener('load', () => {
      const out = {};
      try {
        location.hash = '#s=confirm&disk=0&typed=1';
        applyHash();
        const more = document.getElementById('more');
        out.collapsed = more.getAttribute('aria-expanded');
        out.collapsedDetail = document.getElementById('more-detail').textContent;
        more.click();
        out.expanded = document.getElementById('more').getAttribute('aria-expanded');
        out.pathNote = document.getElementById('more-detail').textContent;
        location.hash = '#s=working&disk=0&progress=stale';
        applyHash();
        out.stalePulse = document.getElementById('pulse').innerText;
        out.stalePct = document.getElementById('pct').innerText;
        location.hash = '#s=working&disk=0&pct=100';
        applyHash();
        out.pct100Screen = screen;
        out.pct100Text = document.getElementById('pct').innerText;
        location.hash = '#s=working&disk=0&progress=mismatch';
        applyHash();
        out.mismatch = document.getElementById('pulse').innerText;
        location.hash = '#s=working&disk=0&progress=writing';
        applyHash();
        [...document.querySelectorAll('button')].find(b => b.textContent === P.stop.ask).click();
        out.stopScreen = screen;
        out.stopHeading = document.getElementById('stop-heading').textContent;
        out.stopFocus = document.activeElement.textContent;
        location.hash = '#s=stopping&disk=0';
        applyHash();
        out.stoppingTitle = document.getElementById('stop-heading').textContent;
        out.stoppingTiming = document.getElementById('stop-timing').innerText;
        out.stopMethod = document.getElementById('stop-method').textContent;
        location.hash = '#s=working&disk=0&more=1';
        applyHash();
        out.moreFromHash = document.getElementById('more').getAttribute('aria-expanded');
        out.moreFromHashText = document.getElementById('more-detail').textContent;
      } catch (err) {
        out.error = String(err);
      }
      document.documentElement.setAttribute('data-parity', JSON.stringify(out));
    });
    </script>"""
    page = tmp_path / "index.html"
    page.write_text(gallery_html().replace("</body>", check + "</body>"))
    proc = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            f"--user-data-dir={tmp_path / 'chrome'}",
            "--window-size=1280,900",
            "--dump-dom",
            page.as_uri() + "#s=confirm&disk=0&typed=1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=40)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", "replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    blob = stdout or ""
    marker = 'data-parity="'
    assert marker in blob, (blob[-1500:], stderr[-1500:])
    raw = blob.split(marker, 1)[1].split('"', 1)[0]
    out = json.loads(unescape(raw))
    assert out.get("error") is None, out
    assert out["collapsed"] == "false"
    assert ident.SYSTEM_PATH_NOTE not in (out["collapsedDetail"] or "")
    assert out["expanded"] == "true"
    assert ident.SYSTEM_PATH_NOTE in out["pathNote"]
    assert "/dev/" in out["pathNote"]
    assert P.STALE_MEANING in out["stalePulse"]
    assert "42%" in out["stalePct"]
    assert "(old)" in out["stalePct"]
    assert "100%" not in out["stalePct"]
    assert out["pct100Screen"] == "working"
    assert "100%" not in out["pct100Text"]
    assert P.STAGE_MISMATCH in out["mismatch"]
    assert out["stopScreen"] == "stop_confirm"
    assert out["stopHeading"] == C.STOP_TITLE
    assert out["stopFocus"] == C.STOP_KEEP
    assert out["stoppingTitle"] == C.BUSY_STOPPING_TITLE
    assert P.phase_display("Stopping") in out["stoppingTiming"]
    assert out["stopMethod"]
    assert out["moreFromHash"] == "true"
    assert ident.SYSTEM_PATH_NOTE in out["moreFromHashText"]


@pytest.mark.parametrize("size", [(1024, 740), (1280, 820)])
def test_playwright_keyboard_show_more(tmp_path, size):
    api = pytest.importorskip("playwright.sync_api")
    chrome = _chrome()
    if not chrome:
        pytest.skip("Chrome unavailable")
    html = tmp_path / "index.html"
    html.write_text(gallery_html())
    with api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": size[0], "height": size[1]})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(html.as_uri() + "#s=confirm&disk=0&typed=1")
        more = page.locator("#more")
        more.focus()
        page.keyboard.press("Enter")
        assert page.locator("#more").get_attribute("aria-expanded") == "true"
        page.keyboard.press("Space")
        assert page.locator("#more").get_attribute("aria-expanded") == "false"
        page.goto(html.as_uri() + "#s=working&disk=0&progress=writing")
        page.keyboard.press("Escape")
        assert page.evaluate("screen") == "stop_confirm"
        page.keyboard.press("Escape")
        assert page.evaluate("screen") == "working"
        assert not errors
        browser.close()
