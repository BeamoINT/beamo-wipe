from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,args=['--no-sandbox'])
 for width in (1024,390):
  page=b.new_page(viewport={'width':width,'height':900})
  page.goto('file:///home/box/beamo-wipe/web-preview/index.html#s=method&disk=0')
  card=page.locator('.identity')
  before=card.inner_text()
  assert 'Samsung' in before and '256 GB' in before
  page.locator('#more').click()
  assert '/dev/' in card.inner_text()
  for method in ('extra','quick_zero','everyday'):
   page.locator('[data-id='+method+']').click()
   assert before in card.inner_text()
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
  page.screenshot(path=f'/tmp/method-summary/after-web-{width}.png',full_page=True)
  page.evaluate("document.body.style.zoom = '1.5'")
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
  page.close()
 b.close()
print('Browser identity, disclosure, method continuity, and overflow checks passed at 1024 and 390 pixels.')
