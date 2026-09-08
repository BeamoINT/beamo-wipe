"""Cross-platform contracts with fake inventories; never enumerate host disks."""

import json
from pathlib import Path

import pytest

from beamo_wipe import app, discover, safety
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner


FIXTURE = Path(__file__).parent / 'fixtures' / 'lsblk_same_size.json'


def forbidden(*args, **kwargs):
    pytest.fail('fixture consulted host inventory or kernel boot metadata')


def test_injected_inventory_never_reads_host_boot_metadata(monkeypatch):
    for name in ('run_lsblk', 'read_mount_sources', 'read_cmdline'):
        monkeypatch.setattr(discover, name, forbidden)
    payload = json.loads(FIXTURE.read_text())
    result = discover.discover(lsblk_payload=payload, env={})
    assert result.boot_identified and result.boot.path == '/dev/sdb'
    assert len(result.selectable) == 2
    # Explicit contradictory evidence still fails closed.
    result = discover.discover(lsblk_payload=payload, boot_path='/dev/sdb',
                              mount_sources=['/dev/nvme0n1'], cmdline='boot=live', env={})
    assert not result.boot_identified and not result.selectable


def test_fixture_cli_refresh_stays_on_fake_machine(monkeypatch):
    for name in ('run_lsblk', 'read_mount_sources', 'read_cmdline'):
        monkeypatch.setattr(discover, name, forbidden)
    wizard = app._build_wizard(app._parser().parse_args(['--lsblk-json', str(FIXTURE)]))
    assert wizard.dry_run and isinstance(wizard.runner, DryRunRunner)
    before = wizard.discovery
    wizard.skip_splash()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    assert wizard.screen == Screen.PICK
    assert wizard.refresh_disks()
    assert wizard.discovery == before and wizard.screen == Screen.WHAT
    assert not wizard.owner_ok and wizard.selected is None


@pytest.mark.parametrize('platform', ['darwin', 'win32', 'freebsd14'])
def test_non_linux_live_detection_never_reads_proc(monkeypatch, platform):
    monkeypatch.setattr(safety.sys, 'platform', platform)
    monkeypatch.setattr(discover, 'read_cmdline', forbidden)
    assert not safety.running_on_live_usb(env={})


def test_production_discovery_still_reads_boot_metadata(monkeypatch):
    calls = []
    monkeypatch.setattr(discover, 'run_lsblk', lambda: json.loads(FIXTURE.read_text()))
    monkeypatch.setattr(discover, 'read_mount_sources', lambda: calls.append('mounts') or ['/dev/sdb1'])
    monkeypatch.setattr(discover, 'read_cmdline', lambda: calls.append('cmdline') or 'boot=live')
    result = discover.discover(env={'BEAMO_WIPE_DRY_RUN': '1'})
    assert result.boot_identified and calls == ['mounts', 'cmdline']


def test_macos_preview_checks_loaded_tk_patch_not_tcl(monkeypatch, tmp_path):
    import os
    import shlex
    import subprocess
    import sys

    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    uname = fake_bin / 'uname'
    uname.write_text("#!/bin/sh\nprintf 'Darwin\\n'\n")
    uname.chmod(0o755)
    (tmp_path / 'tkinter.py').write_text('''
import os
class Tk:
    def __init__(self): self.tk = self
    def withdraw(self): pass
    def call(self, *args):
        assert args == ('package', 'provide', 'Tk'), args
        return os.environ['FAKE_TK_PATCH']
class Tcl:
    def call(self, *args): return '8.6.99'
''')
    for name, patch in [('python3.14', '8.6.11'), ('python3.13', '8.6.16')]:
        wrapper = fake_bin / name
        wrapper.write_text('#!/bin/sh\n'
                           f'export FAKE_TK_PATCH={patch}\n'
                           f'if [ "$1" = -c ]; then exec {shlex.quote(sys.executable)} "$@"; fi\n'
                           f'printf "selected={name} dry=%s demo=%s\\n" "$BEAMO_WIPE_DRY_RUN" "$BEAMO_WIPE_DEMO"\n')
        wrapper.chmod(0o755)
    env = {**os.environ, 'PATH': f'{fake_bin}:/usr/bin:/bin', 'PYTHONPATH': str(tmp_path)}
    env.pop('BEAMO_WIPE_PREVIEW_PYTHON', None)
    result = subprocess.run([str(FIXTURE.parents[2] / 'preview'), '--console'],
                            env=env, capture_output=True, text=True, check=True, timeout=15)
    assert result.stdout.strip() == 'selected=python3.13 dry=1 demo=1'
