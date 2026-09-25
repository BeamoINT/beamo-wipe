"""A bounded progress tail must not turn the middle of a log line into telemetry."""

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NWIPE_PROGRESS_LOG_BYTES, NwipeRunner, nwipe_accepts_sigusr1


def test_cut_progress_tail_does_not_trust_a_fragment_of_another_record(tmp_path):
    sample = (
        "/dev/vda: 89.00%, round 1 of 1, pass 1 of 1, "
        "eta 0001:00:00, [writing]\n"
    )
    # The full first record is a model string. The bounded tail starts just
    # after its prefix, which otherwise turns the suffix into fake telemetry.
    filler = "X" * (NWIPE_PROGRESS_LOG_BYTES - len(sample) - 1) + "\n"
    log = tmp_path / "nwipe.log"
    log.write_text("info: Model: " + sample + filler, encoding="utf-8")

    runner = NwipeRunner()
    runner._refresh_progress(str(log), "/dev/vda")

    assert runner.progress_observation is None
    assert runner.progress is None


def test_cut_progress_tail_keeps_a_later_complete_sample(tmp_path):
    forged = (
        "/dev/vda: 89.00%, round 1 of 1, pass 1 of 1, "
        "eta 0001:00:00, [writing]\n"
    )
    real = (
        "/dev/vda: 20.00%, round 1 of 1, pass 1 of 1, "
        "eta 0001:30:00, [writing]\n"
    )
    filler = "X" * (NWIPE_PROGRESS_LOG_BYTES - len(forged) - len(real) - 1) + "\n"
    log = tmp_path / "nwipe.log"
    log.write_text("info: Model: " + forged + filler + real, encoding="utf-8")

    runner = NwipeRunner()
    runner._refresh_progress(str(log), "/dev/vda")

    assert runner.progress_observation is not None
    assert runner.progress_observation.percent == 20.0
    assert runner.progress == 20.0


def test_cut_log_tail_cannot_arm_early_sigusr1(tmp_path):
    ready = "Program options are set as follows\n"
    filler = "X" * (65536 - len(ready) - 1) + "\n"
    log = tmp_path / "nwipe.log"
    log.write_text("info: Model: " + ready + filler, encoding="utf-8")

    class FakeProcess:
        returncode = None

        def __init__(self):
            self.signals = []

        def poll(self):
            return None

        def send_signal(self, sig):
            self.signals.append(sig)

    request = WipeRequest(
        device="/dev/vda", method=MethodId.EVERYDAY,
        boot_device="/dev/sr0", logfile=str(log),
    )
    runner = NwipeRunner()
    proc = FakeProcess()
    runner._proc = proc
    runner._active_request = request

    assert runner.poll(request) is None
    assert not runner._sigusr1_armed
    assert proc.signals == []


def test_unterminated_readiness_record_cannot_arm_sigusr1(tmp_path):
    log = tmp_path / "nwipe.log"
    log.write_text("info: Program options are set as follows", encoding="utf-8")
    assert not nwipe_accepts_sigusr1(log.read_text(encoding="utf-8"))

    class FakeProcess:
        returncode = None

        def __init__(self):
            self.signals = []

        def poll(self):
            return None

        def send_signal(self, sig):
            self.signals.append(sig)

    request = WipeRequest(
        device="/dev/vda", method=MethodId.EVERYDAY,
        boot_device="/dev/sr0", logfile=str(log),
    )
    runner = NwipeRunner()
    proc = FakeProcess()
    runner._proc = proc
    runner._active_request = request

    assert runner.poll(request) is None
    assert not runner._sigusr1_armed
    assert proc.signals == []


def test_complete_record_at_exact_tail_boundary_is_still_readable(tmp_path):
    ready = "info: Program options are set as follows\n"
    filler = "X" * (65536 - len(ready) - 1) + "\n"
    log = tmp_path / "nwipe.log"
    log.write_text("earlier record\n" + ready + filler, encoding="utf-8")

    runner = NwipeRunner()
    tail = runner._read_log_tail(str(log), 65536)

    assert runner._log_read_state.truncated
    assert nwipe_accepts_sigusr1(runner._complete_log_records(tail))
