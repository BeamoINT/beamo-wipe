import json,pathlib,subprocess,urllib.request,datetime
r=pathlib.Path('/private/tmp/beamo-usb-kvm-0907'); constraint='constraints/compute.disableNestedVirtualization'
def read(effective=False):
 args=['gcloud','resource-manager','org-policies','describe',constraint,'--project=beamo-wipe','--format=json']
 if effective:args.append('--effective')
 return json.loads(subprocess.check_output(args,text=True))
before=json.loads((r/'policy-before.json').read_text()); applied=json.loads((r/'policy-applied.json').read_text())
assert 'booleanPolicy' not in before
current=read();(r/'policy-before-restore.json').write_text(json.dumps(current,indent=2)+'\n')
assert current['etag']==applied['etag'] and current.get('booleanPolicy')=={}, 'Policy changed since our exception; reconcile instead of overwriting'
token=subprocess.check_output(['gcloud','auth','print-access-token'],text=True).strip()
req=urllib.request.Request('https://cloudresourcemanager.googleapis.com/v1/projects/beamo-wipe:clearOrgPolicy',data=json.dumps({'constraint':constraint,'etag':current['etag']}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(req,timeout=60) as response: result=json.load(response)
assert result=={}
local=read();effective=read(True)
(r/'policy-restored-local.json').write_text(json.dumps(local,indent=2)+'\n')
(r/'policy-restored-effective.json').write_text(json.dumps(effective,indent=2)+'\n')
assert 'booleanPolicy' not in local and effective['booleanPolicy']['enforced'] is True
(r/'policy-restoration.json').write_text(json.dumps({'restored_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'removed_only_our_project_override':True,'etag_checked_by_server':current['etag'],'inherited_enforcement_restored':True},indent=2)+'\n')
print('PRIOR_INHERITED_POLICY_RESTORED_AND_VERIFIED')
