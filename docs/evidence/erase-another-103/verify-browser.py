"""Fake browser workflow. Run after BEAMO_WIPE_NO_OPEN=1 ./preview --web."""
from pathlib import Path
import shutil
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1024, 'height': 740})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto((Path.cwd() / 'web-preview/index.html').as_uri() + '#s=done&disk=0')
    page.get_by_role('button', name='Erase another disk', exact=True).click()
    assert page.get_by_role('heading', name='Continue without saving this report?').is_visible()
    page.get_by_role('button', name='Keep session open', exact=True).click()
    page.get_by_role('button', name='Erase another disk', exact=True).click()
    page.screenshot(path='docs/evidence/erase-another-103/browser-report-choice.png')
    page.get_by_role('button', name='Continue without saving', exact=True).click()
    assert page.evaluate('selected === null && !owner && token === "" && method === "everyday" && tLeft === 5')
    assert not errors, errors
    browser.close()
print('Browser report guard, cancellation, and reset passed.')
