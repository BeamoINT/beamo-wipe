"""An incomplete final log record cannot prove nwipe finished."""

from beamo_wipe.models import MethodId, WipeRequest
from beamo_wipe.nwipe_runner import NWIPE_COMPLETION_LOG_BYTES, NwipeRunner, completion_for_method

STATUS = "********************************* Drive Status *********************************\n"
ERASED_ROW = "      sda | Erased |  120MB/s | 01:25:04 | QEMU/DISK"


class ExitedProcess:
    def poll(self):
        return 0


def test_unterminated_completion_markers_do_not_prove_success():
    for text in (
        STATUS + ERASED_ROW,
        "/dev/sda: 100.00%, round 1 of 1, pass 1 of 1, eta 00:00:00, [verifying]",
    ):
        ok, _summary, reason = completion_for_method(
            0, text, "/dev/sda", MethodId.EVERYDAY
        )
        assert not ok and reason == "indeterminate"


def test_exited_runner_rejects_unterminated_small_and_large_logs(tmp_path):
    padding = "ordinary message\n" * (
        NWIPE_COMPLETION_LOG_BYTES // len("ordinary message\n") + 1
    )
    for prefix in ("", padding):
        logfile = tmp_path / "nwipe.log"
        logfile.write_text(prefix + STATUS + ERASED_ROW, encoding="utf-8")
        runner = NwipeRunner()
        runner._proc = ExitedProcess()
        request = WipeRequest(
            device="/dev/sda", method=MethodId.EVERYDAY,
            boot_device="/dev/sdb", logfile=str(logfile),
        )

        result = runner.poll(request)

        assert result is not None and not result.ok
        assert result.reason == "indeterminate"


def test_complete_success_and_explicit_failure_still_classify():
    complete = (
        STATUS + ERASED_ROW + "\n",
        "/dev/sda: 100.00%, round 1 of 1, pass 1 of 1, eta 00:00:00, [verifying]\n",
    )
    for text in complete:
        ok, _summary, reason = completion_for_method(
            0, text, "/dev/sda", MethodId.EVERYDAY
        )
        assert ok and reason == "completed"

    for text in (
        "sda |-FAILED-|\n",
        "sda |-FAILED-|\npartial trailing note",
    ):
        ok, _summary, reason = completion_for_method(
            0, text, "/dev/sda", MethodId.EVERYDAY
        )
        assert not ok and reason == "engine_failed"
