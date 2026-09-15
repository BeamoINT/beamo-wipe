# SPDX-License-Identifier: GPL-3.0-or-later
"""New-session isolation. All disks and runners are fake."""
import json
from pathlib import Path

import pytest

from beamo_wipe import app
from beamo_wipe.models import Screen, MethodId
from beamo_wipe.safety import SafetyError
from beamo_wipe.wizard import _ReportExportClaim
from test_result_presentations import CASES, case_evidence
from test_session_recovery import session, armed, finish


def saved(w):
    w.evidence_path = '/tmp/beamo-wipe/result-test-1.json'
    w._saved_report_claim = _ReportExportClaim(
        Path(w.evidence_path), 'a' * 64, w._evidence_write_seq,
        w.wipe_result, w.discovery, w.selected.path, 1, 2)


@pytest.mark.parametrize('case', CASES + [
    ('indeterminate', MethodId.EVERYDAY, None, '', True, False)
], ids=lambda c: c[0])
@pytest.mark.parametrize('report', ['not_wanted', 'wanted', 'failed', 'saved',
                                   'stale_saved', 'evidence_failed'])
def test_outcomes_and_reports(case, report):
    w, _, _ = case_evidence(case)
    if case[0] == 'indeterminate':
        w.evidence = None
    w.owner_ok = True
    w.confirm_input = 'OLD TOKEN'
    w._authorized_operation = ('old',)
    w._erase_until = 0
    if report != 'not_wanted':
        w.report_wanted = True
    if report in {'saved', 'stale_saved'}:
        saved(w)
        if report == 'stale_saved':
            w._evidence_write_seq += 1
    if report == 'failed':
        w.report_status = 'error'
    if report == 'evidence_failed':
        w.evidence_error = 'Could not save'
    assert w.can_erase_another
    w.erase_another_disk()
    if report != 'saved':
        assert w.screen == Screen.SHUTDOWN_CONFIRM
        assert not w.wants_new_session
        old_result, old_evidence = w.wipe_result, w.evidence
        generation = w.shutdown_generation
        w.keep_report_session()
        w.confirm_shutdown_without_saving(generation)
        assert not w.wants_new_session
        assert w.screen == Screen.DONE
        assert w.wipe_result is old_result and w.evidence is old_evidence
        w.erase_another_disk()
        w.confirm_shutdown_without_saving(generation)  # old confirmation
        assert not w.wants_new_session
        w.confirm_shutdown_without_saving(w.shutdown_generation)
    assert w.wants_new_session and not w.wants_shutdown
    assert not w.owner_ok and not w.confirm_input
    assert w._authorized_operation is None and w._erase_until is None
    assert not w.can_erase_another


@pytest.mark.parametrize('busy', ['_report_exporting', '_evidence_saving', '_diagnostic_busy', '_finishing'])
def test_busy_blocks_transition(busy):
    w, _, _ = case_evidence(CASES[0])
    setattr(w, busy, True)
    w.erase_another_disk()
    assert w.screen == Screen.DONE and not w.wants_new_session


@pytest.mark.parametrize('screen', [s for s in Screen if s != Screen.DONE])
def test_only_done_can_request_new_session(screen):
    w, _, _ = case_evidence(CASES[0])
    w.screen = screen
    w.erase_another_disk()
    assert not w.wants_new_session
    assert w.screen == screen


@pytest.mark.parametrize("interface", ["console", "tk", "accessible"])
def test_repeated_app_sessions_are_fresh(monkeypatch, tmp_path, interface):
    monkeypatch.setattr(app, 'running_on_live_usb', lambda: False)
    monkeypatch.delenv('BEAMO_WIPE_BOOT_DEVICE', raising=False)
    source = tmp_path / 'disks.json'
    payload = json.loads((Path(__file__).parent / 'fixtures/lsblk_same_size.json').read_text())
    source.write_text(json.dumps(payload))
    args = app._parser().parse_args(['--lsblk-json', str(source), '--plain-console'])
    seen = []
    def ui(w, **kwargs):
        if seen:
            assert w.keyboard_layout == "de"
        assert all(w is not old and w.runner is not old.runner for old in seen)
        assert w.screen == Screen.SPLASH
        assert not w.owner_ok and w.selected is None and w.confirm_input == ''
        assert w.method == MethodId.EVERYDAY
        assert w._wipe_request is None and w._authorized_operation is None
        assert w._erase_until is None and w.log_text == '' and w.evidence is None
        assert w.wipe_result is None and w._saved_report_claim is None
        w.confirm_erase()  # stale callback cannot start the new runner
        assert w._wipe_request is None
        assert w.discovery.boot not in w.selectable
        seen.append(w)
        if len(seen) == 3:
            assert w.discovery.boot.path == '/dev/sdy'
            w.shutdown()
            return 0
        if len(seen) == 2:
            assert any(d.path == '/dev/sdz' for d in w.selectable)
            payload['blockdevices'][0].update(name='sdy', path='/dev/sdy')
            payload['blockdevices'][0]['children'][0].update(name='sdy1', path='/dev/sdy1')
        else:
            payload['blockdevices'][1].update(name='sdz', path='/dev/sdz')
        source.write_text(json.dumps(payload))
        completed, evidence, _ = case_evidence(CASES[0])
        w.screen = Screen.DONE
        w.selected = w.selectable[0]
        w.wipe_result = completed.wipe_result
        w.evidence = evidence
        w.keyboard_layout = 'de'
        w.log_text = 'previous log'
        w.owner_ok = True
        w.confirm_input = 'previous token'
        w.method = MethodId.QUICK_ZERO
        w.erase_another_disk()
        w.confirm_shutdown_without_saving(w.shutdown_generation)
        return 0
    monkeypatch.setattr('beamo_wipe.ui.console_wizard._plain_loop', ui)
    if interface != 'console':
        monkeypatch.setattr(app, '_build_wizard_with_' + ('tk' if interface == 'tk' else 'accessible') + '_stages',
                            lambda args, fullscreen: app._build_wizard(args))
        module = 'tk_wizard.run_tk' if interface == 'tk' else 'accessible_wizard.run_accessible'
        if interface == 'accessible':
            pytest.importorskip('gi')
        monkeypatch.setattr('beamo_wipe.ui.' + module, ui)
    assert app._run_session(args, session_store=None, use_console=interface == 'console',
                            want_accessible=interface == 'accessible', fullscreen=False, reader=None) == 0
    assert len(seen) == 3


def test_journal_rotation_keeps_artifacts_and_allows_fresh_arm(session):
    store = session()
    discovery, request = armed(store)
    finish(store, discovery, request)
    old_session = store.record['session']
    before = {p.name: p.read_bytes() for p in store.directory.glob('result-*')}
    before[Path(request.logfile).name] = Path(request.logfile).read_bytes()
    store.begin_new_session()
    assert store.record['session'] != old_session
    assert store.record['phase'] == 'preflight' and not store.previous
    assert store.quiescent == -1
    assert all((store.directory / name).read_bytes() == data for name, data in before.items())
    armed(store)


def test_journal_rotation_refuses_active_runner(session, monkeypatch):
    store = session()
    armed(store)
    before = store.record.copy()
    monkeypatch.setattr(store, 'is_quiescent', lambda: False)
    with pytest.raises(SafetyError):
        store.begin_new_session()
    assert store.record == before


def test_console_unsaved_cancel_and_continue(monkeypatch):
    from beamo_wipe.ui.console_wizard import _plain_loop
    w, _, _ = case_evidence(CASES[0])
    answers = iter(['ANOTHER', '', 'ANOTHER', 'CONTINUE WITHOUT SAVING'])
    monkeypatch.setattr('builtins.input', lambda *_: next(answers))
    assert _plain_loop(w) == 0
    assert w.wants_new_session and not w.wants_shutdown


@pytest.mark.parametrize('change', ['removed', 'added', 'boot_missing', 'invalid'])
def test_new_session_rediscovery_fails_closed(change, monkeypatch, tmp_path):
    monkeypatch.setattr(app, 'running_on_live_usb', lambda: False)
    monkeypatch.delenv('BEAMO_WIPE_BOOT_DEVICE', raising=False)
    payload = json.loads((Path(__file__).parent / 'fixtures/lsblk_same_size.json').read_text())
    source = tmp_path / 'disks.json'
    source.write_text(json.dumps(payload))
    args = app._parser().parse_args(['--lsblk-json', str(source), '--plain-console'])
    seen = []
    def ui(w):
        seen.append(w)
        if len(seen) == 1:
            if change == 'removed':
                payload['blockdevices'] = payload['blockdevices'][:1]
            elif change == 'added':
                node = payload['blockdevices'][1]
                payload['blockdevices'].append({**node, 'name': 'sdz', 'path': '/dev/sdz', 'serial': 'NEW'})
            elif change == 'boot_missing':
                payload['blockdevices'].pop(0)
            source.write_text('invalid' if change == 'invalid' else json.dumps(payload))
            completed, ev, _ = case_evidence(CASES[0])
            w.screen, w.wipe_result, w.evidence = Screen.DONE, completed.wipe_result, ev
            w.erase_another_disk()
            w.confirm_shutdown_without_saving(w.shutdown_generation)
        else:
            assert w.selected is None and not w.owner_ok
            assert w._wipe_request is None
            if change in {'boot_missing', 'invalid', 'removed'}:
                assert not w.selectable
            else:
                assert any(d.path == '/dev/sdz' for d in w.selectable)
            # Close the test interface without requesting power off.
        return 0
    monkeypatch.setattr('beamo_wipe.ui.console_wizard._plain_loop', ui)
    assert app._run_session(args, session_store=None, use_console=True,
                            want_accessible=False, fullscreen=False, reader=None) == 0
    assert len(seen) == 2


def test_new_session_requires_all_gates_and_new_countdown(monkeypatch, tmp_path):
    from beamo_wipe.demo import make_demo_wizard
    from test_confirmation_gates import Clock
    old, _, _ = case_evidence(CASES[0])
    saved(old)
    old.erase_another_disk()
    clock = Clock()
    w = make_demo_wizard()
    w._clock = clock
    monkeypatch.setattr('beamo_wipe.safety.default_log_dir', lambda: tmp_path)
    w.skip_intro()
    w.accept_what()
    w.continue_owner()
    assert w.screen == Screen.OWNER
    w.set_owner(True)
    w.continue_owner()
    w.continue_pick()
    assert w.screen == Screen.PICK
    w.select_disk(w.discovery.boot.path)
    assert w.selected is None
    w.select_disk(w.selectable[0].path)
    w.continue_pick()
    w.continue_confirm()
    assert w.screen == Screen.CONFIRM
    w.set_confirm_input(w.confirm.token)
    w.continue_confirm()
    assert w.screen == Screen.METHOD
    w.continue_method()
    assert w.screen == Screen.LAST_CHANCE and w.countdown_left == 5
    w.confirm_erase()
    assert w._wipe_request is None
    clock.add(4.99)
    w.confirm_erase()
    assert w._wipe_request is None
    clock.add(0.01)
    assert w.erase_enabled
    # Explicit user activation remains required even after five seconds.
    w.tick()
    assert w._wipe_request is None


def test_invalid_or_busy_journal_keeps_report_available(session, monkeypatch):
    store = session()
    w, _, _ = case_evidence(CASES[0])
    w._session_store = store
    monkeypatch.setattr(store, 'is_quiescent', lambda: False)
    w.erase_another_disk()
    assert w.screen == Screen.DONE and not w.wants_new_session
    monkeypatch.setattr(store, 'is_quiescent', lambda: True)
    store.invalid = True
    w.erase_another_disk()
    assert w.screen == Screen.DONE and not w.wants_new_session


def test_curses_another_and_cancel():
    from beamo_wipe.ui.console_wizard import _handle
    w, _, _ = case_evidence(CASES[0])
    _handle(w, ord('a'))
    assert w.screen == Screen.SHUTDOWN_CONFIRM
    _handle(w, 10)
    assert w.screen == Screen.DONE and not w.wants_new_session


def test_verified_usb_receipt_skips_unsaved_prompt(tmp_path):
    from test_usb_report_workflow import _done_wizard, _success_receipt
    w = _done_wizard(lambda **kw: _success_receipt(**kw, log_status='complete'), tmp_path)
    w.save_report_to_usb()
    assert w.report_status == 'saved'
    w.erase_another_disk()
    assert w.wants_new_session
    assert w.screen == Screen.DONE
    assert not w.begin_report_export()  # a stale button cannot export again


def test_finish_cannot_be_left_before_evidence_work_is_claimed(monkeypatch):
    w, _, _ = case_evidence(CASES[0])
    result = w.wipe_result
    w.screen = Screen.WORKING
    w.wipe_result = None
    def evidence(**kwargs):
        assert w.screen == Screen.DONE
        w.erase_another_disk()
        assert not w.wants_new_session and w.screen == Screen.DONE
    monkeypatch.setattr(w, '_write_evidence', evidence)
    w._finish(result)
    assert not w._finishing and w.can_erase_another



def test_rotation_checks_real_runner_lock(session):
    import subprocess
    import sys
    store = session()
    armed(store)
    child = subprocess.Popen([sys.executable, '-c',
        "import fcntl,sys,os; os.umask(0o077); f=open(sys.argv[1],'a'); "
        "fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.readline()",
        str(store.directory / 'wipe.lock')], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'locked'
        before = store.record.copy()
        with pytest.raises(SafetyError):
            store.begin_new_session()
        assert store.record == before
    finally:
        child.communicate('release\n', timeout=5)
    store.begin_new_session()
    assert store.record['phase'] == 'preflight'


def test_journal_save_failure_cannot_arm_new_erase(session, monkeypatch):
    store = session()
    armed(store)
    before = store.record.copy()
    def fail(changes):
        raise OSError('temporary storage unavailable')
    monkeypatch.setattr(store, 'save', fail)
    with pytest.raises(OSError):
        store.begin_new_session()
    assert store.record == before
    with pytest.raises(SafetyError):
        armed(store)



def test_screen_reader_switch_persists_across_sessions(monkeypatch):
    pytest.importorskip('gi')
    args = app._parser().parse_args(['--demo'])
    calls = []
    def tk(w, **kwargs):
        calls.append('tk')
        return 4  # user requests the screen-reader view
    def accessible(w, **kwargs):
        calls.append('accessible')
        if calls.count('accessible') == 1:
            completed, ev, _ = case_evidence(CASES[0])
            w.preview = False
            w.screen, w.wipe_result, w.evidence = Screen.DONE, completed.wipe_result, ev
            w.erase_another_disk()
            w.confirm_shutdown_without_saving(w.shutdown_generation)
        return 0
    monkeypatch.setattr('beamo_wipe.ui.tk_wizard.run_tk', tk)
    monkeypatch.setattr('beamo_wipe.ui.accessible_wizard.run_accessible', accessible)
    assert app._run_session(args, session_store=None, use_console=False,
                            want_accessible=False, fullscreen=False, reader=None) == 0
    assert calls == ['tk', 'accessible', 'accessible']



def test_unconfirmed_stop_never_offers_another_disk(monkeypatch):
    from beamo_wipe.wizard import Wizard
    from beamo_wipe.outcomes import VIEWS
    w, _, _ = case_evidence(CASES[0])
    monkeypatch.setattr(Wizard, 'result_view', property(lambda self: VIEWS['stop_unconfirmed']))
    w.erase_another_disk()
    assert not w.can_erase_another and not w.wants_new_session
    assert w.screen == Screen.DONE
