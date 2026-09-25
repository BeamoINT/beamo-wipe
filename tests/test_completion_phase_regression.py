"""A completed write pass is not proof that read-back verification finished."""

import pytest

from beamo_wipe.evidence import OUTCOME_COMPLETED, OUTCOME_FAILED, OUTCOME_VERIFIED, _outcome_for
from beamo_wipe.models import MethodId, WipeResult
from beamo_wipe.nwipe_runner import completion_for_method


@pytest.mark.parametrize(
    ("method", "passes"),
    [(MethodId.EVERYDAY, 1), (MethodId.EXTRA, 3)],
)
def test_final_write_progress_does_not_prove_verification(method, passes):
    log = (
        f"/dev/vda: 100.00%, round 1 of 1, pass {passes} of {passes}, "
        "eta 00:00:00, [writing]\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, _, reason = completion_for_method(0, log, "/dev/vda", method)
    assert (ok, reason) == (False, "completion_missing")

    result = WipeResult(True, 0, "finished", "/tmp/nwipe.log")
    outcome, _ = _outcome_for(
        result=result,
        method=method,
        log_text=log,
        device="/dev/vda",
        interrupted=False,
        cancelled=False,
    )
    assert outcome == OUTCOME_FAILED


@pytest.mark.parametrize(
    ("method", "passes"),
    [(MethodId.EVERYDAY, 1), (MethodId.EXTRA, 3)],
)
def test_final_verification_progress_proves_method_completion(method, passes):
    log = (
        f"/dev/vda: 100.00%, round 1 of 1, pass {passes} of {passes}, "
        "eta 00:00:00, [verifying]\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, _, reason = completion_for_method(0, log, "/dev/vda", method)
    assert (ok, reason) == (True, "completed")
    result = WipeResult(True, 0, "finished", "/tmp/nwipe.log")
    outcome, _ = _outcome_for(
        result=result,
        method=method,
        log_text=log,
        device="/dev/vda",
        interrupted=False,
        cancelled=False,
    )
    assert outcome == OUTCOME_VERIFIED


def test_quick_zero_write_progress_remains_unverified_completion():
    log = (
        "/dev/vda: 100.00%, round 1 of 1, pass 1 of 1, eta 00:00:00, [writing]\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, _, reason = completion_for_method(0, log, "/dev/vda", MethodId.QUICK_ZERO)
    assert (ok, reason) == (True, "completed")
    result = WipeResult(True, 0, "finished", "/tmp/nwipe.log")
    outcome, _ = _outcome_for(
        result=result,
        method=MethodId.QUICK_ZERO,
        log_text=log,
        device="/dev/vda",
        interrupted=False,
        cancelled=False,
    )
    assert outcome == OUTCOME_COMPLETED


@pytest.mark.parametrize("suffix", ["", ", eta", ", eta garbage", ", eta 00:00:00, [writing] garbage"])
def test_quick_zero_rejects_incomplete_final_progress(suffix):
    log = (
        f"/dev/vda: 100.00%, round 1 of 1, pass 1 of 1{suffix}\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, _, reason = completion_for_method(0, log, "/dev/vda", MethodId.QUICK_ZERO)
    assert (ok, reason) == (False, "completion_missing")


def test_stray_verifying_word_after_writing_is_not_readback_proof():
    log = (
        "/dev/vda: 100.00%, round 1 of 1, pass 1 of 1, "
        "eta 00:00:00, [writing] garbage [verifying]\n"
        "Nwipe successfully completed. See summary table for details.\n"
    )
    ok, _, reason = completion_for_method(0, log, "/dev/vda", MethodId.EVERYDAY)
    assert (ok, reason) == (False, "completion_missing")
