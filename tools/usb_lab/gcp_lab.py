#!/usr/bin/env python3
"""Create/delete a dedicated private GCP lab; resource state is an explicit receipt."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def command(*args):
    return subprocess.check_output(['gcloud', *args, '--quiet', '--format=json'], text=True)


def save(path, state):
    path.write_text(json.dumps(state, indent=2)+'\n')


def create(args):
    state_path = Path(args.state).absolute()
    if state_path.exists():
        raise ValueError('State exists; inspect it instead of overwriting')
    name = args.name
    if not re.fullmatch(r'beamo-usb-[a-z0-9-]{1,30}', name):
        raise ValueError('Use a dedicated beamo-usb- prefix')
    state = {'project': args.project, 'name': name, 'zone': args.zone, 'region': args.zone.rsplit('-', 1)[0], 'created': [], 'status': 'CREATING'}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.touch(mode=0o600, exist_ok=False)
    save(state_path, state)
    p, r = '--project='+args.project, '--region='+state['region']
    operations = [
        ('network', ['compute', 'networks', 'create', name, p, '--subnet-mode=custom']),
        ('subnet', ['compute', 'networks', 'subnets', 'create', name, p, r, '--network='+name, '--range='+args.subnet_range, '--enable-private-ip-google-access']),
        ('router', ['compute', 'routers', 'create', name, p, r, '--network='+name]),
        ('nat', ['compute', 'routers', 'nats', 'create', 'lab-egress', p, r, '--router='+name, '--nat-all-subnet-ip-ranges', '--auto-allocate-nat-external-ips']),
        ('firewall', ['compute', 'firewall-rules', 'create', name+'-iap', p, '--network='+name, '--allow=tcp:22', '--source-ranges=35.235.240.0/20']),
        ('instance', ['compute', 'instances', 'create', name, p, '--zone='+args.zone, '--machine-type=n2-standard-8', '--image='+args.image, '--image-project=debian-cloud', '--boot-disk-size=100GB', '--boot-disk-type=pd-balanced', '--subnet='+name, '--no-address', '--no-service-account', '--no-scopes', '--max-run-duration=10800s', '--instance-termination-action=DELETE', '--metadata=block-project-ssh-keys=TRUE', '--metadata-from-file=startup-script='+str(Path(__file__).with_name('host_setup.sh'))]),
    ]
    try:
        for kind, operation in operations:
            result = json.loads(command(*operation))
            state['created'].append(kind)
            state.setdefault('resources', {})[kind] = result
            if kind == 'instance':
                state['instance_id'] = result[0]['id']
            save(state_path, state)
        state['status'] = 'READY'
    except Exception:
        state['status'] = 'CREATE_FAILED_REQUIRES_CLEANUP'
        raise
    finally:
        save(state_path, state)


def destroy(args):
    path = Path(args.state)
    state = json.loads(path.read_text())
    name = state['name']
    if not re.fullmatch(r'beamo-usb-[a-z0-9-]{1,30}', name):
        raise ValueError('Invalid lab state')
    p = '--project='+state['project']
    r = '--region='+state['region']
    z = '--zone='+state['zone']
    instances = json.loads(command('compute', 'instances', 'list', p, '--filter=name='+name))
    exact = [i for i in instances if i['name'] == name]
    if exact:
        if len(exact) != 1 or str(exact[0]['id']) != str(state.get('instance_id')):
            raise ValueError('Instance identity differs; refuse deletion')
        command('compute', 'instances', 'delete', name, p, z)
    operations = [
        ('nat', ['compute', 'routers', 'nats', 'delete', 'lab-egress', p, r, '--router='+name]),
        ('router', ['compute', 'routers', 'delete', name, p, r]),
        ('firewall', ['compute', 'firewall-rules', 'delete', name+'-iap', p]),
        ('subnet', ['compute', 'networks', 'subnets', 'delete', name, p, r]),
        ('network', ['compute', 'networks', 'delete', name, p]),
    ]
    for kind, operation in operations:
        if kind in state['created'] and kind not in state.get('deleted', []):
            check_kind = 'router' if kind == 'nat' else kind
            if kind == 'nat':
                describe = ['compute', 'routers', 'describe', name, p, r]
            else:
                describe = operation.copy()
                describe[describe.index('delete')] = 'describe'
            current = json.loads(command(*describe))
            original = state.get('resources', {}).get(check_kind)
            if isinstance(original, list):
                original = original[0]
            if not original or str(current.get('id')) != str(original.get('id')):
                raise ValueError('Cloud resource identity differs: '+check_kind)
            command(*operation)
            state.setdefault('deleted', []).append(kind)
            save(path, state)
    absent = {}
    for resource in ('instances', 'disks', 'firewall-rules', 'routers', 'networks', 'networks subnets'):
        rows = json.loads(command('compute', *resource.split(), 'list', p, '--filter=name~^'+name+'($|-)'))
        absent[resource] = rows
        if rows:
            raise RuntimeError('Lab resources remain: '+resource)
    state['cleanup'] = absent
    state['status'] = 'CLEANUP_VERIFIED'
    save(path, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'destroy'])
    parser.add_argument('--state', required=True)
    parser.add_argument('--name', default='beamo-usb-lab')
    parser.add_argument('--project', default='beamo-wipe')
    parser.add_argument('--zone', default='us-central1-a')
    parser.add_argument('--image', default='debian-12-bookworm-v20260902')
    parser.add_argument('--subnet-range', default='10.89.19.0/28')
    args = parser.parse_args()
    (create if args.action == 'create' else destroy)(args)


if __name__ == '__main__':
    main()
