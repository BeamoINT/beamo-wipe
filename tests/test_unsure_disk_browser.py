"""Real browser keyboard and semantics checks, using the fake gallery only."""
import shutil
import pytest
from beamo_wipe.gallery import gallery_html
from beamo_wipe import copy as C


@pytest.mark.parametrize('size', [(1024, 740), (1280, 820)])
def test_unsure_browser_keyboard_and_reset(tmp_path, size):
    api = pytest.importorskip('playwright.sync_api')
    chrome = shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome:
        pytest.skip('Chrome unavailable')
    html = tmp_path / 'index.html'
    html.write_text(gallery_html())
    with api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': size[0], 'height': size[1]})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(html.as_uri() + '#s=pick&disk=0')
        unsure = page.get_by_role('button', name=C.DISK_HELP_BUTTON, exact=True)
        page.evaluate('window.oldPick = document.querySelector(".card.pickable")')
        unsure.focus()
        page.keyboard.press('Enter')
        page.evaluate('window.oldPick.click()')
        reader = page.get_by_role('region', name='Identify the disk', exact=True)
        assert reader.text_content() == C.DISK_HELP_TEXT
        assert reader.evaluate('(el) => el === document.activeElement')
        page.keyboard.press('PageDown')
        page.keyboard.press('Enter')
        assert page.evaluate('screen') == 'disk_help'
        assert page.evaluate('selected') is None
        page.keyboard.press('Tab')
        page.keyboard.press('Shift+Tab')
        page.keyboard.press('Escape')
        assert page.evaluate('screen') == 'pick'
        assert page.get_by_role('button', name='Continue', exact=True).is_disabled()
        assert unsure.evaluate('(el) => el === document.activeElement')
        page.keyboard.press('Space')
        assert page.evaluate('screen') == 'disk_help'
        page.evaluate('reportWanted = true')
        page.get_by_role('button', name=C.DISK_HELP_STOP).click()
        assert page.evaluate('screen') == 'shutdown_confirm'
        page.keyboard.press('Escape')
        assert page.evaluate('screen') == 'disk_help'
        page.goto(html.as_uri() + '#s=disk_help&disk=0&typed=1&ready=1')
        page.reload()
        assert page.evaluate('selected') is None
        assert page.evaluate('token') == ''
        assert page.evaluate('tLeft') == 5
        assert not errors
        browser.close()
