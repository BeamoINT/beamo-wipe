# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

import pytest

from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.methods import DEFAULT_METHOD, METHODS
from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import DryRunRunner, build_nwipe_argv, parse_percent, validate_argv
from beamo_wipe.safety import SafetyError, selectable_disks

FIXTURES = Path(__file__).parent / "fixtures"


def _request(method=MethodId.EVERYDAY) -> WipeRequest:
    payload = load_lsblk_json_text((FIXTURES / "lsblk_vm_iso.json").read_text(encoding="utf-8"))
    d = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
        mount_sources=[],
        cmdline="",
    )
    disk = selectable_disks(d)[0]
    return WipeRequest(
        device=disk.path,
        method=method,
        boot_device="/dev/sr0",
        logfile="/tmp/beamo-wipe/nwipe-vda.log",
    )


def test_argv_is_single_device_noninteractive():
    req = _request()
    argv = build_nwipe_argv(req)
    validate_argv(argv, req)
    assert argv[0] == "nwipe"
    assert "--autonuke" in argv
    assert "--nogui" in argv
    assert "--force" not in argv
    assert argv[-1] == "/dev/vda"
    assert argv.count("/dev/vda") == 1
    assert "--exclude=/dev/sr0" in argv
    assert "--PDFreportpath=noPDF" in argv
    spec = METHODS[DEFAULT_METHOD]
    assert f"--method={spec.nwipe_method}" in argv


def test_extra_and_zero_methods():
    extra = build_nwipe_argv(_request(MethodId.EXTRA))
    assert "--method=dodshort" in extra
    zero = build_nwipe_argv(_request(MethodId.QUICK_ZERO))
    assert "--method=zero" in zero
    assert "--verify=off" in zero


def test_rejects_missing_device():
    req = _request()
    argv = build_nwipe_argv(req)
    argv[-1] = "--bogus"
    with pytest.raises(SafetyError):
        validate_argv(argv, req)


def test_validate_rejects_extra_positional():
    req = _request()
    argv = build_nwipe_argv(req)
    argv.insert(-1, "/etc/passwd")
    with pytest.raises(SafetyError):
        validate_argv(argv, req)


def test_parse_percent():
    assert parse_percent("progress 12.5% remaining") == 12.5
    assert parse_percent("no numbers") is None
    assert parse_percent("101%") is None


def test_dry_run_never_calls_binary():
    runner = DryRunRunner(duration_s=0.01)
    req = _request()
    runner.start(req)
    assert runner.started
    # Immediate poll may still be running; that's fine.
    assert runner.result is None or runner.result.ok


def test_nwipe_runner_does_not_deadlock_on_stdout(tmp_path, monkeypatch):
    """A child that writes more than a pipe buffer must still be able to exit."""
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    script = tmp_path / "fake_nwipe"
    script.write_text(
        "#!/bin/sh\n"
        "trap '' USR1\n"
        "dd if=/dev/zero bs=1024 count=256 2>/dev/null\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in --logfile=*) echo '12.5%' >> \"${arg#--logfile=}\" ;; esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    deadline = time.monotonic() + 3.0
    result = None
    while time.monotonic() < deadline:
        result = runner.poll(req)
        if result is not None:
            break
        time.sleep(0.05)
    if runner._proc is not None:
        runner._proc.kill()
    assert result is not None
    assert result.exit_code == 0


def test_nwipe_runner_cancel_allows_start_again(tmp_path, monkeypatch):
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    script = tmp_path / "fake_nwipe_sleep"
    script.write_text(
        "#!/bin/sh\n"
        "trap '' USR1\n"
        "sleep 30\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    runner.cancel()
    time.sleep(0.05)
    runner.start(req)
    runner.cancel()


def test_stale_logfile_does_not_show_100_percent(tmp_path, monkeypatch):
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    stale = tmp_path / "nwipe-vda.log"
    stale.write_text("/dev/vda: 100.00%, round 1 of 1\n", encoding="utf-8")
    script = tmp_path / "fake_nwipe_hang"
    script.write_text(
        "#!/bin/sh\n"
        "trap '' USR1\n"
        "sleep 30\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(stale),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    time.sleep(0.05)
    assert runner.poll(req) is None
    assert runner.progress != 100.0
    runner.cancel()


def test_rejects_logfile_on_block_device():
    req = _request()
    bad = WipeRequest(
        device=req.device,
        method=req.method,
        boot_device=req.boot_device,
        logfile="/dev/sda",
    )
    with pytest.raises(SafetyError):
        build_nwipe_argv(bad)


def test_rejects_force_flag():
    req = _request()
    argv = build_nwipe_argv(req)
    argv.insert(-1, "--force")
    with pytest.raises(SafetyError, match="force"):
        validate_argv(argv, req)


def test_rejects_pdf_path_on_device():
    req = _request()
    argv = build_nwipe_argv(req)
    idx = argv.index("--PDFreportpath=noPDF")
    argv[idx] = "--PDFreportpath=/tmp/report.pdf"
    with pytest.raises(SafetyError):
        validate_argv(argv, req)


def test_rejects_partition_target():
    req = WipeRequest(
        device="/dev/vda1",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile="/tmp/beamo-wipe/nwipe-vda.log",
    )
    with pytest.raises(SafetyError):
        build_nwipe_argv(req)


def test_real_nwipe_binary_refuses_dry_run(monkeypatch, tmp_path):
    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setenv("BEAMO_WIPE_DRY_RUN", "1")
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    runner = NwipeRunner(binary="nwipe")
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    with pytest.raises(SafetyError, match="dry-run"):
        runner.start(req)


def test_zero_confirm_rdev_is_fail_closed_for_real_engine(tmp_path, monkeypatch):
    import subprocess

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.nwipe_runner.require_real_live_for_nwipe", lambda: None)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.pinned_nwipe_already_running", lambda **_k: False
    )
    monkeypatch.setattr("beamo_wipe.nwipe_runner._verify_pinned_nwipe", lambda _p: None)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.assert_existing_is_block_device", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.assert_size_unchanged", lambda *_a, **_k: None
    )
    monkeypatch.setattr("beamo_wipe.nwipe_runner.block_rdev", lambda _p: 0x800)
    monkeypatch.setattr(
        "beamo_wipe.nwipe_runner.resolve_nwipe_binary",
        lambda _b: "/usr/lib/beamo-wipe/nwipe",
    )
    called = []

    def fake_popen(*_a, **_k):
        called.append(True)
        raise AssertionError("nwipe must not start when confirm-time rdev is unknown")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
        device_rdev=0,
        device_size_bytes=10_000_000_000,
    )
    runner = NwipeRunner(binary="/usr/lib/beamo-wipe/nwipe")
    with pytest.raises(SafetyError, match="identity"):
        runner.start(req)
    assert called == []


def test_nwipe_start_leaves_progress_unknown_until_log_reports(tmp_path, monkeypatch):
    import stat

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    script = tmp_path / "fake_nwipe_hang"
    script.write_text(
        "#!/bin/sh\ntrap '' USR1\nsleep 30\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    assert runner.progress is None
    assert runner.poll(req) is None
    assert runner.progress is None
    runner.cancel()


def test_evaluate_nwipe_busy_skip_is_not_success():
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "/dev/vda is reported as IN USE (it could be mounted)\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is False
    assert "in use" in summary.lower()


def test_evaluate_nwipe_busy_on_boot_usb_does_not_fail_target():
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "/dev/sdb is reported as IN USE (it could be mounted)\n"
        "/dev/vda: 100.00%, round 1 of 1\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is True
    assert summary == "finished"


def test_evaluate_nwipe_exit_zero_with_empty_log_is_not_success():
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    ok, summary = evaluate_nwipe_completion(0, "", "/dev/vda")
    assert ok is False
    assert "without wiping" in summary


def test_evaluate_nwipe_abort_with_progress_is_not_finished():
    """nwipe 0.42 logs a percent from SIGUSR1, then abort, and still exits 0."""
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "/dev/vda: 45.00%, round 1 of 1, pass 1 of 1, eta 00:10:00, [writing]\n"
        "Nwipe was aborted by the user. Check the summary table for the drive status.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is False
    assert "abort" in summary.lower()


def test_evaluate_nwipe_zero_percent_summary_is_not_finished():
    """Erasure summary 0.00% plus the success banner is not a completed wipe."""
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        " ! vda |                 0 |        10000000000 |             0.00%\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is False


def test_evaluate_nwipe_unable_to_open_is_not_finished():
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "Unable to open device '/dev/vda'.\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is False
    assert "open" in summary.lower()


def test_evaluate_nwipe_serial_probe_warning_is_not_open_failure():
    """device.c logs this when HDIO_GET_IDENTITY open() fails, then continues."""
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "Unable to open device /dev/vda to obtain serial number\n"
        "      vda | Erased |  120MB/s | 01:25:04 | QEMU/HARDDISK\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is True
    assert summary == "finished"


def test_evaluate_nwipe_model_insanity_is_not_drive_status_failure():
    """Drive Status tokens are 8 chars between pipes; model/serial may contain them."""
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "      vda | Erased |  120MB/s | 01:25:04 | QEMU/INSANITYBOX\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is True
    assert summary == "finished"


def test_evaluate_nwipe_one_hundred_percent_on_target_is_finished():
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "/dev/vda: 100.00%, round 1 of 1, pass 1 of 1, eta 00:00:00, [verifying]\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is True
    assert summary == "finished"


def test_evaluate_nwipe_one_hundred_percent_mid_method_is_not_finished():
    """dodshort (Extra thorough) is 3 passes in one round. 100% of pass 1 of 3
    plus nwipe's exit-0 success banner is not a completed wipe."""
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "/dev/vda: 100.00%, round 1 of 1, pass 1 of 3, eta 00:10:00, [writing]\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is False
    assert "without wiping" in summary


def test_evaluate_nwipe_one_hundred_percent_mid_rounds_is_not_finished():
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "/dev/vda: 100.00%, round 1 of 2, pass 1 of 1, eta 00:10:00, [writing]\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is False
    assert "without wiping" in summary


def test_evaluate_nwipe_one_hundred_percent_last_pass_is_finished():
    """100% of pass 3 of 3 (last pass) is the same fallback as pass 1 of 1."""
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "/dev/vda: 100.00%, round 1 of 1, pass 3 of 3, eta 00:00:00, [verifying]\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is True
    assert summary == "finished"


def test_evaluate_nwipe_erased_table_is_finished():
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "      vda | Erased |  120MB/s | 01:25:04 | QEMU/HARDDISK\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is True
    assert summary == "finished"


def test_evaluate_nwipe_sigusr1_success_before_thread_is_not_finished():
    """nwipe 0.42 SIGUSR1 logs '/dev/X: Success' when thread is unset and
    result is 0 — including after options_log, before pthread_create."""
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "Program options are set as follows\n"
        "/dev/vda: Success\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is False
    assert "without wiping" in summary


def test_evaluate_nwipe_geometry_fail_with_sigusr1_success_is_not_finished():
    """Geometry continue + wipe_threads_started==0 still exits 0 with INSANITY."""
    from beamo_wipe.nwipe_runner import evaluate_nwipe_completion

    log = (
        "Program options are set as follows\n"
        "/dev/vda: Success\n"
        "No sane device geometry for '/dev/vda'.\n"
        "      vda |INSANITY|        0 | 00:00:00 | QEMU/HARDDISK\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, summary = evaluate_nwipe_completion(0, log, "/dev/vda")
    assert ok is False


def test_nwipe_version_line_is_not_a_substring_match():
    from beamo_wipe.nwipe_runner import nwipe_version_is_pinned

    assert nwipe_version_is_pinned("nwipe version 0.42\n")
    assert nwipe_version_is_pinned("nwipe version 0.42")
    assert not nwipe_version_is_pinned("0.42")
    assert not nwipe_version_is_pinned("nwipe version 0.37\n")
    assert not nwipe_version_is_pinned("nwipe version 0.420\n")
    assert not nwipe_version_is_pinned("nwipe version 10.42\n")
    assert not nwipe_version_is_pinned("compiled with 0.42\n")
    assert not nwipe_version_is_pinned("nwipe version 0.42.1\n")


def test_job_percent_does_not_wrap_between_dodshort_passes():
    from beamo_wipe.nwipe_runner import _target_job_percent, _target_last_percent

    pass1 = "/dev/vda: 100.00%, round 1 of 1, pass 1 of 3, eta 00:10:00, [writing]\n"
    assert _target_last_percent(pass1, "/dev/vda") == 100.0
    mid = _target_job_percent(pass1, "/dev/vda")
    assert mid is not None
    assert 33.0 <= mid <= 34.0
    both = pass1 + "/dev/vda: 0.40%, round 1 of 1, pass 2 of 3, eta 00:10:00, [writing]\n"
    job = _target_job_percent(both, "/dev/vda")
    assert job is not None
    assert 33.0 <= job <= 35.0
    last = (
        both + "/dev/vda: 100.00%, round 1 of 1, pass 3 of 3, eta 00:00:00, [verifying]\n"
    )
    assert _target_job_percent(last, "/dev/vda") == 100.0


def test_target_last_percent_ignores_erasure_summary_zero():
    """nwipe 0.42 writes Erasure Summary 0.00% after SIGUSR1 progress lines."""
    from beamo_wipe.nwipe_runner import _target_last_percent

    log = (
        "/dev/vda: 45.00%, round 1 of 1, pass 1 of 1, eta 00:10:00, [writing]\n"
        " ! vda |                 0 |        10000000000 |             0.00%\n"
    )
    assert _target_last_percent(log, "/dev/vda") == 45.0


def test_nwipe_accepts_sigusr1_only_after_options_log():
    from beamo_wipe.nwipe_runner import nwipe_accepts_sigusr1

    assert not nwipe_accepts_sigusr1("")
    assert not nwipe_accepts_sigusr1("nwipe version 0.42\nAuto-selected fastest PRNG: AES\n")
    assert nwipe_accepts_sigusr1("Program options are set as follows...\n")
    assert nwipe_accepts_sigusr1("Using cached I/O on device '/dev/vda'.\n")


def test_sigusr1_not_sent_during_startup_before_nwipe_masks_it(tmp_path, monkeypatch):
    """nwipe 0.42 benches 8 PRNGs before pthread_sigmask(SIGUSR1). Default
    SIGUSR1 terminates; sending it at t=2s kills the engine."""
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    script = tmp_path / "fake_nwipe_no_usr1_trap"
    script.write_text(
        "#!/bin/sh\n"
        "sleep 4\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        result = runner.poll(req)
        if result is not None:
            runner.cancel()
            raise AssertionError(
                f"nwipe child exited during startup (exit {result.exit_code}); "
                "SIGUSR1 was sent before the engine masked it"
            )
        time.sleep(0.05)
    assert runner._proc is not None
    assert runner._proc.poll() is None
    runner.cancel()


def test_sigusr1_sent_after_nwipe_ready_marker(tmp_path, monkeypatch):
    """Once nwipe has logged options (handler installed), SIGUSR1 is used for progress."""
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    script = tmp_path / "fake_nwipe_ready"
    script.write_text(
        "#!/bin/sh\n"
        "trap '' USR1\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in --logfile=*)\n"
        "    echo 'Program options are set as follows...' >> \"${arg#--logfile=}\" ;;\n"
        "  esac\n"
        "done\n"
        "sleep 4\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        runner.poll(req)
        if runner._sigusr1_armed and runner._last_sigusr1 > 0:
            break
        time.sleep(0.05)
    alive = runner._proc is not None and runner._proc.poll() is None
    runner.cancel()
    assert runner._sigusr1_armed
    assert runner._last_sigusr1 > 0
    assert alive


def test_nwipe_runner_busy_skip_log_is_failure(tmp_path, monkeypatch):
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    script = tmp_path / "fake_nwipe_busy"
    script.write_text(
        "#!/bin/sh\n"
        "trap '' USR1\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in --logfile=*)\n"
        "    printf '%s\\n%s\\n' "
        "'/dev/vda is reported as IN USE (it could be mounted)' "
        "'Nwipe successfully completed. See summary table for details.' "
        ">> \"${arg#--logfile=}\" ;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    deadline = time.monotonic() + 3.0
    result = None
    while time.monotonic() < deadline:
        result = runner.poll(req)
        if result is not None:
            break
        time.sleep(0.05)
    if runner._proc is not None:
        runner._proc.kill()
    assert result is not None
    assert result.exit_code == 0
    assert result.ok is False
    assert "in use" in result.summary.lower()


def test_progress_does_not_drop_to_summary_zero_percent(tmp_path, monkeypatch):
    """WORKING must keep SIGUSR1 progress, not the later Erasure Summary 0.00%."""
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    script = tmp_path / "fake_nwipe_summary_zero"
    script.write_text(
        "#!/bin/sh\n"
        "trap '' USR1\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in --logfile=*)\n"
        "    printf '%s\\n%s\\n' "
        "'/dev/vda: 45.00%, round 1 of 1, pass 1 of 1, eta 00:10:00, [writing]' "
        "' ! vda |                 0 |        10000000000 |             0.00%' "
        ">> \"${arg#--logfile=}\" ;;\n"
        "  esac\n"
        "done\n"
        "sleep 4\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    seen = None
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        runner.poll(req)
        if runner.progress is not None:
            seen = runner.progress
            break
        time.sleep(0.05)
    alive = runner._proc is not None and runner._proc.poll() is None
    runner.cancel()
    assert alive
    assert seen == 45.0


def test_completion_sees_erased_row_after_large_pdf_tail(tmp_path, monkeypatch):
    """nwipe 0.42 logs smartctl/PDF after Drive Status. A 64KiB tail can miss Erased."""
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    script = tmp_path / "fake_nwipe_fat_tail"
    script.write_text(
        "#!/bin/sh\n"
        "trap '' USR1\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in --logfile=*)\n"
        "    log=\"${arg#--logfile=}\"\n"
        "    echo '      vda | Erased |  120MB/s | 01:25:04 | QEMU/HARDDISK' >> \"$log\"\n"
        "    dd if=/dev/zero bs=1024 count=80 2>/dev/null | tr '\\0' 'x' >> \"$log\"\n"
        "    echo >> \"$log\"\n"
        "    ;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    req = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sr0",
        logfile=str(tmp_path / "nwipe-vda.log"),
    )
    runner = NwipeRunner(binary=str(script))
    runner.start(req)
    deadline = time.monotonic() + 3.0
    result = None
    while time.monotonic() < deadline:
        result = runner.poll(req)
        if result is not None:
            break
        time.sleep(0.05)
    if runner._proc is not None:
        runner._proc.kill()
    assert result is not None
    assert result.exit_code == 0
    assert result.ok is True

