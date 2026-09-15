"""Rendered fake-disk checks; run after BEAMO_WIPE_NO_OPEN=1 ./preview --web."""
from pathlib import Path
from playwright.sync_api import sync_playwright

url = Path("web-preview/index.html").resolve().as_uri()
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    for width in (375, 800, 1024, 1280, 1600):
        page = browser.new_page(viewport={"width": width, "height": 820})
        page.clock.install()
        page.goto("about:blank")
        page.goto(url + "#s=method&disk=0&typed=1")
        page.get_by_role("button", name="Continue", exact=True).click()
        assert page.evaluate("screen") == "last"
        ring = page.locator(".ringwrap svg").bounding_box()
        assert ring["width"] <= 64 and ring["height"] <= 64
        assert page.locator(".ringnum").evaluate(
            "el => parseFloat(getComputedStyle(el).fontSize)"
        ) <= 16
        assert "never starts erasure" in page.locator(".subtitle").inner_text()
        assert page.evaluate("document.activeElement.textContent") == "Back"
        page.keyboard.down("Enter")
        assert page.evaluate("screen") == "method"
        page.keyboard.down("Enter")  # same held key, repeat=True
        page.clock.run_for(6000)
        assert page.evaluate("screen") == "method"
        page.keyboard.up("Enter")
        page.get_by_role("button", name="Continue", exact=True).click()
        assert page.evaluate("tLeft") == 5
        page.clock.run_for(5000)
        assert page.evaluate("screen") == "last"
        assert page.evaluate("document.activeElement.textContent") == "Back"
        assert page.get_by_role("button", name="Erase now", exact=True).is_enabled()
        page.get_by_role("button", name="Erase now", exact=True).focus()
        page.keyboard.press("Enter")
        assert page.evaluate("screen") == "working"
        page.goto("about:blank")
        page.goto(url + "#s=method&disk=0&typed=1")
        page.get_by_role("button", name="Continue", exact=True).click()
        page.clock.run_for(5000)
        page.get_by_role("button", name="Erase now", exact=True).click()
        assert page.evaluate("screen") == "working"
        page.goto("about:blank")
        page.goto(url + "#s=method&disk=0&typed=1")
        page.get_by_role("button", name="Continue", exact=True).click()
        page.keyboard.press("F5")
        assert page.evaluate("selected === null && token === '' && owner === false")
        page.clock.run_for(6000)
        assert page.evaluate("screen") == "what"
        print(f"{width}px: ring 64px, numeral 16px; focus, Back, reset, zero, keyboard, mouse, refresh passed")
        page.close()
    browser.close()
