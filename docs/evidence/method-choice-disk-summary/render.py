import sys
sys.path[:0] = ['src', 'tests']
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.ui.tk_wizard import TkWizard
from beamo_wipe.models import Screen
from test_tk_runtime import _drive_to
from PIL import ImageGrab
w = make_demo_wizard()
a = TkWizard(w)
a.root.geometry('1024x740+0+0')
_drive_to(w,a,Screen.METHOD)
a.root.update()
ImageGrab.grab().save(sys.argv[1])
a._teardown()
