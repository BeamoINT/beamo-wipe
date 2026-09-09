"""Real Chromium preview verification; requires Playwright and chromium."""
import json
from pathlib import Path
import shutil

from playwright.sync_api import sync_playwright

root = Path.cwd()
output = Path('/tmp/beamo-ui-browser')
output.mkdir(exist_ok=True)
url = (root / 'web-preview/index.html').as_uri()
sizes = [(390, 844), (800, 600), (1024, 740), (1280, 820), (1366, 768), (1920, 1080)]
states = ['splash', 'what', 'owner', 'pick', 'confirm', 'method', 'last',
          'working', 'done', 'advanced', 'limits', 'report_help', 'shutdown_confirm',
          'empty', 'blocked']
checks = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=shutil.which('chromium'),
                                         args=['--no-sandbox'])
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    for width, height in sizes:
        page.set_viewport_size({'width': width, 'height': height})
        for state in states:
            scenario = {'empty': 'empty', 'blocked': 'blocked'}.get(state, 'happy')
            page.goto(f'{url}?case={width}-{state}#s={state}&scenario={scenario}&disk=0&typed=1&pct=42')
            page.wait_for_timeout(100)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, state)
            for control in page.locator('.foot button:visible').all():
                control.scroll_into_view_if_needed()
                rect = control.bounding_box()
                assert rect['x'] >= 0 and rect['x'] + rect['width'] <= width, (width, state, rect)
                # Chromium scroll offsets round fractional CSS pixels.
                assert rect['y'] >= -1 and rect['y'] + rect['height'] <= height + 1, (width, state, rect)
            if state in ['pick', 'confirm', 'last', 'working', 'done']:
                assert page.locator('.dev').first.is_visible(), (width, state)
            page.screenshot(path=str(output / f'{width}-{state}.png'), full_page=True)
            checks.append({'width': width, 'height': height, 'state': state, 'passed': True})

    page.set_viewport_size({'width': 1024, 'height': 740})
    page.goto(f'{url}#s=pick&disk=0')
    row = page.locator('.card.pickable').nth(1)
    row.focus()
    row.press('Space')
    assert page.locator('.card.pickable').nth(1).evaluate('(el) => el === document.activeElement')
    assert page.locator('.card.pickable').nth(1).get_attribute('aria-pressed') == 'true'
    page.get_by_role('button', name='Continue', exact=True).click()
    page.locator('#tok').fill(page.evaluate('selected.token'))
    page.locator('#tok').press('Enter')
    page.get_by_role('button', name='Continue', exact=True).click()
    assert page.evaluate('screen') == 'last'
    assert 'Tab to Erase' in page.locator('#hint').inner_text()
    assert page.get_by_role('button', name='Erase now', exact=True).is_disabled()
    assert page.get_by_role('button', name='Back', exact=True).evaluate('(el) => el === document.activeElement')
    page.wait_for_timeout(5500)
    assert page.evaluate('screen') == 'last'
    assert page.get_by_role('button', name='Back', exact=True).evaluate('(el) => el === document.activeElement')
    assert page.locator('.countcap').inner_text().startswith('Nothing has started.')
    page.get_by_role('button', name='Erase now', exact=True).focus()
    page.keyboard.press('Enter')
    assert page.evaluate('screen') == 'working'
    page.wait_for_function('screen === "done"')
    assert 'Nothing on this computer was erased' in page.locator('#main').inner_text()
    assert not errors, errors
    browser.close()
print(json.dumps({'layouts': checks, 'keyboard_countdown_fake_completion': 'passed',
                  'javascript_errors': errors}, indent=2))
