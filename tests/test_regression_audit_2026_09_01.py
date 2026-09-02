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
