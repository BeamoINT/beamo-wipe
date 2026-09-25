"""A rejected power worker must not publish a later stale reading."""

import threading

from beamo_wipe import power


def test_thread_start_error_after_spawn_cannot_publish_power_status(monkeypatch):
    readings = []
    threads = []
    real_thread = threading.Thread

    class StartedThenRaised:
        def __init__(self, *, target, daemon, name):
            ready = threading.Event()
            proceed = threading.Event()

            def run():
                ready.set()
                proceed.wait()
                target()

            self.real = real_thread(target=run, daemon=daemon, name=name)
            self.ready = ready
            self.proceed = proceed
            threads.append(self.real)

        def start(self):
            self.real.start()
            assert self.ready.wait(2)
            self.proceed.set()
            raise RuntimeError("start interrupted after spawn")

    def read():
        readings.append(True)
        return power.PowerStatus(ac=True, complete=True)

    monkeypatch.setattr(power.threading, "Thread", StartedThenRaised)
    monitor = power.PowerMonitor(read)
    monitor.tick(0.0)
    threads[0].join(timeout=2)
    assert not threads[0].is_alive()
    assert readings == []
    assert monitor.status.ac is None
    assert monitor._results.empty()
