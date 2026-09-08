#!/usr/bin/env python3
"""Drive the Windows serial probe in an already provisioned disposable QEMU PC.

The caller owns the virtual PC lifecycle. All added USB backends are detached
before this script removes its scratch directory. It never stops another VM.
"""
import argparse
import json
import shutil
import signal
import sys
import time

from lab import Lab, PROFILES, QMP, JsonSocket, digest


class WindowsLab(Lab):
    def __init__(self, qmp, probe, output):
        super().__init__('.', output)
        try:
            self.qmp = QMP(qmp, self.output / 'qmp.jsonl')
            self.guest = JsonSocket(probe, timeout=180)
        except BaseException:
            if self.qmp:
                self.qmp.close()
            shutil.rmtree(self.root)
            raise

    def matrix(self, product, firmware='uefi', profiles=None):
        selected = tuple(PROFILES if profiles is None else profiles)
        if not selected or len(set(selected)) != len(selected) or any(p not in PROFILES for p in selected):
            raise ValueError('Choose distinct known USB profiles')
        self.record('windows-os', self.probe('inventory'))
        self.image('canary')
        self.attach('canary', 'USBLABCANARY')
        self.wait_disk('USBLABCANARY')
        for i, profile in enumerate(selected):
            name, serial = f'profile{i}', f'USBLABPROFILE{i}'
            self.image(name)
            self.attach(name, serial, profile)
            state = self.wait_disk(serial)
            disk = next(d for d in state['disks'] if d.get('serial') == serial)
            assert disk['transport'] == 'USB' and not disk['readonly'], disk
            write = self.probe('write', serial=serial)
            assert write['ok'], write
            read = self.probe('read', serial=serial)
            assert read['ok'] and read['result']['sha256'] == write['result']['sha256'], read
            self.detach(name)
            self.wait_disk(serial, 0)
            with self.files[name].open('rb') as f:
                import hashlib
                f.seek(8*1024**2)
                assert hashlib.sha256(f.read(4096)).hexdigest() == read['result']['sha256']
            self.attach(name, serial, profile)
            self.wait_disk(serial)
            assert self.probe('read', serial=serial) == read
            self.detach(name)
            self.wait_disk(serial, 0)
            self.record(profile+'-windows-write-unplug-reconnect', {'inventory': state, 'readback': read})
        self.image('protected')
        self.attach('protected', 'USBLABPROTECTED', readonly=True)
        state = self.wait_disk('USBLABPROTECTED')
        assert next(d for d in state['disks'] if d.get('serial') == 'USBLABPROTECTED')['readonly']
        assert self.probe('read', serial='USBLABPROTECTED')['ok']
        result = self.probe('write', serial='USBLABPROTECTED')
        assert not result['ok'], result
        self.detach('protected')
        assert digest(self.files['protected']) == self.initial['protected']
        self.record('windows-write-protection', {'inventory': state, 'refusal': result})
        if product:
            self.image('product', product)
            for profile in selected:
                self.attach('product', 'BEAMOBOOT', profile)
                self.wait_disk('BEAMOBOOT')
                # Disk arrival precedes volume arrival on Windows.
                end = time.monotonic()+45
                while True:
                    result = self.probe('product', serial='BEAMOBOOT')
                    if result['ok'] or time.monotonic() > end:
                        break
                    time.sleep(1)
                assert result['ok'] and not result['result']['check']['ready'], result
                expected = 'not provided one exact boot entry' if firmware == 'uefi' else 'does not offer the supported automatic restart path'
                assert expected in result['result']['check']['detail'], result
                self.detach('product')
                self.wait_disk('BEAMOBOOT', 0)
                self.record(profile+'-windows-beamo-packaged-launcher', result)
        self.detach('canary')
        assert digest(self.files['canary']) == self.initial['canary']
        self.record('windows-canary-unchanged', {'sha256': self.initial['canary']})

    def close(self):
        # On failure, retain backing files if device removal cannot be proved.
        try:
            for name in list(self.attached):
                self.detach(name)
            for name in list(self.backends):
                self.qmp.call('blockdev-del', **{'node-name': name})
                self.backends.remove(name)
        finally:
            self.guest.close()
            self.qmp.close()
        shutil.rmtree(self.root)


def main():
    def interrupted(signum, frame):
        signal.signal(signum, signal.SIG_IGN)
        raise KeyboardInterrupt('Lab interrupted; preserving failed-run evidence')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qmp', required=True)
    parser.add_argument('--probe', required=True)
    parser.add_argument('--product-image')
    parser.add_argument('--firmware', choices=['uefi', 'bios'], default='uefi', help='Actual firmware of the caller-owned guest; selects the specific expected launcher fallback')
    parser.add_argument('--profiles', nargs='+', choices=list(PROFILES), default=list(PROFILES), help='Explicit scope; defaults to all profiles, and every requested profile is recorded in the receipt')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('Test assertions must be enabled')
    lab = WindowsLab(args.qmp, args.probe, args.output)
    status = 'FAIL'
    try:
        lab.matrix(args.product_image, args.firmware, args.profiles)
        status = 'PASS'
    finally:
        after = {name: digest(path) for name, path in lab.files.items() if name != 'guest-os'}
        try:
            lab.close()
        except BaseException:
            status = 'FAIL'
            raise
        finally:
            receipt = {'status': status, 'requested_profiles': args.profiles, 'firmware': args.firmware, 'cases': lab.records, 'product_source_sha256': digest(args.product_image) if args.product_image else None, 'images_before_sha256': lab.initial, 'images_after_sha256': after, 'scratch_removed': not lab.root.exists(), 'packet_captures': {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size} for p in lab.output.glob('*.pcap')}}
            (lab.output / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__':
    main()
