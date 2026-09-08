"""Host-file and protocol safety for the disposable USB simulation harness."""
import importlib.util
import json
from pathlib import Path
import socket
import threading
import tempfile

import pytest

SPEC = importlib.util.spec_from_file_location('usb_lab', Path(__file__).parents[1] / 'tools/usb_lab/lab.py')
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def test_backing_rejects_devices_symlinks_and_hardlinks(tmp_path):
    source = tmp_path / 'disk.raw'
    source.write_bytes(b'test')
    assert lab.regular(source) == source
    with pytest.raises(ValueError):
        lab.regular('/dev/null')
    symlink = tmp_path / 'link'
    symlink.symlink_to(source)
    with pytest.raises(ValueError):
        lab.regular(symlink)
    directory = tmp_path / 'alias'
    directory.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        lab.regular(directory / source.name)
    hardlink = tmp_path / 'hard'
    hardlink.hardlink_to(source)
    with pytest.raises(ValueError):
        lab.regular(hardlink)


def test_qmp_retains_events_and_rejects_errors(request):
    directory = tempfile.TemporaryDirectory(prefix="usblab-test-", dir="/private/tmp" if Path("/private/tmp").exists() else "/tmp")
    request.addfinalizer(directory.cleanup)
    path = Path(directory.name) / "qmp"
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    server.listen(1)
    def respond():
        connection, _ = server.accept()
        with connection, connection.makefile('rwb', buffering=0) as f:
            f.write(b'{"QMP": {}}\n')
            for _ in range(3):
                req = json.loads(f.readline())
                if req['execute'] == 'bad':
                    value = {'error': {'class': 'GenericError', 'desc': 'refused'}}
                else:
                    f.write(b'{"event":"DEVICE_DELETED","data":{"device":"usb"}}\n')
                    value = {'return': {}}
                f.write(json.dumps({**value, 'id': req['id']}).encode()+b'\n')
    worker = threading.Thread(target=respond)
    worker.start()
    client = lab.QMP(path)
    try:
        assert client.call('query-status') == {}
        assert len(client.events) == 2
        with pytest.raises(RuntimeError, match='refused'):
            client.call('bad')
    finally:
        client.close()
        worker.join(3)
        server.close()


def test_guest_io_refuses_internal_disk_and_ambiguous_serial(monkeypatch):
    spec = importlib.util.spec_from_file_location('usb_guest', Path(__file__).parents[1] / 'tools/usb_lab/guest.py')
    guest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guest)
    disk = {'serial': 'USBLABTEST', 'tran': 'virtio', 'type': 'disk', 'path': '/dev/vda', 'size': 64 * 1024**2}
    monkeypatch.setattr(guest, 'inventory', lambda: {'disks': [disk]})
    with pytest.raises(ValueError, match='Not a USB'):
        guest.execute({'action': 'write', 'serial': 'USBLABTEST'})
    disk.update(tran='usb', path='/dev/sda')
    monkeypatch.setattr(guest, 'inventory', lambda: {'disks': [disk, disk]})
    with pytest.raises(ValueError, match='ambiguous'):
        guest.execute({'action': 'write', 'serial': 'USBLABTEST'})
    monkeypatch.setattr(guest, 'inventory', lambda: {'disks': [disk]})
    disk['size'] = 1024**3
    with pytest.raises(ValueError, match='64 MiB'):
        guest.execute({'action': 'write', 'serial': 'USBLABTEST'})


def load_cloud_lab():
    spec = importlib.util.spec_from_file_location('gcp_lab', Path(__file__).parents[1] / 'tools/usb_lab/gcp_lab.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cloud_teardown_refuses_replacement_instance(tmp_path, monkeypatch):
    from types import SimpleNamespace
    cloud = load_cloud_lab()
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'project': 'test', 'name': 'beamo-usb-test', 'zone': 'us-central1-a', 'region': 'us-central1', 'instance_id': 'original', 'created': ['instance']}))
    calls = []
    def command(*args):
        calls.append(args)
        return json.dumps([{'name': 'beamo-usb-test', 'id': 'replacement'}])
    monkeypatch.setattr(cloud, 'command', command)
    with pytest.raises(ValueError, match='identity differs'):
        cloud.destroy(SimpleNamespace(state=path))
    assert len(calls) == 1 and 'delete' not in calls[0]


def test_cloud_teardown_checks_router_before_deleting_nat(tmp_path, monkeypatch):
    from types import SimpleNamespace
    cloud = load_cloud_lab()
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'project': 'test', 'name': 'beamo-usb-test', 'zone': 'us-central1-a', 'region': 'us-central1', 'created': ['router', 'nat'], 'resources': {'router': {'id': 'original'}}}))
    calls = []
    def command(*args):
        calls.append(args)
        return '[]' if 'list' in args else json.dumps({'id': 'replacement'})
    monkeypatch.setattr(cloud, 'command', command)
    with pytest.raises(ValueError, match='identity differs'):
        cloud.destroy(SimpleNamespace(state=path))
    assert all('delete' not in call for call in calls)


def test_usb_capture_rejects_incomplete_evidence(tmp_path):
    import struct
    spec = importlib.util.spec_from_file_location('pcap_summary', Path(__file__).parents[1] / 'tools/usb_lab/pcap_summary.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'usb.pcap'
    header = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65536, 220)
    path.write_bytes(header+struct.pack('<IIII', 0, 0, 4, 4)+b'USB!')
    assert module.summarize(path)['packets'] == 1
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match='Truncated packet payload'):
        module.summarize(path)
    path.write_bytes(header)
    with pytest.raises(ValueError, match='Empty'):
        module.summarize(path)


def test_windows_connection_failure_removes_owned_scratch(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools/usb_lab'))
    import windows_matrix
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    monkeypatch.setattr(windows_matrix.Lab.__init__.__globals__['tempfile'], 'mkdtemp', lambda **kwargs: str(scratch))
    def refused(*args, **kwargs):
        raise ConnectionRefusedError('fixture QMP unavailable')
    monkeypatch.setattr(windows_matrix, 'QMP', refused)
    with pytest.raises(ConnectionRefusedError):
        windows_matrix.WindowsLab(tmp_path / 'qmp', tmp_path / 'probe', tmp_path / 'out')
    assert not scratch.exists()


def test_usb_attachment_uses_root_port_and_rolls_back_partial_uas(tmp_path, monkeypatch):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    monkeypatch.setattr(lab.tempfile, 'mkdtemp', lambda **kwargs: str(scratch))
    runner = lab.Lab('.', tmp_path / 'out')
    class FakeQMP:
        def __init__(self):
            self.calls = []
            self.events = []
        def call(self, command, **args):
            self.calls.append((command, args))
            if command == 'qom-set':
                raise RuntimeError('injected UAS attach failure')
            if command == 'device_del':
                self.events.append({'event': 'DEVICE_DELETED', 'data': {'device': args['id']}})
            return {}
    runner.qmp = FakeQMP()
    runner.image('test')
    with pytest.raises(RuntimeError, match='injected'):
        runner.attach('test', 'USBLABTEST', 'usb3-uas')
    created = next(args for command, args in runner.qmp.calls if command == 'device_add')
    assert created.get('port') == '1'
    assert any(command == 'device_del' for command, _ in runner.qmp.calls)
    assert any(command == 'blockdev-del' for command, _ in runner.qmp.calls)
    assert not runner.attached


def test_windows_cleanup_failure_cannot_emit_pass(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools/usb_lab'))
    import windows_matrix
    output = tmp_path / 'output'
    class CleanupFailure:
        def __init__(self, *args):
            self.output = output
            self.output.mkdir()
            self.root = tmp_path / 'retained-backing'
            self.root.mkdir()
            self.files, self.initial, self.records = {}, {}, []
        def matrix(self, *args):
            return
        def close(self):
            raise RuntimeError('USB detach unconfirmed')
    monkeypatch.setattr(windows_matrix, 'WindowsLab', CleanupFailure)
    monkeypatch.setattr(windows_matrix.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(windows_matrix.sys, 'argv', ['windows_matrix.py', '--qmp', 'qmp', '--probe', 'probe', '--output', str(output)])
    with pytest.raises(RuntimeError, match='detach unconfirmed'):
        windows_matrix.main()
    receipt = json.loads((output / 'receipt.json').read_text())
    assert receipt['status'] == 'FAIL'
    assert not receipt['scratch_removed']
    assert receipt['requested_profiles'] == list(windows_matrix.PROFILES)
