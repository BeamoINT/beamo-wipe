# SPDX-License-Identifier: GPL-3.0-or-later
"""Evidence failures never control a runner. Fake disks and ordinary files only."""
import errno
from pathlib import Path

import pytest

from beamo_wipe import evidence
from beamo_wipe.models import Screen
from test_evidence import _wiz


def start(tmp_path, monkeypatch):
    monkeypatch.setattr('beamo_wipe.safety.default_log_dir', lambda: tmp_path)
    w, clock = _wiz(tmp_path)
    w.skip_splash()
    w.accept_what()
    w.set_owner(True)
    w.continue_owner()
    w.select_disk(w.selectable[0].path)
    w.continue_pick()
    w.set_confirm_input(w.confirm.token)
    w.continue_confirm()
    w.continue_method()
    clock.add(5)
    w.confirm_erase()
    return w, clock


def fail(*args, **kwargs):
    raise OSError(errno.ENOSPC, '/private/customer/serial-sensitive')


def test_running_warning_and_terminal_retry(tmp_path, monkeypatch):
    writer = evidence.write_evidence_atomic
    monkeypatch.setattr(evidence, 'write_evidence_atomic', fail)
    w, clock = start(tmp_path, monkeypatch)
    assert w.screen == Screen.WORKING
    assert 'space' in w.evidence_warning
    assert 'customer' not in w.evidence_warning
    assert not w.can_retry_evidence
    clock.add(1)
    w.tick()
    result = w.wipe_result
    assert w.screen == Screen.DONE and w.can_retry_evidence
    assert not w.can_save_report and not w.result_view.success
    monkeypatch.setattr(evidence, 'write_evidence_atomic', writer)
    monkeypatch.setattr(w.runner, 'start', lambda *_: pytest.fail('erase restarted'))
    monkeypatch.setattr(w.runner, 'poll', lambda *_: pytest.fail('erase polled'))
    assert w.retry_evidence_save()
    assert w.wipe_result == result
    assert w.evidence_error is None
    path = w.evidence_path
    assert not w.retry_evidence_save()
    assert w.evidence_path == path and evidence.verify_evidence_checksum(Path(path))


def test_checksum_failure_is_visible(tmp_path, monkeypatch):
    w, clock = start(tmp_path, monkeypatch)
    monkeypatch.setattr(evidence, 'verify_evidence_checksum', lambda *_: False)
    clock.add(1)
    w.tick()
    assert w.evidence_error
    assert not w.can_save_report and not w.result_view.success


def complete(w, clock, outcome='completed'):
    log = f'{Path(w.selected.path).name} | Erased |\n'
    Path(w._wipe_request.logfile).write_text(log)
    Path(w._wipe_request.logfile).chmod(0o600)
    w.runner._log_tail = log
    if outcome == 'interrupted':
        w.cancel_wipe()
    else:
        w.runner.fail = outcome == 'failed'
        clock.add(1)
        w.tick()
    assert w.screen == Screen.DONE


@pytest.mark.parametrize('number,code', [
    (errno.EACCES, 'permissions'), (errno.EPERM, 'permissions'),
    (errno.EROFS, 'permissions'), (errno.ENOSPC, 'storage_full'),
    (errno.EDQUOT, 'storage_full'), (errno.EIO, 'transient_io'),
    (errno.EINTR, 'transient_io'), (errno.EAGAIN, 'transient_io'),
])
@pytest.mark.parametrize('outcome', ['completed', 'failed', 'interrupted'])
def test_error_classes_retry_bound_and_frozen_outcome(tmp_path, monkeypatch, number, code, outcome):
    w, clock = start(tmp_path, monkeypatch)
    writer = evidence.write_evidence_atomic
    attempts = []

    def broken(ev, **kwargs):
        attempts.append(ev)
        raise OSError(number, 'private-customer-data')

    monkeypatch.setattr(evidence, 'write_evidence_atomic', broken)
    complete(w, clock, outcome)
    result = w.wipe_result
    original = attempts[0]
    assert w.evidence_error_code == code
    assert w.report_view.evidence_status == 'failed'
    assert 'private-customer-data' not in w.evidence_warning
    # A changed log and clock cannot change the report after the engine stopped.
    Path(result.logfile).write_text('contradictory later bytes')
    w.runner._log_tail = 'contradictory later bytes'
    clock.add(1000)
    for remaining in (2, 1, 0):
        assert not w.retry_evidence_save()
        assert w.report_view.retries_remaining == remaining
        assert w.wipe_result == result and attempts[-1] == original
    for _ in range(8):
        w.tick()
        assert not w.retry_evidence_save()
    assert len(attempts) == 4
    monkeypatch.setattr(evidence, 'write_evidence_atomic', writer)
    assert not w.retry_evidence_save()  # exhaustion cannot queue a fifth write
    assert not w.can_save_report and not w.result_view.success


@pytest.mark.parametrize('outcome', ['completed', 'failed', 'interrupted'])
def test_retry_preserves_result_times_and_interruption(tmp_path, monkeypatch, outcome):
    w, clock = start(tmp_path, monkeypatch)
    writer = evidence.write_evidence_atomic
    monkeypatch.setattr(evidence, 'write_evidence_atomic', fail)
    complete(w, clock, outcome)
    result = w.wipe_result
    inputs = w._pending_evidence[0].copy()
    monkeypatch.setattr(evidence, 'write_evidence_atomic', writer)
    clock.add(100)
    for name in ('start', 'poll', 'cancel'):
        monkeypatch.setattr(w.runner, name, lambda *_: pytest.fail('runner called by save'))
    assert w.retry_evidence_save()
    assert w.wipe_result == result
    assert w.evidence['timestamps']['ended_monotonic'] == inputs['ended_mono']
    assert w.evidence['interruption']['cancelled'] == (outcome == 'interrupted')
    assert w.can_save_report
    assert w.report_view.evidence_status == 'saved'
    assert w.result_view.success == (outcome == 'completed')
    assert w.report_status != 'saved'  # local persistence is not USB export


@pytest.mark.parametrize('checkpoint', [
    'open', 'write', 'short_write', 'file_fsync', 'link', 'temp_unlink', 'dir_fsync',
    'sidecar_open', 'sidecar_write', 'sidecar_fsync', 'sidecar_link', 'sidecar_dir_fsync',
    'readback', 'checksum', 'corrupt_readback',
])
@pytest.mark.parametrize('phase', ['start', 'completed', 'interrupted', 'failed'])
def test_atomic_checkpoint_failures(tmp_path, monkeypatch, checkpoint, phase):
    import os
    import stat
    w = clock = None
    if phase != 'start':
        w, clock = start(tmp_path, monkeypatch)
    with monkeypatch.context() as fault:
        if checkpoint in {'readback', 'checksum', 'corrupt_readback'}:
            if checkpoint == 'checksum':
                fault.setattr(evidence, 'verify_evidence_checksum', lambda *_: False)
            elif checkpoint == 'readback':
                fault.setattr(evidence, 'load_evidence', fail)
            else:
                load = evidence.load_evidence
                def corrupt(path, **kwargs):
                    record = load(path, **kwargs)
                    record['exit_evidence']['exit_code'] = 99
                    return record
                fault.setattr(evidence, 'load_evidence', corrupt)
        else:
            atomic = evidence._atomic_write_bytes
            active = {'enabled': False}
            sidecar = checkpoint.startswith('sidecar_')
            point = checkpoint.removeprefix('sidecar_')
            def wrapped(path, data):
                active['enabled'] = str(path).endswith('.sha256') == sidecar
                try:
                    return atomic(path, data)
                finally:
                    active['enabled'] = False
            fault.setattr(evidence, '_atomic_write_bytes', wrapped)
            operation = {'short_write': 'write', 'file_fsync': 'fsync', 'dir_fsync': 'fsync',
                         'temp_unlink': 'unlink'}.get(point, point)
            original = getattr(os, operation)
            tripped = []
            def broken(*args, **kwargs):
                qualifies = True
                if point == 'open':
                    qualifies = '.tmp.' in str(args[0])
                elif point in {'file_fsync', 'dir_fsync'}:
                    qualifies = stat.S_ISDIR(os.fstat(args[0]).st_mode) == (point == 'dir_fsync')
                if active['enabled'] and qualifies and not tripped:
                    tripped.append(True)
                    if point == 'short_write':
                        return 0
                    raise OSError(errno.EIO, 'private-path')
                return original(*args, **kwargs)
            fault.setattr(os, operation, broken)
        if phase == 'start':
            w, clock = start(tmp_path, monkeypatch)
            assert w.screen == Screen.WORKING and not w.can_retry_evidence
        else:
            complete(w, clock, phase)
            assert w.can_retry_evidence
        assert w.evidence_error and not w.can_save_report
        assert not w.result_view.success
    if phase == 'start':
        complete(w, clock)
    else:
        result = w.wipe_result
        assert w.retry_evidence_save()
        assert w.wipe_result == result
    assert not w.evidence_error and w.can_save_report


def test_finalization_retry_reuses_verified_file(tmp_path, monkeypatch):
    from types import SimpleNamespace
    w, clock = start(tmp_path, monkeypatch)
    calls = []
    def finalize(path):
        calls.append(path)
        if len(calls) == 1:
            raise RuntimeError('private finalization data')
    w._session_store = SimpleNamespace(directory=tmp_path, finish=finalize)
    complete(w, clock)
    assert w.evidence_error_code == 'finalization'
    assert w.evidence_status == 'failed' and not w.can_save_report
    files = set(tmp_path.iterdir())
    assert w.retry_evidence_save()
    assert calls[0] == calls[1] and set(tmp_path.iterdir()) == files
    assert w.can_save_report


def test_concurrent_retry_is_single_claim_and_blocks_shutdown_export(tmp_path, monkeypatch):
    import threading
    w, clock = start(tmp_path, monkeypatch)
    writer = evidence.write_evidence_atomic
    monkeypatch.setattr(evidence, 'write_evidence_atomic', fail)
    complete(w, clock)
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return writer(*args, **kwargs)
    monkeypatch.setattr(evidence, 'write_evidence_atomic', slow)
    assert w.begin_evidence_retry()
    assert entered.wait(2)
    try:
        assert not w.begin_evidence_retry() and not w.retry_evidence_save()
        assert w.report_view.saving_evidence and not w.can_save_report
        w.shutdown()
        assert not w.wants_shutdown and w.screen == Screen.DONE
        assert not w.begin_report_export()
        with pytest.raises(Exception, match='verified evidence'):
            w.export_evidence(str(tmp_path))
    finally:
        release.set()
    import time
    deadline = time.monotonic() + 3
    while w.report_view.saving_evidence and time.monotonic() < deadline:
        time.sleep(.01)
    assert w.can_save_report and w._evidence_retries == 1


@pytest.mark.parametrize('change', ['result', 'disk', 'method', 'discovery', 'request', 'shutdown', 'screen'])
def test_stale_retry_rejected_without_writing(tmp_path, monkeypatch, change):
    from dataclasses import replace
    from beamo_wipe.models import MethodId
    w, clock = start(tmp_path, monkeypatch)
    monkeypatch.setattr(evidence, 'write_evidence_atomic', fail)
    complete(w, clock)
    if change == 'result':
        w.wipe_result = replace(w.wipe_result, exit_code=9)
    elif change == 'disk':
        w.selected = replace(w.selected, serial='changed')
    elif change == 'discovery':
        w.discovery = replace(w.discovery, error='changed')
    elif change == 'method':
        w.method = MethodId.QUICK_ZERO
    elif change == 'request':
        w._wipe_request = None
    elif change == 'shutdown':
        w.wants_shutdown = True
    else:
        w.screen = Screen.WORKING
    monkeypatch.setattr(evidence, 'write_evidence_atomic', lambda *_a, **_k: pytest.fail('stale save'))
    assert not w.retry_evidence_save()


def test_recovery_save_failure_has_no_tick_retry(tmp_path, monkeypatch):
    from beamo_wipe.session_recovery import SessionStore
    from test_session_recovery import BOOT, BUILD, armed
    directory = tmp_path / 'recovery'
    first = SessionStore(directory, boot=BOOT, build=BUILD).open()
    discovery, _ = armed(first)
    first.close()
    second = SessionStore(directory, boot=BOOT, build=BUILD).open()
    from beamo_wipe.wizard import Wizard
    from beamo_wipe.nwipe_runner import DryRunRunner
    w = Wizard(discovery, DryRunRunner())
    writer = evidence.write_evidence_atomic
    calls = []
    def broken(*a, **kw):
        calls.append(True)
        return fail()
    monkeypatch.setattr(evidence, 'write_evidence_atomic', broken)
    try:
        w.enable_session_recovery(second)
        assert w.screen == Screen.DONE and w.wipe_result.exit_code is None
        assert w.can_retry_evidence and not w.can_save_report
        for _ in range(20):
            w.tick()
        assert len(calls) == 1
        monkeypatch.setattr(evidence, 'write_evidence_atomic', writer)
        assert w.retry_evidence_save()
        assert w.can_save_report and not w.result_view.success
        assert w._wipe_request is None and w.runner._started is None
        assert w.evidence['exit_evidence']['exit_code'] is None
        assert not w.evidence['logfile']
    finally:
        second.close()


def test_invalid_build_data_can_only_retry_frozen_inputs(tmp_path, monkeypatch):
    w, clock = start(tmp_path, monkeypatch)
    builder = evidence.build_evidence
    def invalid(**kw):
        record = builder(**kw)
        record['timestamps']['duration_s'] = float('nan')
        return record
    monkeypatch.setattr(evidence, 'build_evidence', invalid)
    complete(w, clock)
    assert w.evidence_error_code == 'invalid_data' and w.can_retry_evidence
    monkeypatch.setattr(evidence, 'build_evidence', builder)
    assert w.retry_evidence_save()


@pytest.mark.parametrize('file', ['json', 'sidecar'])
def test_unsafe_readback_permissions_are_not_silently_repaired(tmp_path, monkeypatch, file):
    w, clock = start(tmp_path, monkeypatch)
    writer = evidence.write_evidence_atomic
    paths = []
    def unsafe(*args, **kwargs):
        path = writer(*args, **kwargs)
        changed = path if file == 'json' else Path(str(path) + '.sha256')
        changed.chmod(0o644)
        paths.append(changed)
        return path
    monkeypatch.setattr(evidence, 'write_evidence_atomic', unsafe)
    complete(w, clock)
    assert w.evidence_error_code == 'permissions'
    assert not w.can_save_report and not w.result_view.success
    assert paths[0].stat().st_mode & 0o777 == 0o644
    monkeypatch.setattr(evidence, 'write_evidence_atomic', writer)
    assert w.retry_evidence_save()
    assert Path(w.evidence_path).stat().st_mode & 0o777 == 0o600


def test_plain_console_retry_action(tmp_path, monkeypatch, capsys):
    from beamo_wipe.ui import console_wizard
    w, clock = start(tmp_path, monkeypatch)
    writer = evidence.write_evidence_atomic
    monkeypatch.setattr(evidence, 'write_evidence_atomic', fail)
    complete(w, clock)
    monkeypatch.setattr(evidence, 'write_evidence_atomic', writer)
    responses = iter(['RETRY', 'SHUTDOWN'])
    monkeypatch.setattr(console_wizard, '_answer', lambda *_: next(responses))
    console_wizard._plain_loop_body(w)
    assert w.can_save_report is False  # shutdown was explicitly requested
    assert w.evidence_status == 'saved'
    assert 'Retry save (3 left)' in capsys.readouterr().out


def test_menu_console_retry_key_never_starts_runner(tmp_path, monkeypatch):
    from beamo_wipe.ui.console_wizard import _handle
    w, clock = start(tmp_path, monkeypatch)
    monkeypatch.setattr(evidence, 'write_evidence_atomic', fail)
    complete(w, clock)
    called = []
    monkeypatch.setattr(w, 'begin_evidence_retry', lambda: called.append(True))
    _handle(w, ord('E'))
    assert called == [True] and w.screen == Screen.DONE
