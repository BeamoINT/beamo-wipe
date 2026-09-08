import sys
from pathlib import Path
sys.path.insert(0,'/lab/harness/tools/usb_lab')
from lab import QMP
from PIL import Image
p=Path('/lab/windows-11')
assert (p/'qmp').is_socket()
q=QMP(p/'qmp');q.call('screendump',filename=str(p/'screen.ppm'));q.close()
Image.open(p/'screen.ppm').save('/tmp/usb-windows11.png')
