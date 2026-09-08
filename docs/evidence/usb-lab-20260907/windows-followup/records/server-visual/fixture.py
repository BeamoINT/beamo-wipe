import sys,time,json,signal
from pathlib import Path
sys.path.insert(0,'/lab/harness/tools/usb_lab')
from windows_matrix import WindowsLab
from lab import QMP
out=Path('/lab/server-visual')
lab=WindowsLab('/lab/windows-2022/qmp','/lab/windows-2022/probe',out)
def stop(*args):raise KeyboardInterrupt('Visual fixture interrupted')
signal.signal(signal.SIGTERM,stop)
try:
 lab.image('visual','/lab/product/dist/beamo-wipe-0.2.5-amd64.img')
 lab.attach('visual','BEAMOBOOT')
 lab.wait_disk('BEAMOBOOT')
 result=lab.probe('product',serial='BEAMOBOOT')
 assert result['ok'],result
 lab.image('uasdiag')
 lab.attach('uasdiag','USBLABPROFILE2','usb3-uas')
 (out/'ready.json').write_text(json.dumps(result,indent=2)+'\n')
 lab.guest.close();lab.qmp.close()
 deadline=time.monotonic()+900
 while not (out/'done').exists() and time.monotonic()<deadline:time.sleep(1)
finally:
 lab.qmp.close()
 lab.qmp=QMP('/lab/windows-2022/qmp',out/'qmp-cleanup.jsonl')
 lab.close()
 (out/'cleanup.json').write_text(json.dumps({'scratch_removed':not lab.root.exists()})+'\n')
