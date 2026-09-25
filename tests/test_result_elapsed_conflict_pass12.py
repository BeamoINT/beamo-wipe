"""Contradictory elapsed evidence must not be papered over by a duration hint."""

from beamo_wipe.result_summary import build_result_report_html, build_result_summary


def test_backwards_monotonic_timestamps_do_not_use_claimed_duration():
    evidence = {
        "timestamps": {
            "started_monotonic": 100.0,
            "ended_monotonic": 90.0,
            "duration_s": 10.0,
        }
    }

    assert "Elapsed: unavailable" in build_result_summary(evidence)
    assert '<th scope="row">Elapsed</th><td>unavailable</td>' in build_result_report_html(evidence)


def test_legacy_duration_only_report_still_displays_elapsed_time():
    assert "Elapsed: less than 1 minute" in build_result_summary(
        {"timestamps": {"duration_s": 10.0}}
    )
