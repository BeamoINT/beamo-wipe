from pathlib import Path
import json,hashlib,subprocess,time
r=Path('/lab/windows11-native');d=json.loads((r/'assembly.json').read_text());results=[]
with (r/'guest.raw').open('rb') as whole:
 for row in d['partitions']:
  whole.seek(row['offset']);h=hashlib.sha256();other=hashlib.sha256();remaining=row['logical_size']
  with (r/row['source']).open('rb') as part:
   while remaining:
    n=min(8*1024**2,remaining);a=part.read(n);b=whole.read(n)
    assert len(a)==len(b)==n and a==b
    h.update(a);other.update(b);remaining-=n
  assert h.hexdigest()==other.hexdigest()
  results.append({'partition':row['source'],'bytes_compared':row['logical_size'],'sha256':h.hexdigest(),'equal':True})
subprocess.run(['sfdisk','--verify',str(r/'guest.raw')],check=True)
(r/'verified-assembly.json').write_text(json.dumps({'partitions':results,'gpt_verified':True,'completed_epoch':time.time()},indent=2)+'\n')
print('EVERY_PARTITION_BYTE_VERIFIED')
