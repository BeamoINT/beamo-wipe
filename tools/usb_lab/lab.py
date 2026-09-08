#!/usr/bin/env python3
"""Reusable QMP USB lab. Raw host devices and external writable disks are forbidden."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import stat
import sys
import subprocess
import tempfile
import threading
import time


PROFILES = {
    'usb2-bot': ('usb-ehci', 'usb-storage'),
    'usb3-bot': ('qemu-xhci', 'usb-storage'),
    'usb3-uas': ('qemu-xhci', 'usb-uas'),
}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def regular(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Only regular files without symlink components are accepted')
    if path.stat().st_nlink != 1:
        raise ValueError('Hard-linked backing files are forbidden')
    return path


class JsonSocket:
    def __init__(self, path, timeout=180):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(timeout)
        end = time.monotonic() + timeout
        while True:
            try:
                self.sock.connect(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() > end:
                    raise TimeoutError(str(path))
                time.sleep(.2)
        self.file = self.sock.makefile('rwb', buffering=0)

    def read(self):
        line = self.file.readline(1024**2)
        if not line or len(line) >= 1024**2:
            raise RuntimeError('Missing or oversized JSON response')
        return json.loads(line)

    def send(self, obj):
        self.file.write(json.dumps(obj).encode() + b'\n')

    def close(self):
        self.file.close()
        self.sock.close()


class QMP(JsonSocket):
    def __init__(self, path, transcript=None):
        self.transcript = transcript
        super().__init__(path)
        if 'QMP' not in self.read():
            raise RuntimeError('Missing QMP greeting')
        self.events = []
        self.counter = 0
        self.call('qmp_capabilities')

    def read(self):
        msg = super().read()
        if self.transcript:
            with self.transcript.open('a') as log:
                log.write(json.dumps({'direction': 'receive', 'message': msg}) + '\n')
        return msg

    def send(self, msg):
        if self.transcript:
            with self.transcript.open('a') as log:
                log.write(json.dumps({'direction': 'send', 'message': msg}) + '\n')
        super().send(msg)

    def call(self, name, **args):
        self.counter += 1
        ident = self.counter
        self.send({'execute': name, 'arguments': args, 'id': ident})
        while True:
            msg = self.read()
            if 'event' in msg:
                self.events.append(msg)
                continue
            if msg.get('id') != ident:
                raise RuntimeError('Mismatched QMP response')
            if 'error' in msg:
                raise RuntimeError(msg['error'])
            return msg['return']


class Lab:
    def __init__(self, fixture, output, accelerator='tcg', firmware='uefi'):
        self.fixture = Path(fixture).resolve()
        self.output = Path(output).absolute()
        self.output.mkdir(parents=True, exist_ok=False)
        self.root = Path(tempfile.mkdtemp(prefix='usblab-', dir='/var/tmp'))
        if accelerator not in ('tcg', 'kvm'):
            raise ValueError('Unknown accelerator')
        self.accelerator = accelerator
        if firmware not in ('uefi', 'bios'):
            raise ValueError('Unknown firmware')
        self.firmware = firmware
        self.proc = None
        self.qmp = None
        self.guest = None
        self.records = []
        self.files = {}
        self.attached = {}
        self.usb_ports = {}
        self.backends = set()
        self.initial = {}
        self.attach_count = 0
        self.guest_events = []
        self.write_started = threading.Event()

    def image(self, name, source=None):
        if not re.fullmatch('[a-z][a-z0-9-]*', name):
            raise ValueError('Unsafe image name')
        path = self.root / (name + '.raw')
        with path.open('xb') as dest:
            if source:
                with regular(source).open('rb') as src:
                    shutil.copyfileobj(src, dest, 1024**2)
            else:
                dest.truncate(64 * 1024**2)
                dest.seek(0)
                dest.write(b'USBLAB DISPOSABLE FIXTURE\n')
        self.files[name] = regular(path)
        self.initial[name] = digest(path)
        return path

    def start(self):
        for name in ('kernel', 'initrd', 'root.ext4'):
            regular(self.fixture / name)
        root = self.image('guest-os', self.fixture / 'root.ext4')
        args = ['qemu-system-x86_64', '-machine', 'q35,accel='+self.accelerator, '-cpu', 'max', '-m', '2048', '-nic', 'none', '-display', 'none', '-no-reboot',
                '-kernel', str(self.fixture / 'kernel'), '-initrd', str(self.fixture / 'initrd'),
                '-append', 'root=/dev/vda rw console=ttyS0,115200 systemd.unit=multi-user.target',
                '-drive', f'file={root},format=raw,if=virtio', '-serial', f'file:{self.output}/serial.log',
                '-qmp', f'unix:{self.root}/qmp,server=on,wait=off',
                '-chardev', f'socket,id=probe,path={self.root}/probe,server=on,wait=off',
                '-device', 'virtio-serial-pci', '-device', 'virtserialport,chardev=probe,name=org.beamo.usblab',
                '-device', 'qemu-xhci,id=xhci', '-device', 'usb-ehci,id=ehci']
        if self.firmware == 'uefi':
            code = regular('/usr/share/OVMF/OVMF_CODE_4M.fd')
            variables = self.image('firmware-vars', '/usr/share/OVMF/OVMF_VARS_4M.fd')
            args += ['-drive', f'if=pflash,format=raw,readonly=on,file={code}', '-drive', f'if=pflash,format=raw,file={variables}']
        (self.output / 'command.json').write_text(json.dumps(args, indent=2))
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=(self.output / 'qemu.log').open('w'))
        self.qmp = QMP(self.root / 'qmp', self.output / 'qmp.jsonl')
        self.guest = JsonSocket(self.root / 'probe', timeout=300)
        self.probe('inventory')

    def probe(self, action, **kwargs):
        self.guest.send({'action': action, **kwargs})
        while True:
            response = self.guest.read()
            if 'event' not in response:
                return response
            self.guest_events.append(response)
            if response['event'] == 'write-started':
                self.write_started.set()

    def wait_disk(self, serial, count=1):
        end = time.monotonic() + 40
        while time.monotonic() < end:
            result = self.probe('inventory')
            if not result['ok']:
                raise RuntimeError(result)
            matches = [d for d in result['result']['disks'] if d.get('serial') == serial]
            if len(matches) == count:
                return result['result']
            time.sleep(.3)
        (self.output / 'enumeration-timeout.json').write_text(json.dumps(result, indent=2))
        raise TimeoutError(f'Expected {count} USB devices with serial {serial}')

    def attach(self, name, serial, profile='usb3-bot', readonly=False, fault=False):
        path = regular(self.files[name])
        if path.parent != self.root or name in self.attached:
            raise ValueError('Unowned or already attached backing')
        controller, device = PROFILES[profile]
        backend = {'driver': 'file', 'filename': str(path)}
        if fault:
            backend = {'driver': 'blkdebug', 'image': backend, 'inject-error': [{'event': 'read_aio', 'errno': 5, 'sector': 16384, 'once': False, 'immediately': True}]}
        bus = 'ehci.0' if controller == 'usb-ehci' else 'xhci.0'
        used = {port for existing_bus, port in self.usb_ports.values() if existing_bus == bus}
        port = next((str(n) for n in range(1, 5) if str(n) not in used), None)
        if port is None:
            raise RuntimeError('No reserved direct USB root port remains')
        self.qmp.call('blockdev-add', **{'driver': 'raw', 'node-name': name, 'read-only': readonly, 'file': backend})
        self.backends.add(name)
        self.attach_count += 1
        capture = {} if name == 'product' else {'pcap': str(self.output / f'{self.attach_count}-{name}.pcap')}
        try:
            if device == 'usb-storage':
                self.qmp.call('device_add', driver=device, id=name, drive=name, bus=bus, port=port, serial=serial, removable=True, **capture)
            else:
                self.qmp.call('device_add', driver=device, id=name, bus=bus, port=port, serial=serial, **capture)
            # Track ownership before any later realization step can fail.
            self.attached[name] = profile
            self.usb_ports[name] = (bus, port)
            if device != 'usb-storage':
                self.qmp.call('device_add', driver='scsi-hd', id=name+'-lun', bus=name+'.0', drive=name, serial=serial, removable=True)
                self.qmp.call('qom-set', path='/machine/peripheral/'+name, property='attached', value=True)
        except BaseException:
            if name in self.attached:
                self.detach(name)
            else:
                self.qmp.call('blockdev-del', **{'node-name': name})
                self.backends.remove(name)
            raise

    def detach(self, name):
        self.qmp.call('device_del', id=name)
        # QMP success acknowledges the request, not completion. Wait for the
        # DEVICE_DELETED event before releasing or reusing the backing node.
        end = time.monotonic() + 30
        while time.monotonic() < end:
            self.qmp.call('query-status')
            if any(e['event'] == 'DEVICE_DELETED' and e.get('data', {}).get('device') == name for e in self.qmp.events):
                self.qmp.events = [e for e in self.qmp.events if e.get('data', {}).get('device') != name]
                self.qmp.call('blockdev-del', **{'node-name': name})
                del self.attached[name]
                del self.usb_ports[name]
                self.backends.remove(name)
                return
            time.sleep(.1)
        raise TimeoutError('USB unplug completion was not observed')

    def record(self, name, value):
        self.records.append({'case': name, 'evidence': value})
        (self.output / 'progress.json').write_text(json.dumps(self.records, indent=2))
        print('PASS '+name, flush=True)

    def matrix(self, product):
        self.image('canary')
        self.attach('canary', 'USBLABCANARY')
        self.wait_disk('USBLABCANARY')
        for i, profile in enumerate(PROFILES):
            name = f'profile{i}'
            serial = f'USBLABPROFILE{i}'
            self.image(name)
            self.attach(name, serial, profile)
            state = self.wait_disk(serial)
            disk = next(d for d in state['disks'] if d.get('serial') == serial)
            assert disk['tran'] == 'usb' and disk['rm'] and not disk['ro'], disk
            assert any('ID_BUS=usb' == p for p in disk['udev']), disk
            result = self.probe('write', serial=serial)
            assert result['ok'], result
            read = self.probe('read', serial=serial)
            assert read['ok'] and read['result']['sha256'] == result['result']['written_sha256'], read
            self.detach(name)
            self.wait_disk(serial, 0)
            # Host readback, after QEMU has released the file, is independent.
            with self.files[name].open('rb') as stream:
                stream.seek(8*1024**2)
                assert hashlib.sha256(stream.read(4096)).hexdigest() == read['result']['sha256']
            self.attach(name, serial, profile)
            self.wait_disk(serial)
            assert self.probe('read', serial=serial) == read
            self.detach(name)
            self.wait_disk(serial, 0)
            self.record(profile+'-enumerate-write-unplug-reconnect', {'inventory': state, 'readback': read})
        self.image('protected')
        self.attach('protected', 'USBLABPROTECTED', readonly=True)
        state = self.wait_disk('USBLABPROTECTED')
        assert next(d for d in state['disks'] if d.get('serial') == 'USBLABPROTECTED')['ro']
        result = self.probe('write', serial='USBLABPROTECTED')
        assert not result['ok'] and result['errno'] in (13, 30), result
        self.detach('protected')
        assert digest(self.files['protected']) == self.initial['protected']
        self.record('write-protection', result)
        for name in ('duplicatea', 'duplicateb'):
            self.image(name)
            self.attach(name, 'USBLABDUPLICATE')
        self.wait_disk('USBLABDUPLICATE', 2)
        result = self.probe('write', serial='USBLABDUPLICATE')
        assert not result['ok'] and 'ambiguous' in result['message'], result
        for name in ('duplicatea', 'duplicateb'):
            self.detach(name)
            assert digest(self.files[name]) == self.initial[name]
        self.record('duplicate-identity-refused', result)
        self.image('fault')
        self.attach('fault', 'USBLABFAULT', fault=True)
        self.wait_disk('USBLABFAULT')
        result = self.probe('read', serial='USBLABFAULT')
        assert not result['ok'] and result['errno'] == 5, result
        self.detach('fault')
        assert digest(self.files['fault']) == self.initial['fault']
        self.record('injected-read-io-error', result)
        self.image('disconnect')
        self.attach('disconnect', 'USBLABDISCONNECT')
        self.wait_disk('USBLABDISCONNECT')
        pending = []
        def write_request():
            pending.append(self.probe('slow-write', serial='USBLABDISCONNECT'))
        worker = threading.Thread(target=write_request)
        worker.start()
        assert self.write_started.wait(30), 'Guest did not acknowledge first flushed write'
        self.detach('disconnect')
        worker.join(45)
        assert not worker.is_alive() and len(pending) == 1 and not pending[0]['ok'], pending
        self.wait_disk('USBLABDISCONNECT', 0)
        # Linux can return ENOSPC after removal resets block-device capacity
        # to zero. Absence plus a flushed first write distinguishes removal
        # from an ordinary full filesystem. No filesystem is involved here.
        assert pending[0]['errno'] in (5, 6, 19, 28), pending
        assert digest(self.files['disconnect']) != self.initial['disconnect']
        self.attach('disconnect', 'USBLABREPLACEMENT')
        state = self.wait_disk('USBLABREPLACEMENT')
        refused = self.probe('write', serial='USBLABDISCONNECT')
        assert not refused['ok'] and 'absent' in refused['message'], refused
        self.detach('disconnect')
        self.record('unplug-during-io-and-replacement-identity', {'interrupted': pending[0], 'write_started': self.guest_events, 'stale_identity': refused, 'inventory': state})
        if product:
            self.image('product', product)
            for profile in PROFILES:
                self.attach('product', 'BEAMOBOOT', profile)
                self.wait_disk('BEAMOBOOT')
                result = self.probe('product', serial='BEAMOBOOT')
                assert result['ok'] and not result['result']['check']['ready'], result
                detail = result['result']['check']['detail']
                expected = 'not provided one exact boot entry' if self.firmware == 'uefi' else 'does not offer the supported automatic restart path'
                assert expected in detail, result
                self.detach('product')
                self.wait_disk('BEAMOBOOT', 0)
                assert digest(self.files['product']) == self.initial['product']
                self.record(profile+'-beamo-packaged-launcher', result)
        self.detach('canary')
        assert digest(self.files['canary']) == self.initial['canary']
        self.record('unrelated-canary-unchanged', {'sha256': self.initial['canary']})

    def close(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        for conn in (self.guest, self.qmp):
            if conn:
                conn.close()
        # Only this mkdtemp-created directory is removed, after QEMU exits.
        shutil.rmtree(self.root)


def main():
    def interrupted(signum, frame):
        signal.signal(signum, signal.SIG_IGN)
        raise KeyboardInterrupt('Lab interrupted; preserving failed-run evidence')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--product-image')
    parser.add_argument('--output', required=True)
    parser.add_argument('--firmware', choices=['uefi', 'bios'], default='uefi')
    parser.add_argument('--accelerator', choices=['tcg', 'kvm'], default='tcg')
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('Assertions must remain enabled for the test oracle')
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or Path('/Users/HP').exists():
        parser.error('Requires a disposable x86_64 Linux host')
    lab = Lab(args.fixture, args.output, args.accelerator, args.firmware)
    status = 'FAIL'
    try:
        lab.start()
        lab.matrix(args.product_image)
        status = 'PASS'
    finally:
        lab.close()
        receipt = {'schema_version': 1, 'status': status, 'accelerator': lab.accelerator, 'firmware': lab.firmware, 'cases': lab.records, 'qemu': subprocess.check_output(['qemu-system-x86_64', '--version'], text=True).splitlines()[0], 'fixture_sha256': {n: digest(Path(args.fixture)/n) for n in ('kernel', 'initrd', 'root.ext4')}, 'product_sha256': digest(args.product_image) if args.product_image else None, 'scratch_removed': not lab.root.exists(), 'qemu_exited': lab.proc is None or lab.proc.poll() is not None, 'packet_captures': {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size} for p in lab.output.glob('*.pcap')}}
        (lab.output / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__':
    main()
