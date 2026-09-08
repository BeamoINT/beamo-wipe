import sys,json,time,pathlib
sys.path.insert(0,'/lab/harness/tools/usb_lab')
from lab import QMP
q=QMP('/lab/windows-11/qmp')
rows=[{'device':r['device'],'stats':{k:r['stats'].get(k) for k in ('rd_bytes','wr_bytes','wr_operations','flush_operations','failed_rd_operations','failed_wr_operations')}} for r in q.call('query-blockstats') if r.get('device') in ('os','install')]
out={'epoch':time.time(),'kvm':q.call('query-kvm'),'status':q.call('query-status'),'blocks':rows};q.close()
with pathlib.Path('/lab/windows-11/host-progress.jsonl').open('a') as f:f.write(json.dumps(out)+'\n')
print(json.dumps(out))
