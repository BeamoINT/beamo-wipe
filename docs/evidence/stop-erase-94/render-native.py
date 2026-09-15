import sys, time
from pathlib import Path
from PIL import ImageGrab
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe import copy as C
from test_result_presentations import CASES, case_evidence
out=Path("docs/evidence/stop-erase-94")
for toolkit in ("tk","gtk"):
 for state in ("confirm","stopping","stopped","unconfirmed"):
  w=make_demo_wizard()
  w.selected=w.selectable[0]
  w.screen=Screen.WORKING
  if state=="confirm": w.stop_confirmation=object()
  if state=="stopping": w.screen=Screen.STOPPING
  if state=="unconfirmed": w.error=C.VIEWS["stop_unconfirmed"].announcement
  if state=="stopped": w=case_evidence(CASES[6])[0]
  if toolkit=="tk":
   from beamo_wipe.ui.tk_wizard import TkWizard
   a=TkWizard(w); a.root.geometry("1024x740+0+0");a._draw();a.root.update()
   ImageGrab.grab().crop((0,0,1024,740)).save(out/f"after-{toolkit}-{state}.png")
   a._teardown()
  else:
   from beamo_wipe.ui.accessible_wizard import AccessibleWizard,Gtk,Gdk
   a=AccessibleWizard(w);a.window.resize(1024,740);a.window.show_all()
   for _ in range(20):
    while Gtk.events_pending(): Gtk.main_iteration_do(False)
    time.sleep(.02)
   width,height=a.window.get_size()
   Gdk.pixbuf_get_from_window(a.window.get_window(),0,0,width,height).savev(str(out/f"after-{toolkit}-{state}.png"),"png",[],[])
   a.close()
