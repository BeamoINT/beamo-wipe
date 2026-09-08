import json,pathlib,time,subprocess,sys
root=pathlib.Path('/lab/windows-11')
deadline=time.monotonic()+900
while time.monotonic()<deadline:
 rows=[]
 for s in (root/'diagnostics.jsonl').read_text(errors='replace').splitlines():
  try: rows.append(json.loads(s))
  except ValueError: pass
 good=[r for r in rows if r.get('setupInProgress')==0 and r.get('secureBoot') is True and 'Windows 11' in r.get('os',{}).get('Caption','')]
 if good:
  (root/'native-ready.json').write_text(json.dumps(good[-1],indent=2)+'\n')
  break
 time.sleep(5)
else: raise RuntimeError('No native Windows 11 readiness proof in bounded wait')
subprocess.run([sys.executable,'/lab/setup/screen-win11.py'],check=True)
import shutil
shutil.copy('/tmp/usb-windows11.png',root/'normal-desktop.png')
base=[sys.executable,'/lab/harness/tools/usb_lab/windows_matrix.py','--qmp',str(root/'qmp'),'--probe',str(root/'probe'),'--product-image','/lab/product/dist/beamo-wipe-0.2.5-amd64.img']
with open('/lab/windows11-full.log','w') as f:
 rc=subprocess.run(base+['--output','/lab/windows11-full'],stdout=f,stderr=subprocess.STDOUT).returncode
print('FULL_MATRIX_EXIT',rc,flush=True)
if rc:
 with open('/lab/windows11-bot.log','w') as f:
  bot=subprocess.run(base+['--profiles','usb2-bot','usb3-bot','--output','/lab/windows11-bot'],stdout=f,stderr=subprocess.STDOUT).returncode
 print('INDEPENDENT_BOT_EXIT',bot,flush=True)
(root/'matrix-runner.json').write_text(json.dumps({'full_exit':rc,'bot_exit':bot if rc else None},indent=2)+'\n')
sys.exit(rc)
