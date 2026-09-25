"""Incomplete fake telemetry must not choose the last write over read-back."""

from beamo_wipe.progress import locate_stage, observe, plan_stages


def test_final_pass_without_phase_does_not_claim_overwrite_stage():
    record = (
        "/dev/vda: 40.00%, round 1 of 1, pass 3 of 3, "
        "eta 00:10:00, [unknown]\n"
    )
    observation = observe(record, "/dev/vda")
    assert observation is not None
    assert observation.phase == "Phase not reported"

    assert locate_stage(plan_stages(3, True), observation) == (None, False)


def test_nonfinal_pass_without_phase_still_uses_unambiguous_counter():
    record = (
        "/dev/vda: 40.00%, round 1 of 1, pass 2 of 3, "
        "eta 00:10:00, [unknown]\n"
    )
    observation = observe(record, "/dev/vda")
    assert observation is not None

    assert locate_stage(plan_stages(3, True), observation) == (1, False)
