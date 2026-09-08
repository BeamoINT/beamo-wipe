from pathlib import Path
import subprocess,json,os,hashlib,time
root=Path('/lab/windows11-native')
assert root.is_dir() and not root.is_symlink()
GiB=1024**3; MiB=1024**2
starts=[2048,534528,567296]
sizes=[532480,32768,80*GiB//512-567296-2048]
whole=root/'guest.raw';ntfs=root/'windows.ntfs';efi=root/'efi.fat'
for p,size in ((whole,80*GiB),(ntfs,sizes[2]*512),(efi,sizes[0]*512)):
 with p.open('xb') as f:f.truncate(size)
 os.chmod(p,0o600)
 assert p.is_file() and p.stat().st_nlink==1 and p.stat().st_uid==0
layout='label: gpt\nunit: sectors\n\n'+''.join(f'start={start},size={size},type={kind},name="{name}"\n' for start,size,kind,name in zip(starts,sizes,['U','R','L'],['System','MSR','Windows']))
# Microsoft basic data uses its explicit GUID, not Linux's L alias.
layout=layout.replace('type=L','type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7').replace('type=R','type=E3C9E316-0B5C-4DB8-817D-F92DF00215AE')
subprocess.run(['sfdisk',str(whole)],input=layout,text=True,check=True)
partition=json.loads(subprocess.check_output(['sfdisk','--json',str(whole)]))
assert [(p['start'],p['size']) for p in partition['partitiontable']['partitions']]==list(zip(starts,sizes))
(root/'partition-layout.json').write_text(json.dumps(partition,indent=2)+'\n')
subprocess.run(['mkfs.vfat','-F','32','-n','SYSTEM',str(efi)],check=True)
subprocess.run(['mkntfs','-F','-Q','-s','512','-p',str(starts[2]),'-H','255','-S','63','-L','Windows',str(ntfs)],check=True)
subprocess.run(['wimlib-imagex','apply',str(root/'iso/sources/install.wim'),'1',str(ntfs),'--check','--strict-acls'],check=True)
# Copy only allocated extents from these private regular partition images.
copy_receipts=[]
with whole.open('r+b') as out:
 for source,start in ((efi,starts[0]),(ntfs,starts[2])):
  with source.open('rb') as inp:
   pos=0; copied=0; h=hashlib.sha256()
   while pos<source.stat().st_size:
    try: begin=os.lseek(inp.fileno(),pos,os.SEEK_DATA)
    except OSError as exc:
     if exc.errno==6:break
     raise
    end=os.lseek(inp.fileno(),begin,os.SEEK_HOLE)
    assert 0<=begin<end<=source.stat().st_size
    inp.seek(begin);out.seek(start*512+begin)
    remaining=end-begin
    while remaining:
     data=inp.read(min(8*MiB,remaining));assert data
     out.write(data);h.update(data);copied+=len(data);remaining-=len(data)
    pos=end
   out.flush();os.fsync(out.fileno())
   copy_receipts.append({'source':source.name,'offset':start*512,'logical_size':source.stat().st_size,'copied_allocated_bytes':copied,'allocated_bytes_sha256':h.hexdigest()})
(root/'assembly.json').write_text(json.dumps({'method':'wimlib native NTFS volume extraction; copied allocated extents into private GPT image','partitions':copy_receipts,'completed_epoch':time.time()},indent=2)+'\n')
print('NATIVE_IMAGE_APPLIED_AND_ASSEMBLED',flush=True)
