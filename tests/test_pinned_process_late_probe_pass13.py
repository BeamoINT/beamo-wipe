"""A pinned engine appearing during preflight must block this launch."""

import pytest

import beamo_wipe.nwipe_runner as runner_module
from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.safety import SafetyError


def test_new_pinned_engine_after_initial_probe_blocks_spawn(monkeypatch):
    request = WipeRequest(
        device="/dev/vda",
        method=MethodId.EVERYDAY,
        boot_device="/dev/sdb",
        logfile="/tmp/beamo-wipe/nwipe-vda.log",
        device_rdev=1,
        boot_rdev=2,
        device_size_bytes=10_000_000_000,
    )
    runner = runner_module.NwipeRunner()
    probes = 0
    released = []

    def pinned_probe(**_kwargs):
        nonlocal probes
        probes += 1
        return probes >= 2

    monkeypatch.setattr(runner_module, "pinned_nwipe_already_running", pinned_probe)
    monkeypatch.setattr(runner_module, "require_real_live_for_nwipe", lambda: None)
    monkeypatch.setattr(runner_module, "_verify_pinned_nwipe", lambda _p: None)
    monkeypatch.setattr(
        runner_module, "assert_existing_is_block_device", lambda *_a, **_k: None
    )
    monkeypatch.setattr(runner_module, "assert_size_unchanged", lambda *_a: None)
    monkeypatch.setattr(
        runner_module, "assert_local_device_transport", lambda *_a: None
    )
    monkeypatch.setattr(
        runner_module, "block_rdev", lambda p: 1 if p == "/dev/vda" else 2
    )
    monkeypatch.setattr(runner_module, "assert_not_boot", lambda *_a, **_k: None)
    monkeypatch.setattr(runner_module, "assert_log_not_on_target", lambda *_a: None)
    monkeypatch.setattr(runner_module, "truncate_log_file", lambda *_a: None)
    monkeypatch.setattr(runner_module, "_recheck_identity_under_lock", lambda *_a: None)
    monkeypatch.setattr(runner, "_acquire_wipe_lock", lambda _r: None)
    monkeypatch.setattr(runner, "_release_wipe_lock", lambda: released.append(True))
    monkeypatch.setattr(runner._sleep_inhibit, "start", lambda: None)
    monkeypatch.setattr(
        runner_module.subprocess,
        "Popen",
        lambda *_a, **_k: pytest.fail("spawn reached"),
    )

    with pytest.raises(SafetyError, match="already running"):
        runner.start(request)
    assert probes >= 2
    assert released == [True]
    assert runner._proc is None
