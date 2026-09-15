import sys
from pathlib import Path
from PIL import ImageGrab
from playwright.sync_api import sync_playwright
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.ui.tk_wizard import TkWizard
from beamo_wipe.models import Screen
from test_tk_runtime import _drive_to
out = Path('/tmp/beamo-77')
out.mkdir(parents=True, exist_ok=True)
phase = sys.argv[1]
w = make_demo_wizard()
a = TkWizard(w)
a.root.geometry('1280x820+0+0')
_drive_to(w,a,Screen.LAST_CHANCE)
a.root.update()
ImageGrab.grab().crop((0,0,1280,820)).save(out / f'{phase}-tk.png')
a._teardown()
with sync_playwright() as p:
 b=p.chromium.launch(args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1280,'height':820})
 page.goto(Path('web-preview/index.html').resolve().as_uri()+'#s=last&disk=0&typed=1')
 page.screenshot(path=str(out/f'{phase}-web.png'),full_page=True)
 b.close()
