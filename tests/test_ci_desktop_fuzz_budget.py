"""The hosted desktop fuzz gate terminates by completed work, not a timer race."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_fuzz_gate_requires_at_least_failed_build_execution_count():
    script = (ROOT / "scripts/ci-desktop.sh").read_text(encoding="utf-8")
    commands = [line for line in script.splitlines() if "-fuzz=FuzzBootOption" in line]
    assert len(commands) == 1
    command = commands[0]
    assert "-run='^$'" in command
    assert "-parallel=2" in command
    # Hosted build 4ba530b7 completed 346,790 executions, then its 15s
    # context deadline was reported as a failure with no crashing input.
    # A count budget preserves at least that much actual fuzz work.
    assert "-fuzztime=350000x" in command
    assert "-fuzztime=15s" not in command
