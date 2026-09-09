import sys, time
from pathlib import Path
sys.path[:0] = [str(Path.cwd()/'src'), str(Path.cwd()/'tests')]
import gi
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui.tk_wizard import TkWizard
from test_tk_runtime import _drive_to
out=Path('docs/evidence/ui-improvement-20260909/baseline')
out.mkdir(exist_ok=True)
for screen in [Screen.SPLASH,Screen.WHAT,Screen.OWNER,Screen.PICK,Screen.CONFIRM,Screen.METHOD,Screen.LAST_CHANCE,Screen.WORKING,Screen.DONE,Screen.ADVANCED,Screen.LIMITS,Screen.REPORT_HELP,Screen.CHECKING,Screen.STOPPING,Screen.REFRESHING,Screen.SHUTDOWN_CONFIRM,Screen.PICK_EMPTY,Screen.PICK_BLOCKED]:
    wiz=make_demo_wizard()
    app=TkWizard(wiz)
    app.root.geometry('1024x740+0+0')
    if app._after_id:
        app.root.after_cancel(app._after_id)
        app._after_id=None
    if screen not in [Screen.SPLASH, Screen.WHAT, Screen.OWNER]:
        _drive_to(wiz,app,Screen.CONFIRM)
    wiz.screen=screen
    app._draw()
    for _ in range(10):
        app.root.update()
        time.sleep(.02)
    Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(),0,0,1024,740).savev(str(out/f'tk-{screen.value}.png'),'png',[],[])
    app._teardown()
print(out)
