# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for audit 2026-09-01 findings.

All use fake devices only; never exec real nwipe.
"""

from __future__ import annotations

import os
import stat
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from beamo_wipe.models import WipeRequest
from beamo_wipe.nwipe_runner import (
    _target_job_percent,
    _target_last_percent,
    assert_nwipe_binary_safe,
    build_nwipe_argv,
)
from beamo_wipe.safety import SafetyError


def test_suid_and_sgid_are_rejected():
    tmp = tempfile.mkdtemp()
    p = Path(tmp) / "nwipe"
    p.write_bytes(b"\x7fELF" + b"\x00" * 100)
    fd = os.open(str(p), os.O_RDONLY)

    class FakeStat:
        st_mode = stat.S_IFREG | 0o4755
        st_uid = 0
        st_rdev = 0
        st_dev = 1
        st_ino = 123

    with mock.patch("os.lstat", return_value=FakeStat()):
        with mock.patch("os.open", return_value=fd):
            with mock.patch("os.read", return_value=b"\x7fELF"):
                with mock.patch("os.fstat", return_value=FakeStat()):
                    with pytest.raises(SafetyError, match="setuid"):
                        assert_nwipe_binary_safe(str(p))
    try:
        os.close(fd)
    except OSError:
        pass

    class FakeStatGid:
        st_mode = stat.S_IFREG | 0o2755
        st_uid = 0
        st_rdev = 0
        st_dev = 1
        st_ino = 124

    fd2 = os.open(str(p), os.O_RDONLY)
    with mock.patch("os.lstat", return_value=FakeStatGid()):
        with mock.patch("os.open", return_value=fd2):
            with mock.patch("os.read", return_value=b"\x7fELF"):
                with mock.patch("os.fstat", return_value=FakeStatGid()):
                    with pytest.raises(SafetyError, match="setuid"):
                        assert_nwipe_binary_safe(str(p))
    try:
        os.close(fd2)
    except OSError:
        pass


def test_fstat_inode_mismatch_is_rejected():
    tmp = tempfile.mkdtemp()
    p = Path(tmp) / "nwipe"
    p.write_bytes(b"\x7fELF" + b"\x00" * 100)
    p.chmod(0o755)
    st1 = os.lstat(str(p))

    class FakeFstat:
        st_mode = stat.S_IFREG | 0o755
        st_uid = 0
        st_rdev = 0
        st_dev = st1.st_dev
        st_ino = st1.st_ino + 1

    fd = os.open(str(p), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with mock.patch("os.lstat", return_value=st1):
            with mock.patch("os.open", return_value=fd):
                with mock.patch("os.fstat", return_value=FakeFstat()):
                    with mock.patch("os.read", return_value=b"\x7fELF"):
                        with pytest.raises(SafetyError, match="changed"):
                            assert_nwipe_binary_safe(str(p))
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def test_unknown_method_raises_safetyerror_not_keyerror():
    req = WipeRequest(
        device="/dev/vda",
        method="bogus",  # type: ignore[arg-type]
        boot_device="/dev/sr0",
        logfile="/tmp/beamo-wipe/nwipe-vda.log",
    )
    with pytest.raises(SafetyError, match="Unknown wipe method"):
        build_nwipe_argv(req)


def test_job_percent_not_raw_on_dodshort_mid_pass():
    log = "/dev/vda: 100.00%, round 1 of 1, pass 1 of 3, eta 00:10:00, [writing]\n"
    raw = _target_last_percent(log, "/dev/vda")
    job = _target_job_percent(log, "/dev/vda")
    assert raw == 100.0
    assert job is not None
    assert abs(job - 33.33333333333333) < 0.01
    # Poll must use job percent, not raw, so incomplete wipe never flashes 100%
    from beamo_wipe.nwipe_runner import NwipeRunner

    import inspect

    src = inspect.getsource(NwipeRunner.poll)
    assert "_target_job_percent" in src


def test_concurrent_confirm_erase_does_not_double_start(tmp_path, monkeypatch):
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()

    class Clock:
        def __init__(self):
            self.t = time.monotonic()

        def __call__(self):
            return self.t

    clock = Clock()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=0.5, clock=clock), clock=clock, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    tgt = wiz.selectable[0]
    wiz.select_disk(tgt.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0

    barrier = threading.Barrier(2)

    def do_erase():
        try:
            barrier.wait(timeout=2)
            wiz.confirm_erase()
        except Exception:
            pass

    t1 = threading.Thread(target=do_erase)
    t2 = threading.Thread(target=do_erase)
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert wiz.screen.value == "working"


def test_concurrent_cancel_and_tick_is_not_lost(tmp_path, monkeypatch):
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()

    class Clock:
        def __init__(self):
            self.t = time.monotonic()

        def __call__(self):
            return self.t

    clock = Clock()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=0.5, clock=clock), clock=clock, dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    tgt = wiz.selectable[0]
    wiz.select_disk(tgt.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0
    wiz.confirm_erase()
    assert wiz.screen.value == "working"

    barrier = threading.Barrier(2)

    def tick_loop():
        try:
            barrier.wait(timeout=2)
        except Exception:
            pass
        for _ in range(5):
            wiz.tick()
            time.sleep(0.015)

    def cancel_loop():
        try:
            barrier.wait(timeout=2)
        except Exception:
            pass
        time.sleep(0.02)
        wiz.cancel_wipe()

    t_tick = threading.Thread(target=tick_loop)
    t_cancel = threading.Thread(target=cancel_loop)
    t_tick.start()
    t_cancel.start()
    t_tick.join(timeout=3)
    t_cancel.join(timeout=3)
    # Must be DONE, interrupted, not a double-finish flicker
    assert wiz.screen.value == "done"
    assert wiz.evidence is not None
    assert wiz.evidence["outcome"] == "interrupted"


def test_post_cancel_poll_result_never_finishes_as_engine_failed(
    tmp_path, monkeypatch
):
    """Deterministic form of the tick/cancel race above (no threads).

    Forces the exact losing interleaving: cancel claimed, runner in
    post-cancel state, then a tick lands in the window. tick() must drop
    the post-cancel poll result so cancel_wipe() finishes 'interrupted'
    instead of the engine-'failed' the runner state alone would record.
    """
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=30.0), dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    tgt = wiz.selectable[0]
    wiz.select_disk(tgt.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0
    wiz.confirm_erase()
    assert wiz.screen.value == "working"
    # cancel_wipe's first half ran (claim set, runner cancelled), then a
    # tick lands before cancel_wipe resumes.
    wiz._cancel_requested = True
    wiz.runner.cancel()
    wiz.tick()
    assert wiz.screen.value == "working"
    wiz.cancel_wipe()
    assert wiz.screen.value == "done"
    assert wiz.evidence is not None
    assert wiz.evidence["outcome"] == "interrupted"


def test_back_during_confirm_keeps_screen_truthful(tmp_path, monkeypatch):
    """A back-out racing confirm_erase must not show METHOD while nwipe runs.

    confirm_erase holds _lock from its LAST_CHANCE gate through runner.start;
    back() takes the same lock, so it either wins (confirm then refuses and
    nothing starts) or waits and becomes a no-op once WORKING. Fake runner
    with a blocking start; threads only, fake disks only.
    """
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=30.0), dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    tgt = wiz.selectable[0]
    wiz.select_disk(tgt.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0

    gate = threading.Event()
    release = threading.Event()
    orig_start = wiz.runner.start

    def slow_start(request):
        gate.set()
        assert release.wait(timeout=5)
        orig_start(request)

    wiz.runner.start = slow_start  # type: ignore[method-assign]
    worker = threading.Thread(target=wiz.confirm_erase)
    worker.start()
    assert gate.wait(timeout=5)

    def delayed_release():
        # Let back() block on the confirm-held lock first, then let confirm
        # finish. The lock is held continuously from gate through WORKING.
        time.sleep(0.2)
        release.set()

    releaser = threading.Thread(target=delayed_release)
    releaser.start()
    wiz.back()
    seen_after_back = wiz.screen.value
    worker.join(timeout=5)
    releaser.join(timeout=5)
    assert not worker.is_alive()
    # The screen observed right after the back-out must never contradict the
    # engine: METHOD shown while a wipe started is the losing interleaving.
    assert not (seen_after_back == "method" and wiz.runner.started), (
        f"back-out showed {seen_after_back!r} while nwipe started"
    )
    assert wiz.screen.value == "working"
    assert wiz.runner.started


def test_cancel_flags_survive_transient_evidence_failure(tmp_path, monkeypatch):
    """A failed first evidence write must not downgrade interrupt to engine outcome.

    cancel_wipe writes (cancelled=True, interrupted=True); _finish rewrites
    the same result. First-writer-wins flags keep the retry truthful.
    """
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    base = make_demo_wizard()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=30.0), dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    tgt = wiz.selectable[0]
    wiz.select_disk(tgt.path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    wiz._erase_until = 0
    wiz.confirm_erase()
    assert wiz.screen.value == "working"

    import beamo_wipe.evidence as evidence_mod

    orig_write = evidence_mod.write_evidence_atomic
    calls = {"n": 0}

    def fail_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated full disk")
        return orig_write(*args, **kwargs)

    monkeypatch.setattr(evidence_mod, "write_evidence_atomic", fail_once)
    wiz.cancel_wipe()
    assert wiz.screen.value == "done"
    assert wiz.evidence is not None
    assert wiz.evidence["outcome"] == "interrupted"
    assert wiz.evidence["interruption"] == {"interrupted": True, "cancelled": True}
