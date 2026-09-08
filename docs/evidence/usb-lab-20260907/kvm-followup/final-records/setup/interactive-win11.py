"""Run with python3 -i, only after Windows setup and the standalone matrix."""
import sys,time,json,subprocess,hashlib
from pathlib import Path
from PIL import Image
sys.path.insert(0,'/lab/harness/tools/usb_lab')
from windows_matrix import WindowsLab
from lab import digest
lab=WindowsLab('/lab/windows-11/qmp','/lab/windows-11/probe','/lab/windows-11/interactive')
plain={' ':'spc','.':'dot','/':'slash','\\':'backslash',';':'semicolon',"'":'apostrophe','-':'minus','=':'equal',',':'comma','[':'bracket_left',']':'bracket_right','`':'grave_accent','\n':'ret'}
shift={':':'semicolon','"':'apostrophe','_':'minus','+':'equal','(':'9',')':'0','!':'1','@':'2','#':'3','$':'4','%':'5','^':'6','&':'7','*':'8','?':'slash','<':'comma','>':'dot','|':'backslash','{':'bracket_left','}':'bracket_right'}
def combo(keys):
    codes=keys.split('-')
    for down,group in [(True,codes),(False,list(reversed(codes)))]:
        lab.qmp.call('input-send-event',events=[{'type':'key','data':{'down':down,'key':{'type':'qcode','data':c}}} for c in group])
        time.sleep(.1)
def type_text(text):
    for ch in text:
        key=('shift-'+ch.lower()) if ch.isupper() else ('shift-'+shift[ch] if ch in shift else plain.get(ch,ch))
        lab.qmp.call('human-monitor-command',**{'command-line':'sendkey '+key+' 30'})
        time.sleep(.06)
def screen(name):
    assert name.isascii() and all(c.isalnum() or c in '-_' for c in name)
    lab.qmp.call('screendump',filename='/lab/windows-11/screen.ppm')
    Image.open('/lab/windows-11/screen.ppm').save('/lab/windows-11/interactive/'+name+'.png')
    Image.open('/lab/windows-11/screen.ppm').save('/tmp/usb-windows11.png')
def run(command):
    combo('meta_l-r');time.sleep(1);type_text(command+'\n')
def finish():
    before=lab.initial.copy()
    after={n:digest(p) for n,p in lab.files.items()}
    lab.close()
    receipt={'scratch_removed':not lab.root.exists(),'attached_remaining':lab.attached,'backends_remaining':list(lab.backends),'images_before':before,'images_after':after,'cases':lab.records}
    Path('/lab/windows-11/interactive/receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('INTERACTIVE_USB_LAB_READY',flush=True)
