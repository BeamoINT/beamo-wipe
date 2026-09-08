import sys,time
sys.path.insert(0,'/lab/harness/tools/usb_lab')
from lab import QMP
q=QMP('/lab/windows-11/qmp')
keys=sys.argv[1].split('-')
for code in keys:q.call('input-send-event',events=[{'type':'key','data':{'down':True,'key':{'type':'qcode','data':code}}}])
time.sleep(.2)
for code in reversed(keys):q.call('input-send-event',events=[{'type':'key','data':{'down':False,'key':{'type':'qcode','data':code}}}])
q.close()
