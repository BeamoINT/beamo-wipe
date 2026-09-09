"""Run the image builder's readback step on regular-file FAT32 fixtures only."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import struct
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def verifier():
    source = (ROOT / 'scripts/build-usb-image.sh').read_text()
    return source.split("<<'PYVERIFY'\n", 1)[1].split('\nPYVERIFY\n', 1)[0]


@pytest.mark.parametrize('files', [{}, {'Start Beamo Wipe.exe': 'bad'},
                                 {'../unexpected': 'bad'}])
def test_incomplete_manifest_cannot_become_success_bundle(tmp_path, files):
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / 'desktop-build.json').write_text(json.dumps({'files': files}))
    image = tmp_path / 'test.img'
    image.write_bytes(b'not a filesystem')
    iso = tmp_path / 'source.iso'
    iso.write_bytes(b'fixture')
    result = subprocess.run([sys.executable, '-c', verifier(), str(tree), str(image), str(iso)],
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert 'exactly both desktop launchers' in result.stderr
    assert not image.with_suffix('.img.sha256').exists()
    assert not image.with_suffix('.img.json').exists()


@pytest.mark.parametrize('damage', [None, 'launcher', 'manifest', 'offset',
                                  'mbr-offset', 'mbr-size', 'mbr-active',
                                  'mbr-type', 'mbr-magic', 'mbr-signature',
                                  'mbr-extra-partition', 'trailing-data'])
def test_regular_file_fat32_roundtrip(tmp_path, damage):
    commands = [shutil.which(tool) for tool in ('mkfs.fat', 'mcopy', 'mtype')]
    if not all(commands):
        pytest.skip('regular-file FAT32 test requires dosfstools and mtools')
    tree = tmp_path / 'tree'
    tree.mkdir()
    payloads = {'Start Beamo Wipe.exe': b'MZ\x00fixture-windows',
                'Start Beamo Wipe Linux': b'\x7fELF\x00fixture-linux'}
    manifest = {'files': {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}}
    (tree / 'desktop-build.json').write_text(json.dumps(manifest))
    fat = tmp_path / 'volume.fat'
    with fat.open('xb') as stream:
        stream.truncate(64 * 1024**2)
    subprocess.run([commands[0], '-F', '32', str(fat)], check=True, capture_output=True)
    for name, data in {**payloads, 'desktop-build.json': (tree / 'desktop-build.json').read_bytes()}.items():
        copy = tmp_path / name
        if damage == 'launcher' and name.endswith('.exe'):
            data += b'changed'
        if damage == 'manifest' and name == 'desktop-build.json':
            data += b' '
        copy.write_bytes(data)
        subprocess.run([commands[1], '-i', str(fat), str(copy), '::/'], check=True, capture_output=True)
    image = tmp_path / 'test.img'
    with image.open('xb') as dest, fat.open('rb') as source:
        mbr = bytearray(512)
        mbr[440:444] = struct.pack('<I', 0x1234abcd)
        mbr[446:462] = struct.pack('<B3sB3sII', 0x80, b'\xfe\xff\xff', 0x0c,
                                    b'\xfe\xff\xff', 2048, fat.stat().st_size // 512)
        mbr[510:512] = b'\x55\xaa'
        if damage == 'mbr-offset':
            mbr[454:458] = struct.pack('<I', 4096)
        elif damage == 'mbr-size':
            mbr[458:462] = struct.pack('<I', 1)
        elif damage == 'mbr-active':
            mbr[446] = 0
        elif damage == 'mbr-type':
            mbr[450] = 0x83
        elif damage == 'mbr-magic':
            mbr[510:512] = b'\0\0'
        elif damage == 'mbr-signature':
            mbr[440:444] = bytes(4)
        elif damage == 'mbr-extra-partition':
            mbr[462:478] = mbr[446:462]
        dest.write(mbr)
        dest.seek(512 if damage == 'offset' else 1024**2)
        shutil.copyfileobj(source, dest)
        if damage == 'trailing-data':
            dest.write(b'unaccounted data')
    iso = tmp_path / 'source.iso'
    iso.write_bytes(b'fixture ISO binding; no boot claim')
    result = subprocess.run([sys.executable, '-c', verifier(), str(tree), str(image), str(iso)],
                            capture_output=True, text=True, check=False, timeout=30)
    if damage:
        assert result.returncode != 0
        assert not image.with_suffix('.img.json').exists()
        assert not image.with_suffix('.img.sha256').exists()
    else:
        assert result.returncode == 0, result.stderr
        receipt = json.loads(image.with_suffix('.img.json').read_text())
        assert receipt['sha256'] == hashlib.sha256(image.read_bytes()).hexdigest()
        assert receipt['iso_sha256'] == hashlib.sha256(iso.read_bytes()).hexdigest()


@pytest.mark.parametrize('suffix', ['.img.sha256', '.img.json'])
@pytest.mark.parametrize('kind', ['file', 'dangling-symlink'])
def test_builder_refuses_existing_success_sidecars(tmp_path, suffix, kind):
    # Execute the production preflight in a disposable repo with no real ISO.
    # Refusal must precede provenance checks, extraction, or output creation.
    import shlex
    from beamo_wipe import __version__
    script = tmp_path / 'scripts/build-usb-image.sh'
    script.parent.mkdir()
    source = (ROOT / 'scripts/build-usb-image.sh').read_text()
    # Test only output preflight: the real builder's Linux-only platform guard
    # is intentionally outside this regular-file test (which also runs on Mac).
    preflight = 'VERSION=' + source.split('VERSION=', 1)[1].split('TMP_IMAGE=', 1)[0]
    script.write_text('set -euo pipefail\nROOT=' + shlex.quote(str(tmp_path)) + '\n' + preflight)
    package = tmp_path / 'src/beamo_wipe'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text(f'__version__ = {__version__!r}\n')
    dist = tmp_path / 'dist'
    dist.mkdir()
    stem = f'beamo-wipe-{__version__}-amd64'
    (dist / (stem + '.iso')).write_bytes(b'fixture; must not be extracted')
    sidecar = dist / (stem + suffix)
    if kind == 'file':
        sidecar.write_bytes(b'previous receipt')
    else:
        sidecar.symlink_to('missing-receipt')
    result = subprocess.run(['bash', str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert 'Unused image and sidecar output paths are required' in result.stderr
    assert not (dist / (stem + '.img')).exists()
    if kind == 'file':
        assert sidecar.read_bytes() == b'previous receipt'
    else:
        assert sidecar.is_symlink() and not sidecar.exists()
