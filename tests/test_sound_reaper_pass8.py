"""A failed sound reaper cannot crash the outcome screen."""

import threading

from beamo_wipe import copy as C
from beamo_wipe import sound


def test_reaper_launch_failure_stops_playback_and_returns_failure(monkeypatch):
    calls = []

    class FakeProc:
        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            calls.append("wait")
            return -15

    class ReaperCannotStart:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(sound, "_ready", lambda _kind: (True, ""))
    monkeypatch.setattr(sound, "ensure_audio", lambda: True)
    monkeypatch.setattr(
        "beamo_wipe.safety.resolve_system_binary", lambda _tool: "/usr/bin/paplay"
    )
    monkeypatch.setattr(sound.subprocess, "Popen", lambda *_a, **_k: FakeProc())
    monkeypatch.setattr(sound.threading, "Thread", ReaperCannotStart)
    result = sound.play_outcome(sound.KIND_ATTENTION)
    assert result == sound.SoundResult(False, C.SOUND_PLAY_FAILED)
    assert calls == ["terminate", "wait"]


def test_reaper_start_error_after_spawn_does_not_wait_twice(monkeypatch):
    calls = []
    spawned = []
    real_thread = threading.Thread

    class FakeProc:
        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            calls.append("wait")
            return -15

    class SpawnThenRaise:
        def __init__(self, *, target, daemon):
            self.real = real_thread(target=target, daemon=daemon)
            spawned.append(self.real)

        def start(self):
            self.real.start()
            raise RuntimeError("start failed after spawn")

    monkeypatch.setattr(sound, "_ready", lambda _kind: (True, ""))
    monkeypatch.setattr(sound, "ensure_audio", lambda: True)
    monkeypatch.setattr(
        "beamo_wipe.safety.resolve_system_binary", lambda _tool: "/usr/bin/paplay"
    )
    monkeypatch.setattr(sound.subprocess, "Popen", lambda *_a, **_k: FakeProc())
    monkeypatch.setattr(sound.threading, "Thread", SpawnThenRaise)
    assert sound.play_outcome(sound.KIND_FINISHED) == sound.SoundResult(
        False, C.SOUND_PLAY_FAILED
    )
    spawned[0].join(timeout=2)
    assert not spawned[0].is_alive()
    assert calls == ["terminate", "wait"]
