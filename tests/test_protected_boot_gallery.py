# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser presentation uses fake payloads only; no device or wipe access."""
import pytest
from beamo_wipe.gallery import gallery_html


@pytest.mark.parametrize("scenario,screen,count", [("happy", "pick", 1), ("empty", "empty", 1), ("blocked", "blocked", 0)])
def test_browser_protected_card_semantics(tmp_path, scenario, screen, count):
    playwright = pytest.importorskip("playwright.sync_api")
    html = tmp_path / "index.html"
    html.write_text(gallery_html())
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        except playwright.Error as exc:
            pytest.skip(f"Browser runtime unavailable: {exc}")
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 900})
            page.goto(html.as_uri() + f"#scenario={scenario}&s={screen}")
            card = page.locator(".card.boot")
            assert card.count() == count
            if not count:
                assert page.locator(".card.pickable").count() == 0
                return
            assert card.get_attribute("role") == "region"
            assert "protected, cannot be erased" in card.get_attribute("aria-label")
            assert not card.get_attribute("tabindex")
            assert "BEAMOUSB001" in card.inner_text()
            assert "BEAMOUSB001" not in page.locator(".inventory-reader").inner_text()
            card.click()
            assert page.locator(".card.pickable.sel").count() == 0
            page.evaluate('P.disks.find(d => d.isBoot).name = "MODEL".repeat(60); P.disks.find(d => d.isBoot).serial = "SERIAL".repeat(60); draw()')
            assert "SERIAL" * 60 in card.inner_text()
            assert card.evaluate("e => e.scrollWidth <= e.clientWidth + 2")
        finally:
            browser.close()
