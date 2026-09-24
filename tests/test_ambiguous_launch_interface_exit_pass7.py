"""A handleless but possibly spawned engine must reach supervisor recovery."""

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import NwipeRunner


def test_failed_interface_does_not_spin_forever_without_child_handle(monkeypatch):
    wizard = make_demo_wizard()
    runner = NwipeRunner(binary="/bin/true")
    # Popen may fork, then fail in the parent. It has no Popen handle but its
    # child inherited the wipe lock; the supervisor can recheck the process.
    runner._lock_fd = 12345
    wizard.runner = runner
    wizard.screen = Screen.WORKING
    wizard._wipe_request = object()
    monkeypatch.setattr(wizard, "tick", lambda: None)
    monkeypatch.setattr(
        "beamo_wipe.wizard.time.sleep",
        lambda _seconds: (_ for _ in ()).throw(AssertionError("settlement spun")),
    )
    wizard.settle_failed_interface()
    assert runner._lock_fd == 12345
