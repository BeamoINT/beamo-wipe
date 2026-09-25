"""A stuck optional outcome player must not accumulate processes or reapers."""

import subprocess
import threading

from beamo_wipe import sound


def test_outcome_player_reaper_bounds_a_hung_process(monkeypatch):
    calls = []
    threads = []
    real_thread = threading.Thread

    class HungPlayer:
        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if timeout == sound._PLAY_TIMEOUT:
                raise subprocess.TimeoutExpired("paplay", timeout)
            return -15

        def terminate(self):
            calls.append(("terminate", None))

    class TrackedThread:
        def __init__(self, *, target, daemon):
            self.real = real_thread(target=target, daemon=daemon)
            threads.append(self.real)

        def start(self):
            self.real.start()

    monkeypatch.setattr(
        "beamo_wipe.safety.resolve_system_binary", lambda _tool: "/usr/bin/paplay"
    )
    monkeypatch.setattr(sound.subprocess, "Popen", lambda *_a, **_k: HungPlayer())
    monkeypatch.setattr(sound.threading, "Thread", TrackedThread)

    assert sound._popen("paplay", ["/fake/attention.wav"]) is not None
    threads[0].join(timeout=2)
    assert not threads[0].is_alive()
    assert calls == [
        ("wait", sound._PLAY_TIMEOUT),
        ("terminate", None),
        ("wait", 1),
    ]
