"""SIGUSR1 is sent only after nwipe's own handler-ready log record."""

from __future__ import annotations

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner, nwipe_accepts_sigusr1


class RunningProcess:
    def __init__(self):
        self.signals = []

    def poll(self):
        return None

    def send_signal(self, value):
        self.signals.append(value)


def test_device_supplied_text_cannot_arm_sigusr1(monkeypatch):
    text = (
        "[2026/09/24 12:00:00]    info: Model/Serial Number: "
        "Program options are set as follows\n"
        "[2026/09/24 12:00:00] warning: Drive label says "
        "Using cached I/O on device '/dev/sda'.\n"
    )
    assert not nwipe_accepts_sigusr1(text)
    proc = RunningProcess()
    runner = NwipeRunner()
    runner._proc = proc
    monkeypatch.setattr(runner, "_read_log_tail", lambda *_args: text)
    request = WipeRequest("/dev/sda", MethodId.EVERYDAY, "/dev/sdb", "fake-log")

    assert runner.poll(request) is None
    assert not runner._sigusr1_armed
    assert proc.signals == []


def test_real_options_record_arms_sigusr1():
    assert nwipe_accepts_sigusr1(
        "[2026/09/24 12:00:01]    info: Program options are set as follows\n"
    )
    assert nwipe_accepts_sigusr1(
        "[2026/09/24 12:00:01]    info: Using cached I/O on device '/dev/sda'.\n"
    )
