import sys,json
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/"tools/usb_lab"))
import gcp_lab
original=gcp_lab.command
def command(*args):
 if args[:3]==("compute","instances","create"):
  args=(*args,"--enable-nested-virtualization")
 return original(*args)
gcp_lab.command=command
gcp_lab.main()
