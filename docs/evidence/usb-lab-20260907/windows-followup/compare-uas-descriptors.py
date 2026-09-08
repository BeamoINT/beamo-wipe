import pathlib,struct,hashlib,json
base=pathlib.Path('docs/evidence/usb-lab-20260907')
paths=['windows/linux-rootports/6-profile2.pcap','windows-followup/records/server-full/6-profile2.pcap','windows-followup/records/server-visual/2-uasdiag.pcap']
results=[]
for rel in paths:
 b=(base/rel).read_bytes(); assert b[:4]==b'\xd4\xc3\xb2\xa1' and struct.unpack_from('<I',b,20)[0]==220
 pos=24;pending={};configs=[];bulk=setting=records=0
 while pos<len(b):
  _,_,size,orig=struct.unpack_from('<IIII',b,pos);pos+=16;d=b[pos:pos+size];pos+=size; assert len(d)==size and size>=64 and size<=orig
  ident=struct.unpack_from('<Q',d)[0];kind=chr(d[8]);transfer=d[9];records+=1
  if kind=='S' and transfer==3: bulk+=1
  if kind=='S' and transfer==2:
   req=struct.unpack_from('<BBHHH',d,40);pending[ident]=req
   setting+=req[0]==0 and req[1]==9
  if kind=='C' and transfer==2:
   req=pending.pop(ident,None)
   if req and req[:3]==(128,6,512):
    payload=d[64:];actual_length=struct.unpack_from('<I',d,32)[0]
    assert len(payload)==actual_length and size==orig
    if len(payload)>=9 and len(payload)==struct.unpack_from('<H',payload,2)[0]:
     off=0;descs=[]
     while off<len(payload):
      length,typ=payload[off:off+2]; assert length>=2 and off+length<=len(payload)
      descs.append({'offset':off,'type':typ,'hex':payload[off:off+length].hex()});off+=length
     configs.append({'sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload),'hex':payload.hex(),'descriptors':descs})
 assert pos==len(b) and not pending and configs
 results.append({'capture':rel,'sha256':hashlib.sha256(b).hexdigest(),'records':records,'bulk_submissions':bulk,'set_configuration_submissions':setting,'complete_configuration_descriptors':configs})
allconfigs=[c['hex'] for r in results for c in r['complete_configuration_descriptors']]
out={'format_reference':'https://docs.kernel.org/usb/usbmon.html','scope':'Offline comparison of captured descriptors; not a Windows driver diagnosis or new runtime pass','all_full_configuration_bytes_identical':len(set(allconfigs))==1,'captures':results,'conclusion':'Successful Linux and failing Windows runs received identical full UAS configuration descriptor bytes. Windows captures stop before SET_CONFIGURATION or bulk submissions. Windows-specific compatibility or start failure remains unresolved; this comparison does not validate every USB requirement.'}
assert out['all_full_configuration_bytes_identical']
assert results[0]['set_configuration_submissions']>0 and results[0]['bulk_submissions']>0
assert all(r['set_configuration_submissions']==0 and r['bulk_submissions']==0 for r in results[1:])
p=base/'windows-followup/uas-descriptor-comparison.json';p.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'identical_configuration_bytes':True,'capture_counts':[{k:v for k,v in r.items() if k not in ['complete_configuration_descriptors','sha256']} for r in results],'configuration_sha256':results[0]['complete_configuration_descriptors'][0]['sha256']}))
