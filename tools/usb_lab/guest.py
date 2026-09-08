#!/usr/bin/env python3
"""Serial-only probe for disposable Linux guests; never install on a real PC."""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import time


def run(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def inventory():
    run('udevadm', 'settle', '--timeout=15')
    disks = json.loads(run('lsblk', '-Jb', '--tree', '-o', 'PATH,TYPE,TRAN,SERIAL,SIZE,RO,RM,FSTYPE,LABEL,MOUNTPOINTS'))['blockdevices']
    for disk in disks:
        disk['udev'] = run('udevadm', 'info', '--query=property', '--name', disk['path']).splitlines()
    usb = []
    for p in pathlib.Path('/sys/bus/usb/devices').iterdir():
        if (p / 'idVendor').exists():
            usb.append({k: (p / k).read_text().strip() for k in ('idVendor', 'idProduct', 'speed', 'product', 'serial') if (p / k).exists()})
    return {'disks': disks, 'usb': usb, 'kernel': run('uname', '-r')}


def target(serial):
    matches = [d for d in inventory()['disks'] if d.get('serial') == serial]
    if len(matches) != 1:
        raise ValueError('USB identity absent or ambiguous')
    d = matches[0]
    if d['tran'] != 'usb' or d['type'] != 'disk' or not re.fullmatch(r'/dev/sd[a-z]+', d['path']):
        raise ValueError('Not a USB disk')
    return d


def execute(req, notify=None):
    action = req['action']
    if action == 'inventory':
        return inventory()
    d = target(req['serial'])
    if action in ('read', 'write', 'slow-write'):
        if not re.fullmatch(r'USBLAB[A-Z0-9]+', req['serial']) or d['size'] != 64 * 1024**2:
            raise ValueError('Only the exact 64 MiB USBLAB scratch fixture permits raw I/O')
        flags = os.O_RDONLY if action == 'read' else os.O_RDWR | os.O_SYNC
        fd = os.open(d['path'], flags)
        try:
            if action == 'read':
                return {'sha256': hashlib.sha256(os.pread(fd, 4096, 8 * 1024**2)).hexdigest()}
            data = b'USBLAB-WRITE\n'.ljust(4096, b'!')
            for i in range(512 if action == 'slow-write' else 1):
                if os.pwrite(fd, data, 8 * 1024**2 + i * 4096) != len(data):
                    raise OSError('short write')
                os.fsync(fd)
                if action == 'slow-write' and i == 0 and notify:
                    notify({'event': 'write-started'})
                if action == 'slow-write':
                    time.sleep(.02)
            return {'written_sha256': hashlib.sha256(data).hexdigest()}
        finally:
            os.close(fd)
    if action == 'product':
        # Product media is always mounted read-only for the desktop check.
        parts = [p for p in d.get('children', []) if p['type'] == 'part']
        if len(parts) != 1:
            raise ValueError('Product media must have exactly one partition')
        mount = '/run/usblab-product'
        pathlib.Path(mount).mkdir(exist_ok=True)
        run('mount', '-o', 'ro', parts[0]['path'], mount)
        try:
            root = pathlib.Path(mount)
            manifest = json.loads((root / 'desktop-build.json').read_text())
            hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in manifest['files']}
            if hashes != manifest['files']:
                raise ValueError('Packaged launcher hashes differ')
            result = subprocess.run([str(root / 'Start Beamo Wipe Linux'), '--check-json'], capture_output=True, text=True, timeout=45)
            return {'hashes': hashes, 'check': json.loads(result.stdout), 'exit_code': result.returncode}
        finally:
            run('umount', mount)
    raise ValueError('Unknown probe action')


def main():
    with open('/dev/virtio-ports/org.beamo.usblab', 'r+b', buffering=0) as channel:
        while True:
            line = bytearray()
            while not line.endswith(b'\n'):
                chunk = channel.read(1)
                if not chunk:
                    time.sleep(.1)
                    continue
                line.extend(chunk)
                if len(line) > 65536:
                    raise ValueError('Oversized request')
            try:
                def notify(event):
                    channel.write(json.dumps(event).encode() + b'\n')
                response = {'ok': True, 'result': execute(json.loads(line), notify)}
            except Exception as exc:
                response = {'ok': False, 'error': type(exc).__name__, 'message': str(exc), 'errno': getattr(exc, 'errno', None)}
            channel.write(json.dumps(response).encode() + b'\n')


if __name__ == '__main__':
    main()
