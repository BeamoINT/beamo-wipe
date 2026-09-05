# SPDX-License-Identifier: GPL-3.0-or-later
"""Production runbook coverage — no forbidden bypass, safe repro, evidence, rollback."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _lower(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8").lower()


def test_runbook_exists_and_is_versioned():
    text = _lower("docs/runbook.md")
    assert "version 1.1" in text
    assert "next review" in text
    assert "owner" in text
    assert "beamo wipe" in text
    assert "0.2.2" in text
    assert "nwipe v0.42" in text
    assert "6082bde" in text


def test_runbook_covers_all_decision_trees():
    text = _lower("docs/runbook.md")
    for heading in (
        "failed boot",
        "blank / low-resolution",
        "missing disks",
        "extra disks",
        "uncertain boot media",
        "confirmation failures",
        "interrupted wipes",
        "nwipe errors",
        "ambiguous results",
        "log collection",
    ):
        assert heading in text, f"runbook missing tree: {heading}"


def test_runbook_defines_severity_and_escalation_and_rollback():
    text = _lower("docs/runbook.md")
    for heading in (
        "severity",
        "escalation",
        "evidence",  # evidence checklist section
        "redaction",
        "customer communication",
        "rollback",  # release rollback
        "quarantine",  # artifact quarantine
        "stop-ship",
    ):
        assert heading in text, f"runbook missing: {heading}"


def test_runbook_has_safe_reproduction_section_with_prohibitions():
    text = _lower("docs/runbook.md")
    assert "fake fixtures first" in text
    # allow either phrasing for qemu
    assert "isolated" in text and "qemu" in text and "disposable" in text
    assert "prohibitions" in text
    assert "beamo_wipe_dry_run=1" in text
    assert "scripts/qemu-verify.sh" in text
    assert "mktemp" in text
    assert "findmnt" in text
    assert "losetup -j" in text
    # must mention not to run on dev disk (markdown may wrap `nwipe` in backticks)
    assert "never run" in text and "against a real" in text


def test_runbook_walkthroughs_present():
    text = _lower("docs/runbook.md")
    # Three incident walk-throughs
    assert "walk-through inc-1" in text
    assert "walk-through inc-2" in text
    assert "walk-through inc-3" in text
    # each should have gaps/timing/handoffs
    assert "gap found" in text
    assert "handoff" in text
    assert "t+0:" in text


def test_runbook_never_instructs_bypass():
    text = _lower("docs/runbook.md")
    # Prohibited bypass instructions must never appear as a *directive* to the user.
    # Each is documented inside the prohibitions table (header or row) or with a negation nearby,
    # not as a step to do it. Table rows start with "|" and headers are allowed.
    # Log-marker verbatim lines that document nwipe's own message are also allowed.
    for forbidden in (
        "disable boot-media exclusion",
        "skip confirmations",
        "skip the owner checkbox",
        "--force",
    ):
        if forbidden in text:
            for line in text.splitlines():
                if forbidden not in line.lower():
                    continue
                stripped = line.strip()
                if stripped.startswith("|") or stripped.startswith("#"):
                    # table row documenting prohibition or heading
                    continue
                # allow escalation/rollback prose that uses "no handoff may add" style prohibition
                if "no handoff" in line.lower():
                    continue
                # allow log-marker verbatim lines that document nwipe's own output
                if "--force" in line.lower() and "is in use" in line.lower():
                    continue
                assert any(
                    neg in line.lower()
                    for neg in (
                        "must not",
                        "never",
                        "do not",
                        "forbidden",
                        "not allowed",
                        "prohibit",
                        "no ",
                        "never a",
                    )
                ) or "prohibitions" in line.lower() or "prohibited" in line.lower(), (
                    f"runbook appears to instruct bypass: {line[:160]}"
                )


def test_runbook_does_not_target_dev_disk_manually():
    text = _lower("docs/runbook.md")
    # Must not say "target /dev/sda manually" as a support step
    for line in text.splitlines():
        # look for manual targeting guidance outside the code that validates it
        if "/dev/sda" in line and "manually" in line and "target" in line:
            assert "not" in line or "never" in line or "must not" in line


def test_runbook_references_storage_limits_and_not_certified():
    text = _lower("docs/runbook.md")
    assert "storage-and-controller-limits" in text
    assert "not a formal certificate" in text or "not a lab certificate" in text
    assert "wear-leveling" in text or "wear leveling" in text


def test_runbook_evidence_checklist_has_redaction():
    text = _lower("docs/runbook.md")
    assert "redaction" in text
    assert "serial" in text
    assert "hmac" not in text  # no inventing hmac redaction
    assert "evidence" in text and "log_checksum" in text


def test_runbook_matches_fail_closed_completion_and_authenticated_log_export():
    text = _lower("docs/runbook.md")
    assert "exit 0, no markers" not in text
    assert "log over 8 mib" not in text
    assert "explicit successful completion marker" in text
    assert "authenticated log suffix" in text


def test_startup_reports_are_separate_and_minimal():
    text = _lower("docs/runbook.md")
    assert "diagnostic.json" in text and "not erase evidence" in text
    assert "do not apply to startup diagnostics" in text
