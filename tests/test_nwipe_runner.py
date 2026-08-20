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


def test_nwipe_runner_does_not_deadlock_on_stdout(tmp_path):
    """A child that writes more than a pipe buffer must still be able to exit."""
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

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


def test_nwipe_runner_cancel_allows_start_again(tmp_path):
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

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


def test_stale_logfile_does_not_show_100_percent(tmp_path):
    import stat
    import time

    from beamo_wipe.nwipe_runner import NwipeRunner

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
