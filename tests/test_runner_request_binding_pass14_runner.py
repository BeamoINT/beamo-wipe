"""An active erase must be classified with the request that launched it."""

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NwipeRunner
from beamo_wipe.safety import SafetyError


class ExitedProcess:
    returncode = 0

    def poll(self):
        return self.returncode


def test_poll_cannot_substitute_another_log_for_active_request(tmp_path):
    active_log = tmp_path / "active.log"
    other_log = tmp_path / "other.log"
    active_log.write_text("", encoding="utf-8")
    other_log.write_text("      vda | Erased | 120MB/s | 01:25:04 | model\n", encoding="utf-8")
    active = WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sdb", str(active_log))
    other = WipeRequest("/dev/vda", MethodId.EVERYDAY, "/dev/sdb", str(other_log))
    runner = NwipeRunner()
    proc = ExitedProcess()
    runner._proc = proc
    runner._active_request = active

    try:
        runner.poll(other)
    except SafetyError:
        pass
    else:
        raise AssertionError("a different log classified the active erase")

    assert runner._proc is proc
    assert runner.result is None
