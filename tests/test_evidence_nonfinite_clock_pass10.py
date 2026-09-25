"""A broken monotonic clock cannot prevent an off-target result report."""

import json

import pytest

from beamo_wipe.evidence import build_evidence, write_evidence_atomic
from beamo_wipe.models import MethodId, WipeResult
from beamo_wipe.wizard import make_demo_wizard


@pytest.mark.parametrize(
    ("started", "ended"),
    [(0.0, float("inf")), (float("inf"), float("inf")), (float("nan"), 3.0)],
)
def test_nonfinite_clock_values_do_not_break_evidence_publication(
    tmp_path, started, ended
):
    discovery = make_demo_wizard().discovery
    disk = discovery.selectable[0]
    evidence = build_evidence(
        disk=disk,
        discovery=discovery,
        method=MethodId.EVERYDAY,
        request=None,
        result=WipeResult(ok=False, exit_code=1, summary="failed", logfile=""),
        started_at_wall=None,
        ended_at_wall=None,
        started_mono=started,
        ended_mono=ended,
        argv=[],
        log_text="",
    )

    path = write_evidence_atomic(
        evidence, log_dir=tmp_path, device_path=disk.path, target_device=disk.path
    )

    stamps = json.loads(path.read_text(encoding="utf-8"))["timestamps"]
    assert stamps["duration_s"] is None
    assert stamps["started_monotonic"] is None or stamps["started_monotonic"] == 0.0
    assert stamps["ended_monotonic"] is None or stamps["ended_monotonic"] == 3.0
