# SPDX-License-Identifier: GPL-3.0-or-later
"""Measured release evidence: complete, skipped, partial, failed, tampered,
reproducible — plus parser, secret, environment, and timestamp rules."""

from __future__ import annotations

import json

import pytest

from beamo_wipe.verification_evidence import (
    OPTIONAL_GATES,
    REQUIRED_GATES,
    build_gate_receipt,
    build_package_inventory,
    build_test_evidence,
    canonical_digest,
    normalize_utc,
    parse_dpkg_status,
    parse_junit_xml,
    sanitize_environment,
    verify_gate_receipt,
    verify_package_inventory,
    verify_release_evidence,
)

COMMIT = "a" * 40
ENV = {"runner": "test", "platform": "linux", "arch": "x86_64"}
APT = ["https://deb.debian.org/debian/"]
T0 = "2026-09-11T00:00:00Z"
T1 = "2026-09-11T00:00:01Z"

JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest" errors="0" failures="0" skipped="2" tests="3" time="0.028" timestamp="2026-09-11T12:41:11.568995-05:00" hostname="MacBook-Air-7.local"><testcase classname="pkg" name="test_pass" time="0.000" /><testcase classname="pkg" name="test_skip" time="0.000"><skipped type="pytest.skip" message="no display">/tmp/x.py:3: no display</skipped></testcase><testcase classname="pkg" name="test_xfail" time="0.000"><skipped type="pytest.xfail" message="known gap" /></testcase></testsuite></testsuites>"""  # noqa: E501

STATUS_DB = """Package: base-files
Status: install ok installed
Version: 12.4+deb12u5
Architecture: amd64
Source: base-files

Package: bash
Status: install ok installed
Version: 5.2.15-2+b2
Architecture: amd64

Package: old-pkg
Status: deinstall ok config-files
Version: 1.0
Architecture: amd64
"""


def _measured(**over) -> dict:
    base = {
        "passed": 10,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
        "xfailed": 0,
        "deselected": 0,
        "total": 11,
    }
    base.update(over)
    return base


def _receipt(gate: str, **over) -> dict:
    args: dict = {
        "gate": gate,
        "status": "pass",
        "command": f"run {gate}",
        "source_commit": COMMIT,
        "build_id": "local",
        "environment": dict(ENV),
        "measured": _measured(),
        "skips": [{"id": f"{gate}.probe", "kind": "skip", "reason": "fixture-only"}],
        "log_sha256": "b" * 64,
        "started_at": T0,
        "ended_at": T1,
    }
    args.update(over)
    return build_gate_receipt(**args)


def _complete_gates(**over) -> dict:
    return {gate: _receipt(gate, **over.get(gate, {})) for gate in REQUIRED_GATES}


def _inventory(**over) -> dict:
    args: dict = {
        "packages": [
            {"name": "base-files", "version": "1", "arch": "amd64", "source": ""}
        ],
        "collected_from": "squashfs var/lib/dpkg/status",
        "apt_sources": list(APT),
        "source_commit": COMMIT,
        "generated_at": T0,
    }
    args.update(over)
    return build_package_inventory(**args)


def test_receipt_cannot_be_relabelled_as_another_gate():
    gates = _complete_gates()
    gates["qemu"] = gates["tests"]
    with pytest.raises(RuntimeError, match="gate name"):
        verify_release_evidence({"schema": "beamo-wipe-test-evidence/1", "gates": gates})


def test_evidence_rejects_duplicate_receipts():
    receipts = list(_complete_gates().values())
    with pytest.raises(RuntimeError, match="duplicate"):
        build_test_evidence(receipts + [receipts[0]])


def test_evidence_rejects_tampered_aggregate_digest():
    evidence = build_test_evidence(list(_complete_gates().values()))
    evidence["evidence_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="evidence digest"):
        verify_release_evidence(evidence)


def test_complete_evidence_verifies():
    evidence = build_test_evidence(list(_complete_gates().values()))
    assert evidence["measured"] is True
    assert set(evidence["gates"]) >= set(REQUIRED_GATES)
    assert all(r["status"] == "pass" for r in evidence["gates"].values())
    assert len(evidence["evidence_sha256"]) == 64
    verified = verify_release_evidence(evidence)
    assert set(verified) >= set(REQUIRED_GATES)


def test_skipped_optional_gate_verifies_with_reason():
    gates = _complete_gates()
    gates["desktop-launchers"] = _receipt(
        "desktop-launchers",
        status="skip",
        measured={
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "xfailed": 0,
            "deselected": 0,
            "total": 1,
        },
        skips=[],
        log_sha256="",
        reason="no desktop changes in scope",
    )
    verified = verify_release_evidence(
        {"schema": "beamo-wipe-test-evidence/1", "gates": gates}
    )
    assert verified["desktop-launchers"]["status"] == "skip"


def test_skipped_required_gate_fails():
    gates = _complete_gates()
    gates["qemu"] = _receipt(
        "qemu",
        status="skip",
        measured={
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "xfailed": 0,
            "deselected": 0,
            "total": 1,
        },
        skips=[],
        log_sha256="",
        reason="worker unavailable",
    )
    with pytest.raises(RuntimeError, match="did not pass"):
        verify_release_evidence({"schema": "beamo-wipe-test-evidence/1", "gates": gates})


def test_partial_evidence_missing_gate_fails():
    gates = _complete_gates()
    del gates["iso"]
    with pytest.raises(RuntimeError, match="missing required gate 'iso'"):
        verify_release_evidence({"schema": "beamo-wipe-test-evidence/1", "gates": gates})


def test_failed_gate_fails_including_optional():
    gates = _complete_gates()
    gates["tests"] = _receipt(
        "tests",
        status="fail",
        measured=_measured(passed=9, failed=1, total=11),
        log_sha256="c" * 64,
    )
    with pytest.raises(RuntimeError, match="did not pass"):
        verify_release_evidence({"schema": "beamo-wipe-test-evidence/1", "gates": gates})
    gates2 = _complete_gates()
    gates2["desktop-launchers"] = _receipt(
        "desktop-launchers",
        status="fail",
        measured={
            "passed": 0,
            "failed": 1,
            "errors": 0,
            "skipped": 0,
            "xfailed": 0,
            "deselected": 0,
            "total": 1,
        },
        skips=[],
        log_sha256="c" * 64,
    )
    with pytest.raises(RuntimeError, match="failed"):
        verify_release_evidence({"schema": "beamo-wipe-test-evidence/1", "gates": gates2})


def test_tampered_receipt_fails_on_digest():
    receipt = _receipt("tests")
    receipt["measured"]["passed"] = 999
    with pytest.raises(RuntimeError, match="digest mismatch"):
        verify_gate_receipt(receipt)


def test_tampered_inventory_fails_on_digest():
    inventory = _inventory()
    inventory["packages"].append(
        {"name": "evil", "version": "9", "arch": "amd64", "source": ""}
    )
    with pytest.raises(RuntimeError, match="digest mismatch"):
        verify_package_inventory(inventory)


def test_unknown_gate_is_rejected():
    gates = _complete_gates()
    forged = dict(_receipt("tests"))
    forged.pop("receipt_sha256")
    forged["gate"] = "free-pass"
    with pytest.raises(RuntimeError, match="unknown"):
        verify_release_evidence(
            {"schema": "beamo-wipe-test-evidence/1", "gates": {**gates, "free-pass": forged}}
        )


def test_reproducible_receipt_bytes():
    first = _receipt("tests")
    second = _receipt("tests")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["receipt_sha256"] == second["receipt_sha256"]
    shuffled = _receipt(
        "tests",
        skips=[
            {"id": "b.case", "kind": "skip", "reason": "r"},
            {"id": "a.case", "kind": "skip", "reason": "r"},
        ],
        measured=_measured(passed=9, skipped=2, total=11),
    )
    ordered = _receipt(
        "tests",
        skips=[
            {"id": "a.case", "kind": "skip", "reason": "r"},
            {"id": "b.case", "kind": "skip", "reason": "r"},
        ],
        measured=_measured(passed=9, skipped=2, total=11),
    )
    assert shuffled["receipt_sha256"] == ordered["receipt_sha256"]


def test_reproducible_inventory_bytes():
    first = _inventory()
    again = build_package_inventory(
        packages=[{"name": "base-files", "version": "1", "arch": "amd64", "source": ""}],
        collected_from="squashfs var/lib/dpkg/status",
        apt_sources=list(APT),
        source_commit=COMMIT,
        generated_at=T0,
    )
    assert first["inventory_sha256"] == again["inventory_sha256"]


def test_junit_parser_measures_and_strips_host_details():
    measured = parse_junit_xml(JUNIT)
    assert (measured["passed"], measured["skipped"], measured["xfailed"]) == (1, 1, 1)
    assert measured["total"] == 3
    assert measured["skips"] == [
        {"id": "pkg.test_skip", "kind": "skip", "reason": "no display"},
        {"id": "pkg.test_xfail", "kind": "xfail", "reason": "known gap"},
    ]
    blob = json.dumps(measured)
    assert "MacBook" not in blob and "/tmp/x.py" not in blob


def test_junit_parser_rejects_garbage():
    with pytest.raises(RuntimeError, match="no testsuite|not valid XML"):
        parse_junit_xml("<nope/>")
    with pytest.raises(RuntimeError, match="not valid XML"):
        parse_junit_xml("not xml at all {{{")


def test_dpkg_parser_keeps_installed_with_provenance():
    packages = parse_dpkg_status(STATUS_DB)
    assert [(p["name"], p["version"], p["arch"]) for p in packages] == [
        ("base-files", "12.4+deb12u5", "amd64"),
        ("bash", "5.2.15-2+b2", "amd64"),
    ]
    assert packages[0]["source"] == "base-files"
    inventory = build_package_inventory(
        packages=packages,
        collected_from="squashfs var/lib/dpkg/status",
        apt_sources=list(APT),
        source_commit=COMMIT,
        generated_at=T0,
    )
    assert inventory["package_count"] == 2
    assert verify_package_inventory(inventory)["package_count"] == 2


def test_dpkg_parser_rejects_empty_and_duplicates():
    with pytest.raises(RuntimeError, match="empty"):
        parse_dpkg_status("   \n")
    with pytest.raises(RuntimeError, match="twice"):
        parse_dpkg_status(
            "Package: a\nStatus: install ok installed\nVersion: 1\nArchitecture: amd64\n\n"
            "Package: a\nStatus: install ok installed\nVersion: 2\nArchitecture: amd64\n"
        )


def test_receipt_rejects_secrets_and_host_details():
    with pytest.raises(RuntimeError, match="secret"):
        _receipt("tests", command="run tests ghp_abcdefgh12345678")
    with pytest.raises(RuntimeError, match="must not carry"):
        _receipt("tests", environment={"hostname": "build-1", "platform": "linux"})
    with pytest.raises(RuntimeError, match="must not carry"):
        _receipt("tests", environment={"GITHUB_TOKEN": "x", "platform": "linux"})


def test_receipt_rejects_empty_required_fields_and_naive_time():
    import datetime

    with pytest.raises(RuntimeError, match="missing its executed command"):
        _receipt("tests", command="   ")
    with pytest.raises(RuntimeError, match="missing its log hash"):
        _receipt("tests", log_sha256="")
    with pytest.raises(RuntimeError, match="skipped without a reason"):
        _receipt(
            "tests",
            status="skip",
            measured={
                "passed": 1,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "xfailed": 0,
                "deselected": 0,
                "total": 1,
            },
            skips=[],
            log_sha256="",
            reason="",
        )
    with pytest.raises(RuntimeError, match="naive datetime"):
        _receipt("tests", started_at=datetime.datetime(2026, 9, 11, 0, 0, 0))
    assert normalize_utc("2026-09-11T00:00:00+00:00") == T0


def test_environment_sanitizer_keeps_stable_facts():
    env = sanitize_environment(
        {"runner": "cloudbuild", "cpus": 8, "kvm": True}, what="probe"
    )
    assert env == {"runner": "cloudbuild", "cpus": 8, "kvm": True}
    with pytest.raises(RuntimeError, match="bad type"):
        sanitize_environment({"tags": ["a"]}, what="probe")


def test_evidence_must_share_one_commit():
    gates = _complete_gates()
    gates["iso"] = _receipt("iso", source_commit="d" * 40)
    with pytest.raises(RuntimeError, match="more than one source commit"):
        verify_release_evidence({"schema": "beamo-wipe-test-evidence/1", "gates": gates})


def test_cli_parse_junit_and_verify_receipts(tmp_path, capsys):
    from beamo_wipe.verification_evidence import main

    xml = tmp_path / "tests.xml"
    xml.write_text(
        '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="1">'
        '<testcase classname="a" name="t" time="0.001"/></testsuite>',
        encoding="utf-8",
    )
    out = tmp_path / "tests.receipt.json"
    assert (
        main(
            [
                "parse-junit",
                "--gate", "tests",
                "--status", "pass",
                "--exec-command", "python3 -m pytest",
                "--commit", COMMIT,
                "--build-id", "local",
                "--xml", str(xml),
                "--log-sha256", "b" * 64,
                "--env", "platform=linux",
                "--started-at", T0,
                "--ended-at", T1,
                "--out", str(out),
            ]
        )
        == 0
    )
    assert json.loads(out.read_text(encoding="utf-8"))["receipt_sha256"]
    with pytest.raises(RuntimeError, match="missing required gate"):
        main(["verify-receipts", "--receipt", str(out)])


def test_optional_gates_are_known():
    assert set(OPTIONAL_GATES) == {"desktop-launchers"}
    assert not (set(REQUIRED_GATES) & set(OPTIONAL_GATES))
    digest = canonical_digest({"b": [1, 2], "a": 1})
    assert digest == canonical_digest({"a": 1, "b": [1, 2]})
