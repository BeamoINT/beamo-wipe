# SPDX-License-Identifier: GPL-3.0-or-later
"""Render shipped launcher assets with fake Go snapshots; no device probes."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser_cases(tmp_path_factory):
    playwright = pytest.importorskip("playwright.sync_api")
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome or not shutil.which("go"):
        pytest.skip("Launcher renders require Chrome, Go and Python Playwright")
    fixtures = tmp_path_factory.mktemp("readiness") / "fixtures.json"
    subprocess.run(["go", "test", "-run", "^TestReadinessExplainsEachCheck$", "."],
                   cwd=ROOT / "desktop", check=True,
                   env={**os.environ, "BEAMO_READINESS_FIXTURES": str(fixtures)})
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=chrome,
                                          args=["--no-sandbox", "--disable-dev-shm-usage"])
        yield browser, json.loads(fixtures.read_text())
        browser.close()


def open_launcher(browser, value, size=(1024, 900), restart_status=200, storage_denied=False):
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    if storage_denied:
        page.add_init_script("""Object.defineProperty(window, 'sessionStorage', {
          configurable: true, get() { throw new DOMException('blocked', 'SecurityError'); }
        });""")
    calls = []
    responses = {"check": value, "state": {"preview": False}}

    def serve(route):
        path = route.request.url.split("launcher.test", 1)[-1]
        if path.startswith("/api/"):
            action = path.removeprefix("/api/")
            calls.append(action)
            if action == "restart":
                route.fulfill(status=restart_status, content_type="application/json",
                              body=json.dumps({"message": "Preview complete. Nothing was changed."})
                              if restart_status == 200 else "Permission declined. Check readiness and try again.")
            else:
                route.fulfill(content_type="application/json", body=json.dumps(responses.get(action, {})))
        else:
            name = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[path]
            route.fulfill(path=str(ROOT / "desktop/web" / name))

    page.route("http://launcher.test/**", serve)
    page.goto("http://launcher.test/#" + "a" * 64)
    page.wait_for_function("document.querySelector('#readiness').getAttribute('aria-busy') === 'false'")
    return page, calls, responses


def test_launcher_token_survives_help_reload_and_unavailable_storage():
    """Exercise the shipped token bootstrap without probing disks or firmware."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed for the launcher JavaScript bootstrap test")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const end = source.indexOf("let busy = false;");
assert.ok(end > 0, "launcher bootstrap boundary missing");
const bootstrap = source.slice(0, end) + "\nglobalThis.observedToken = token;";
const expected = "a".repeat(64);
const saved = new Map();
function load(fragment, storageDenied = false, priorHistoryState = null) {
  let hash = fragment;
  let state = priorHistoryState;
  let onHashChange = null;
  const context = {
    location: {get hash() { return hash; }, pathname: "/", search: ""},
    history: {
      get state() { return state; },
      replaceState(nextState, _title, url) {
        state = nextState;
        if (url !== undefined) {
          assert.equal(url, "/");
          hash = "";
        }
      }
    },
    window: {addEventListener(name, fn) {
      if (name === "hashchange") onHashChange = fn;
    }}
  };
  if (storageDenied) {
    Object.defineProperty(context, "sessionStorage", {get() { throw Error("storage denied"); }});
  } else {
    context.sessionStorage = {
      getItem(key) { return saved.get(key) || null; },
      setItem(key, value) { saved.set(key, value); }
    };
  }
  vm.runInNewContext(bootstrap, context);
  return {
    token: context.observedToken,
    get hash() { return hash; },
    get state() { return state; },
    navigate(nextHash) {
      hash = nextHash;
      state = null; // A fragment navigation can create a new history entry.
      if (onHashChange) onHashChange();
    }
  };
}
assert.equal(load("#" + expected).token, expected);
assert.equal(saved.get("beamo-session"), expected);
assert.equal(load("#trouble-usb").token, expected,
             "a help anchor must not override the stored session token");
const firstRestricted = load("#" + expected, true);
assert.equal(firstRestricted.token, expected);
assert.equal(firstRestricted.hash, "#" + expected,
             "keep the token fragment when storage cannot preserve it");
assert.equal(load(firstRestricted.hash, true).token, expected,
             "reload must keep working when browser storage is unavailable");
firstRestricted.navigate("#trouble-usb");
assert.equal(firstRestricted.hash, "#trouble-usb");
assert.equal(load(firstRestricted.hash, true, firstRestricted.state).token, expected,
             "help anchor and reload must retain the session when storage is unavailable");
"""
    subprocess.run([node, "-e", script, str(ROOT / "desktop/web/app.js")],
                   check=True, capture_output=True, text=True)


def test_help_anchor_reload_keeps_launcher_session(browser_cases):
    browser, fixtures = browser_cases
    page, calls, _ = open_launcher(browser, fixtures["pass"])
    try:
        page.locator("#help summary").click()
        page.locator('.chooser a[href="#trouble-usb"]').click()
        assert page.url.endswith("#trouble-usb")
        page.reload()
        page.wait_for_function("document.querySelector('#readiness').getAttribute('aria-busy') === 'false'")
        assert page.locator("#confirm").is_visible()
        assert calls.count("check") == 2
        assert page.locator("#status").get_attribute("class") != "error"
    finally:
        page.close()


def test_help_anchor_reload_with_storage_denied(browser_cases):
    browser, fixtures = browser_cases
    page, calls, _ = open_launcher(browser, fixtures["pass"], storage_denied=True)
    try:
        expected = "a" * 64
        assert page.url.endswith("#" + expected)
        page.locator("#help summary").click()
        page.locator('.chooser a[href="#trouble-usb"]').click()
        page.wait_for_function("history.state && history.state.beamoToken === '" + expected + "'")
        assert page.url.endswith("#trouble-usb")
        page.reload()
        page.wait_for_function("document.querySelector('#readiness').getAttribute('aria-busy') === 'false'")
        assert page.evaluate("token") == expected
        assert page.locator("#confirm").is_visible()
        assert calls.count("check") == 2
    finally:
        page.close()


@pytest.mark.parametrize("case", ["pass", "partial", "fail", "unsupported", "permission", "legacy", "pending", "unattended", "live", "timeout", "cancelled"])
def test_explained_checks_and_safe_next_actions(browser_cases, case):
    browser, fixtures = browser_cases
    page, calls, _ = open_launcher(browser, fixtures[case])
    try:
        assert page.locator("#checks h3").all_text_contents() == [
            "Original USB detection", "Startup-settings readability", "Supported restart route"]
        assert page.locator("#checks li").count() == 3
        for check in fixtures[case]["checks"]:
            assert check["detail"] in page.locator("#checks").inner_text()
            assert check["next"] in page.locator("#checks").inner_text()
        assert page.locator("#confirm").is_visible() == (case == "pass")
        assert page.locator("#restart").is_disabled()
        summary = page.locator("#technical summary")
        summary.focus()
        page.keyboard.press("Enter")
        assert page.locator("#technical-detail").is_visible()
        assert page.locator("#technical-detail").inner_text() == fixtures[case]["technical"]
        assert 'heading "Original USB detection"' in page.locator("#readiness").aria_snapshot()
        assert page.locator("#status").get_attribute("role") == "status"
        assert "restart" not in calls
    finally:
        page.close()


@pytest.mark.parametrize("bad", [None, {}, {"ready": True, "checks": []}])
def test_empty_or_incomplete_response_fails_closed_and_recovers(browser_cases, bad):
    browser, fixtures = browser_cases
    page, calls, responses = open_launcher(browser, bad)
    try:
        assert page.locator("#confirm").is_hidden()
        assert page.locator("#technical").is_hidden()
        assert "incomplete" in page.locator("#status").inner_text()
        responses["check"] = fixtures["pass"]
        page.locator("#inspect").click()
        page.wait_for_function("!document.querySelector('#confirm').hidden")
        assert not page.locator("#saved").is_checked()
        assert page.locator("#restart").is_disabled()
        assert "restart" not in calls
    finally:
        page.close()


@pytest.mark.parametrize("restart_status", [200, 503])
def test_keyboard_restart_permission_failure_retry_and_close(browser_cases, restart_status):
    browser, fixtures = browser_cases
    page, calls, responses = open_launcher(browser, fixtures["pass"], restart_status=restart_status)
    try:
        page.locator("#saved").focus()
        page.keyboard.press("Space")
        page.keyboard.press("Tab")
        assert page.locator("#restart").evaluate("e => e === document.activeElement")
        page.keyboard.press("Enter")
        page.wait_for_function("!document.querySelector('#inspect').hidden")
        assert calls.count("restart") == 1
        assert page.locator("#confirm").is_hidden()
        assert page.locator("#technical").is_hidden()
        assert "Found." not in page.locator("#checks").inner_text()
        if restart_status == 503:
            assert "Permission declined" in page.locator("#status").inner_text()
        responses["check"] = fixtures["partial"]
        page.locator("#inspect").click()
        page.wait_for_function("document.querySelectorAll('#checks h3').length === 3")
        assert "No exact route" in page.locator("#checks").inner_text()
        page.locator("#close").click()
        page.wait_for_function("document.querySelector('main').textContent.includes('Beamo Wipe is closed')")
        assert calls.count("restart") == 1
    finally:
        page.close()


@pytest.mark.parametrize("size", [(360, 900), (1024, 740), (1280, 900)])
def test_long_content_display_and_forced_colors(browser_cases, size, tmp_path):
    browser, fixtures = browser_cases
    value = json.loads(json.dumps(fixtures["pass"]))
    value["technical"] += "\nUSB identity: <script>unsafe</script>" + "X" * 600
    page, _, _ = open_launcher(browser, value, size)
    try:
        page.locator("#technical summary").click()
        assert page.locator("#technical-detail script").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.emulate_media(forced_colors="active")
        page.locator("#technical summary").focus()
        page.keyboard.press("Tab")
        assert page.locator("#saved").evaluate("e => getComputedStyle(e).outlineStyle") != "none"
        assert page.locator("#restart").is_disabled()
        page.screenshot(path=str(tmp_path / "launcher.png"), full_page=True)
    finally:
        page.close()


def test_loading_network_failure_expired_session_and_retry(browser_cases):
    browser, fixtures = browser_cases
    page, calls, _ = open_launcher(browser, fixtures["partial"])
    held = []
    try:
        page.route("http://launcher.test/api/check", lambda route: held.append(route))
        page.locator("#inspect").click()
        page.wait_for_function("document.querySelector('#readiness').getAttribute('aria-busy') === 'true'")
        assert page.locator("#checks h3").count() == 0
        assert page.locator("#technical").is_hidden()
        assert page.locator("#restart").is_disabled()
        assert page.locator("#inspect").is_disabled()
        page.wait_for_timeout(100)
        assert held
        held.pop().abort()
        page.wait_for_function("!document.querySelector('#inspect').disabled")
        assert "no longer connected" in page.locator("#status").inner_text()
        page.locator("#inspect").click()
        page.wait_for_timeout(100)
        held.pop().fulfill(status=403, body="Request not authorized")
        page.wait_for_function("!document.querySelector('#inspect').disabled")
        assert "session has ended" in page.locator("#status").inner_text()
        assert page.locator("#confirm").is_hidden()
        assert "restart" not in calls
    finally:
        page.close()
