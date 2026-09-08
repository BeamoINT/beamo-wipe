"""Run the image builder's readback step on regular-file FAT32 fixtures only."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
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


@pytest.mark.parametrize('damage', [None, 'launcher', 'manifest', 'offset'])
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
        dest.seek(512 if damage == 'offset' else 1024**2)
        shutil.copyfileobj(source, dest)
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
