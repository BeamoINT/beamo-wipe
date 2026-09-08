import struct,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parent/'windows-results-2022-2'
results={}
for name in ('2-profile0.pcap','4-profile1.pcap','6-profile2.pcap'):
 data=(root/name).read_bytes();assert data[:4]==b'\xd4\xc3\xb2\xa1';assert struct.unpack_from('<I',data,20)[0]==220
 pos=24; records=[]; descriptors=[]; requests=[];previous=None
 while pos<len(data):
  sec,usec,n,original=struct.unpack_from('<IIII',data,pos);p=data[pos+16:pos+16+n];pos+=16+n
  assert len(p)==n and n>=64
  event=chr(p[8]);typ=p[9]
  records.append((event,typ))
  if event=='S' and typ==2:
   setup=struct.unpack_from('<BBHHH',p,40);requests.append(dict(zip(('bmRequestType','bRequest','wValue','wIndex','wLength'),setup)));previous=setup
  if event=='C' and typ==2 and previous and previous[1]==6 and previous[2]==0x100 and len(p)>=82:
   desc=p[64:82];descriptors.append({'bcdUSB':hex(struct.unpack_from('<H',desc,2)[0]),'vendor':hex(struct.unpack_from('<H',desc,8)[0]),'product':hex(struct.unpack_from('<H',desc,10)[0]),'descriptor_hex':desc.hex()})
 results[name]={'sha256':hashlib.sha256(data).hexdigest(),'capture_records':len(records),'bulk_submissions':sum(x==('S',3) for x in records),'set_configuration_submissions':sum(r['bRequest']==9 and r['bmRequestType']==0 for r in requests),'device_descriptors':descriptors}
 if name=='6-profile2.pcap': results[name]['control_requests']=requests
out=root.parent/'protocol-observations.json'
out.write_text(json.dumps({'format_reference':'https://docs.kernel.org/usb/usbmon.html','scope':'QEMU-generated USB mmap captures; descriptor and request observations only, not physical signal or driver failure diagnosis','captures':results},indent=2)+'\n')
print(json.dumps(results,indent=2))
