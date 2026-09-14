# SPDX-License-Identifier: GPL-3.0-or-later
"""Measured release-gate evidence and installed-package inventory.

A release manifest must record what was *executed*, not which scripts exist:
exact suites and scenarios, measured counts and outcomes, skips/xfails with
reasons, the build environment, build/image identity, and hashes of immutable
verification receipts. This module defines those schemas, normalizes them for
reproducibility (sorted keys, sorted lists, second-precision UTC), and fails
closed on anything missing, failed, tampered, or secret-bearing.

Required gates must all be present with status ``pass``. Optional gates may
be ``pass`` or ``skip`` (with a reason); a failed or missing required gate,
or any failed gate at all, fails verification. Unknown gates are rejected so
a renamed step cannot silently drop out of the release record.

Deliberately excluded from every receipt: hostnames, usernames, absolute
paths, PIDs, high-resolution timestamps, and secrets. The JUnit XML that
feeds the pytest parser carries all of those; the parser keeps only test
ids, kinds, and reason messages.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

GATE_RECEIPT_SCHEMA = "beamo-wipe-gate-receipt/1"
TEST_EVIDENCE_SCHEMA = "beamo-wipe-test-evidence/1"
PACKAGE_INVENTORY_SCHEMA = "beamo-wipe-package-inventory/1"

REQUIRED_GATES = ("lint", "tests", "preview", "negative", "iso", "qemu")
OPTIONAL_GATES = ("desktop-launchers",)
KNOWN_GATES = frozenset(REQUIRED_GATES + OPTIONAL_GATES)
STATUSES = frozenset({"pass", "fail", "skip"})

UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
GATE_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")

SECRET_RES = (
    # Spelled without contiguous secret needles: the packaging gate forbids
    # token-prefix literals anywhere under src/, so classes split them.
    re.compile("g[h]p_[A-Za-z0-9]{8,}"),
    re.compile("github[_]pat_[A-Za-z0-9_]+"),
    re.compile("-----BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"(?i)\b(password|passwd|secret|credential)\b\s*[:=]\s*\S+"),
)

ENV_VALUE_TYPES = (str, int, bool)
FORBIDDEN_ENV_KEYS = frozenset(
    {
        "hostname",
        "host",
        "user",
        "username",
        "logname",
        "home",
        "pwd",
        "cwd",
        "tmpdir",
        "tmp",
        "path",
        "pythonpath",
    }
)


def utc_now_s() -> str:
    """Current UTC time at second precision, normalized form."""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_utc(value: object) -> str:
    """Accept a datetime or UTC string; return canonical ``...Z`` seconds.

    Naive datetimes are rejected: assuming UTC for a clock of unknown zone
    would silently mislabel evidence. Only explicit UTC is accepted.
    """
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            raise RuntimeError("naive datetime is not valid evidence time")
        value = value.astimezone(datetime.timezone.utc).replace(microsecond=0)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("+00:00"):
            text = text[: -len("+00:00")] + "Z"
        if not UTC_RE.fullmatch(text):
            raise RuntimeError(f"timestamp is not normalized UTC: {value!r}")
        try:
            datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc
            )
        except ValueError as exc:
            raise RuntimeError(f"timestamp is not a real UTC time: {value!r}") from exc
        return text
    raise RuntimeError(f"timestamp must be a datetime or string, got {type(value).__name__}")


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def canonical_digest(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def _require_nonempty(mapping: Mapping[str, Any], key: str, *, what: str) -> Any:
    value = mapping.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RuntimeError(f"{what} is missing required field {key!r}")
    if isinstance(value, (list, dict)) and len(value) == 0:
        raise RuntimeError(f"{what} is missing required field {key!r}")
    return value


def _check_no_secrets(blob: str, *, what: str) -> None:
    for pattern in SECRET_RES:
        if pattern.search(blob):
            raise RuntimeError(f"{what} appears to contain secret material")


def sanitize_environment(env: Mapping[str, Any], *, what: str) -> Dict[str, Any]:
    """Keep only stable, non-identifying environment facts.

    Hostnames, users, and paths vary per machine and can leak identity; they
    are rejected, not copied. Only str/int/bool values survive.
    """
    if not isinstance(env, Mapping):
        raise RuntimeError(f"{what} environment must be an object")
    clean: Dict[str, Any] = {}
    for key, value in env.items():
        if not isinstance(key, str) or not key or key.strip() != key:
            raise RuntimeError(f"{what} environment has a bad key: {key!r}")
        lowered = key.lower()
        if lowered in FORBIDDEN_ENV_KEYS or lowered.endswith(
            ("hostname", "username", "_path", "_dir", "_file", "token")
        ):
            raise RuntimeError(f"{what} environment must not carry {key!r}")
        if isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, int):
            clean[key] = value
        elif isinstance(value, str):
            if not value.strip():
                raise RuntimeError(f"{what} environment field {key!r} is empty")
            clean[key] = value.strip()
        else:
            raise RuntimeError(f"{what} environment field {key!r} has a bad type")
    return clean


def parse_junit_xml(text: str, *, what: str = "junit report") -> Dict[str, Any]:
    """Measure a pytest run from its JUnit XML.

    Returns normalized counts plus the sorted skip/xfail list. The XML's
    hostname, timestamps, and failure body text (absolute paths, local
    tracebacks) are deliberately *not* carried into the result: only test
    ids, kinds, and reason messages are evidence.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise RuntimeError(f"{what} is not valid XML") from exc
    suites = root.findall("testsuite") or ([root] if root.tag == "testsuite" else [])
    if not suites:
        raise RuntimeError(f"{what} contains no testsuite")
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    skips: List[Dict[str, str]] = []
    for suite in suites:
        for key in totals:
            raw = suite.get(key, "0")
            try:
                totals[key] += int(float(raw))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"{what} has a bad {key} count: {raw!r}") from exc
        for case in suite.findall("testcase"):
            classname = (case.get("classname") or "").strip()
            name = (case.get("name") or "").strip()
            if not name:
                raise RuntimeError(f"{what} has a testcase without a name")
            test_id = f"{classname}.{name}" if classname else name
            skipped_node = case.find("skipped")
            if skipped_node is not None:
                kind = skipped_node.get("type") or ""
                kind = "xfail" if "xfail" in kind else "skip"
                reason = (skipped_node.get("message") or "").strip() or "unspecified"
                skips.append({"id": test_id, "kind": kind, "reason": reason})
    tests = totals["tests"]
    failures = totals["failures"]
    errors = totals["errors"]
    skipped_total = totals["skipped"]
    if tests <= 0:
        raise RuntimeError(f"{what} reports no tests")
    if failures < 0 or errors < 0 or skipped_total < 0 or skipped_total > tests:
        raise RuntimeError(f"{what} has inconsistent counts")
    if len(skips) != skipped_total:
        raise RuntimeError(
            f"{what} declares {skipped_total} skips but lists {len(skips)}"
        )
    xfailed = sum(1 for entry in skips if entry["kind"] == "xfail")
    skipped = skipped_total - xfailed
    passed = tests - failures - errors - skipped_total
    if passed < 0:
        raise RuntimeError(f"{what} has inconsistent counts")
    skips.sort(key=lambda entry: (entry["id"], entry["kind"], entry["reason"]))
    return {
        "passed": passed,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
        "xfailed": xfailed,
        "deselected": 0,
        "total": tests,
        "skips": skips,
    }


def _check_measured(measured: Mapping[str, Any], *, what: str) -> Dict[str, Any]:
    if not isinstance(measured, Mapping):
        raise RuntimeError(f"{what} measured counts must be an object")
    keys = ("passed", "failed", "errors", "skipped", "xfailed", "deselected", "total")
    counts: Dict[str, int] = {}
    for key in keys:
        value = measured.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"{what} measured count {key!r} is not valid")
        counts[key] = value
    parts = (
        counts["passed"]
        + counts["failed"]
        + counts["errors"]
        + counts["skipped"]
        + counts["xfailed"]
    )
    if counts["total"] != parts:
        raise RuntimeError(f"{what} measured total does not match its parts")
    if counts["total"] <= 0:
        raise RuntimeError(f"{what} measured no tests")
    return counts


def _check_skips(skips: object, *, what: str) -> List[Dict[str, str]]:
    if not isinstance(skips, list):
        raise RuntimeError(f"{what} skips must be a list")
    clean: List[Dict[str, str]] = []
    for entry in skips:
        if not isinstance(entry, Mapping):
            raise RuntimeError(f"{what} has a bad skip entry")
        test_id = entry.get("id")
        kind = entry.get("kind")
        reason = entry.get("reason")
        if not isinstance(test_id, str) or not test_id.strip():
            raise RuntimeError(f"{what} has a skip without an id")
        if kind not in ("skip", "xfail"):
            raise RuntimeError(f"{what} has a skip with a bad kind")
        if not isinstance(reason, str) or not reason.strip():
            raise RuntimeError(f"{what} has a skip without a reason")
        clean.append(
            {"id": test_id.strip(), "kind": kind, "reason": reason.strip()}
        )
    clean.sort(key=lambda entry: (entry["id"], entry["kind"], entry["reason"]))
    return clean


def build_gate_receipt(
    *,
    gate: str,
    status: str,
    command: str,
    source_commit: str,
    build_id: str,
    environment: Mapping[str, Any],
    measured: Mapping[str, Any],
    skips: Sequence[Mapping[str, Any]],
    log_sha256: str = "",
    reason: str = "",
    started_at: object = None,
    ended_at: object = None,
) -> Dict[str, Any]:
    """Build a normalized gate receipt, failing closed on bad inputs.

    ``log_sha256`` (the hash of the immutable execution log) is required for
    ``pass`` and ``fail``; ``skip`` carries no log and requires ``reason``.
    """
    if gate not in KNOWN_GATES:
        raise RuntimeError(f"unknown release gate: {gate!r}")
    if status not in STATUSES:
        raise RuntimeError(f"gate {gate} has a bad status: {status!r}")
    if not isinstance(command, str) or not command.strip():
        raise RuntimeError(f"gate {gate} is missing its executed command")
    if not HEX40_RE.fullmatch(source_commit or ""):
        raise RuntimeError(f"gate {gate} has no 40-hex source commit")
    if not isinstance(build_id, str) or not build_id.strip():
        raise RuntimeError(f"gate {gate} is missing its build identity")
    counts = _check_measured(measured, what=f"gate {gate}")
    skip_list = _check_skips(list(skips), what=f"gate {gate}")
    if counts["skipped"] + counts["xfailed"] != len(skip_list):
        raise RuntimeError(f"gate {gate} skip list does not match its counts")
    if status == "skip":
        if not isinstance(reason, str) or not reason.strip():
            raise RuntimeError(f"gate {gate} is skipped without a reason")
        if log_sha256:
            raise RuntimeError(f"gate {gate} is skipped but carries a log hash")
    else:
        if reason:
            raise RuntimeError(f"gate {gate} has status {status} with a skip reason")
        if not HEX64_RE.fullmatch(log_sha256 or ""):
            raise RuntimeError(f"gate {gate} is missing its log hash")
    if counts["failed"] > 0 or counts["errors"] > 0:
        if status != "fail":
            raise RuntimeError(f"gate {gate} has failures but status {status!r}")
    receipt: Dict[str, Any] = {
        "schema": GATE_RECEIPT_SCHEMA,
        "gate": gate,
        "status": status,
        "command": command.strip(),
        "source_commit": source_commit,
        "build_id": build_id.strip(),
        "environment": sanitize_environment(environment, what=f"gate {gate}"),
        "measured": counts,
        "skips": skip_list,
        "log_sha256": log_sha256 or "",
        "reason": reason.strip() if isinstance(reason, str) else "",
        "started_at": normalize_utc(started_at or utc_now_s()),
        "ended_at": normalize_utc(ended_at or utc_now_s()),
    }
    if receipt["started_at"] > receipt["ended_at"]:
        raise RuntimeError(f"gate {gate} ends before it starts")
    _check_no_secrets(canonical_bytes(receipt).decode("utf-8"), what=f"gate {gate}")
    receipt["receipt_sha256"] = canonical_digest(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )
    return receipt


def verify_gate_receipt(receipt: Mapping[str, Any], *, what: str = "gate receipt") -> Dict[str, Any]:
    """Re-validate a stored receipt byte-for-byte semantics.

    Rejects unknown schemas and gates, empty required fields, inconsistent
    counts, digest mismatch (tampering), and secret-bearing content.
    Returns the normalized receipt on success.
    """
    if not isinstance(receipt, Mapping):
        raise RuntimeError(f"{what} must be an object")
    if receipt.get("schema") != GATE_RECEIPT_SCHEMA:
        raise RuntimeError(f"{what} has an unknown schema")
    stored = receipt.get("receipt_sha256")
    if not isinstance(stored, str) or not HEX64_RE.fullmatch(stored):
        raise RuntimeError(f"{what} is missing its receipt digest")
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if canonical_digest(body) != stored:
        raise RuntimeError(f"{what} digest mismatch: tampered or corrupted")
    rebuilt = build_gate_receipt(
        gate=receipt.get("gate", ""),
        status=receipt.get("status", ""),
        command=receipt.get("command", ""),
        source_commit=receipt.get("source_commit", ""),
        build_id=receipt.get("build_id", ""),
        environment=receipt.get("environment", {}),
        measured=receipt.get("measured", {}),
        skips=receipt.get("skips", []),
        log_sha256=receipt.get("log_sha256", ""),
        reason=receipt.get("reason", ""),
        started_at=receipt.get("started_at"),
        ended_at=receipt.get("ended_at"),
    )
    if canonical_digest({k: v for k, v in rebuilt.items() if k != "receipt_sha256"}) != stored:
        raise RuntimeError(f"{what} does not normalize to its digest")
    return rebuilt


def verify_release_evidence(evidence: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Verify the full gate set for a release. Fail closed, always.

    Every required gate must be present with status ``pass``. Optional gates
    may be ``pass`` or ``skip``; a failed gate of any kind, a skipped
    required gate, a missing required gate, or an unknown gate name all
    raise. Returns the verified receipts keyed by gate.
    """
    if not isinstance(evidence, Mapping):
        raise RuntimeError("release evidence must be an object")
    if evidence.get("schema") != TEST_EVIDENCE_SCHEMA:
        raise RuntimeError("release evidence has an unknown schema")
    gates = evidence.get("gates")
    if not isinstance(gates, Mapping) or not gates:
        raise RuntimeError("release evidence has no gates")
    for name in gates:
        if name not in KNOWN_GATES:
            raise RuntimeError(f"release evidence names an unknown gate: {name!r}")
    verified: Dict[str, Dict[str, Any]] = {}
    for name in REQUIRED_GATES:
        if name not in gates:
            raise RuntimeError(f"release evidence is missing required gate {name!r}")
        receipt = verify_gate_receipt(gates[name], what=f"gate {name}")
        if receipt["gate"] != name:
            raise RuntimeError("receipt gate name does not match its evidence slot")
        if receipt["status"] != "pass":
            raise RuntimeError(f"required gate {name!r} did not pass")
        verified[name] = receipt
    for name in OPTIONAL_GATES:
        if name not in gates:
            continue
        receipt = verify_gate_receipt(gates[name], what=f"gate {name}")
        if receipt["gate"] != name:
            raise RuntimeError("receipt gate name does not match its evidence slot")
        if receipt["status"] == "fail":
            raise RuntimeError(f"optional gate {name!r} failed")
        verified[name] = receipt
    commits = {receipt["source_commit"] for receipt in verified.values()}
    if len(commits) != 1:
        raise RuntimeError("release evidence spans more than one source commit")
    if len({receipt["build_id"] for receipt in verified.values()}) != 1:
        raise RuntimeError("release evidence spans more than one build identity")
    if "evidence_sha256" in evidence:
        digest = hashlib.sha256("".join(sorted(r["receipt_sha256"] for r in verified.values())).encode("ascii")).hexdigest()
        if evidence["evidence_sha256"] != digest:
            raise RuntimeError("release evidence digest mismatch")
    return verified


def build_test_evidence(
    receipts: Sequence[Mapping[str, Any]], *, measured_note: str = ""
) -> Dict[str, Any]:
    """Assemble the manifest ``test_evidence`` object from gate receipts."""
    if len({r.get("gate") for r in receipts}) != len(receipts):
        raise RuntimeError("duplicate gate receipts")
    gates = verify_release_evidence({"schema": TEST_EVIDENCE_SCHEMA, "gates": {r.get("gate"): r for r in receipts}})
    digests = sorted(receipt["receipt_sha256"] for receipt in gates.values())
    return {
        "schema": TEST_EVIDENCE_SCHEMA,
        "measured": True,
        "gates": {name: gates[name] for name in sorted(gates)},
        "evidence_sha256": hashlib.sha256("".join(digests).encode("ascii")).hexdigest(),
        "note": measured_note.strip() if isinstance(measured_note, str) else "",
    }


def parse_dpkg_status(text: str, *, what: str = "dpkg status") -> List[Dict[str, str]]:
    """Parse a dpkg status database into a deterministic package list.

    Keeps name, version, architecture, install state, and source-package
    provenance per package. Paragraphs without a ``Status: install ok
    installed`` line are skipped: only installed packages shape the image.
    """
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"{what} is empty")
    packages: List[Dict[str, str]] = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        fields: Dict[str, str] = {}
        current = ""
        for line in paragraph.splitlines():
            if line[:1] in (" ", "\t") and current:
                fields[current] += "\n" + line.strip()
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            current = key.strip()
            fields[current] = value.strip()
        name = fields.get("Package", "")
        version = fields.get("Version", "")
        arch = fields.get("Architecture", "")
        status = fields.get("Status", "")
        if not name:
            continue
        if status != "install ok installed":
            continue
        if not version or not arch:
            raise RuntimeError(f"{what} has an incomplete entry for {name!r}")
        packages.append(
            {
                "name": name,
                "version": version,
                "arch": arch,
                "status": status,
                "source": fields.get("Source", ""),
            }
        )
    if not packages:
        raise RuntimeError(f"{what} lists no installed packages")
    seen = set()
    for entry in packages:
        if entry["name"] in seen:
            raise RuntimeError(f"{what} lists {entry['name']!r} twice")
        seen.add(entry["name"])
    packages.sort(key=lambda entry: entry["name"])
    return packages


def build_package_inventory(
    *,
    packages: Sequence[Mapping[str, Any]],
    collected_from: str,
    apt_sources: Sequence[str],
    source_commit: str,
    generated_at: object = None,
) -> Dict[str, Any]:
    """Build a deterministic installed-package inventory.

    ``apt_sources`` records the image-level repository provenance (mirror
    URIs from the live-build bootstrap config): dpkg status itself carries
    no per-package repository origin, so provenance is the source-package
    name plus these configured sources, stated honestly as such.
    """
    if not isinstance(collected_from, str) or not collected_from.strip():
        raise RuntimeError("package inventory is missing its collection source")
    if not HEX40_RE.fullmatch(source_commit or ""):
        raise RuntimeError("package inventory has no 40-hex source commit")
    sources = sorted({s.strip() for s in apt_sources if isinstance(s, str) and s.strip()})
    if not sources:
        raise RuntimeError("package inventory is missing apt source provenance")
    clean: List[Dict[str, str]] = []
    for entry in packages:
        if not isinstance(entry, Mapping):
            raise RuntimeError("package inventory has a bad entry")
        name = entry.get("name")
        version = entry.get("version")
        arch = entry.get("arch")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("package inventory has an unnamed entry")
        if not isinstance(version, str) or not version.strip():
            raise RuntimeError(f"package inventory entry {name!r} has no version")
        if not isinstance(arch, str) or not arch.strip():
            raise RuntimeError(f"package inventory entry {name!r} has no architecture")
        source = entry.get("source", "")
        clean.append(
            {
                "name": name.strip(),
                "version": version.strip(),
                "arch": arch.strip(),
                "source": source.strip() if isinstance(source, str) else "",
            }
        )
    clean.sort(key=lambda entry: entry["name"])
    names = [entry["name"] for entry in clean]
    if len(set(names)) != len(names):
        raise RuntimeError("package inventory lists a package twice")
    if not clean:
        raise RuntimeError("package inventory is empty")
    inventory = {
        "schema": PACKAGE_INVENTORY_SCHEMA,
        "measured": True,
        "collected_from": collected_from.strip(),
        "apt_sources": sources,
        "source_commit": source_commit,
        "generated_at": normalize_utc(generated_at or utc_now_s()),
        "package_count": len(clean),
        "packages": clean,
    }
    _check_no_secrets(canonical_bytes(inventory).decode("utf-8"), what="package inventory")
    inventory["inventory_sha256"] = canonical_digest(
        {k: v for k, v in inventory.items() if k != "inventory_sha256"}
    )
    return inventory


def verify_package_inventory(
    inventory: Mapping[str, Any], *, what: str = "package inventory"
) -> Dict[str, Any]:
    """Re-validate a stored package inventory, including its digest."""
    if not isinstance(inventory, Mapping):
        raise RuntimeError(f"{what} must be an object")
    if inventory.get("schema") != PACKAGE_INVENTORY_SCHEMA:
        raise RuntimeError(f"{what} has an unknown schema")
    stored = inventory.get("inventory_sha256")
    if not isinstance(stored, str) or not HEX64_RE.fullmatch(stored):
        raise RuntimeError(f"{what} is missing its inventory digest")
    body = {k: v for k, v in inventory.items() if k != "inventory_sha256"}
    if canonical_digest(body) != stored:
        raise RuntimeError(f"{what} digest mismatch: tampered or corrupted")
    rebuilt = build_package_inventory(
        packages=inventory.get("packages", []),
        collected_from=inventory.get("collected_from", ""),
        apt_sources=inventory.get("apt_sources", []),
        source_commit=inventory.get("source_commit", ""),
        generated_at=inventory.get("generated_at"),
    )
    if rebuilt["package_count"] != inventory.get("package_count"):
        raise RuntimeError(f"{what} package count does not match its packages")
    if canonical_digest({k: v for k, v in rebuilt.items() if k != "inventory_sha256"}) != stored:
        raise RuntimeError(f"{what} does not normalize to its digest")
    return rebuilt


def _read_text_file(path: Path, *, what: str) -> str:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise RuntimeError(f"{what} cannot be read: {path}") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{what} is not UTF-8: {path}") from exc


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="verification-evidence")
    sub = parser.add_subparsers(dest="command", required=True)

    junit = sub.add_parser("parse-junit", help="build a gate receipt from JUnit XML")
    junit.add_argument("--gate", required=True)
    junit.add_argument("--status", required=True)
    junit.add_argument("--exec-command", required=True)
    junit.add_argument("--commit", required=True)
    junit.add_argument("--build-id", required=True)
    junit.add_argument("--xml", required=True)
    junit.add_argument("--log-sha256", default="")
    junit.add_argument("--reason", default="")
    junit.add_argument("--env", action="append", default=[], metavar="K=V")
    junit.add_argument("--started-at", default="")
    junit.add_argument("--ended-at", default="")
    junit.add_argument("--out", required=True)

    dpkg = sub.add_parser("parse-dpkg-status", help="build a package inventory")
    dpkg.add_argument("--status-file", required=True)
    dpkg.add_argument("--collected-from", required=True)
    dpkg.add_argument("--apt-source", action="append", default=[], metavar="URI")
    dpkg.add_argument("--commit", required=True)
    dpkg.add_argument("--generated-at", default="")
    dpkg.add_argument("--out", required=True)

    verify = sub.add_parser("verify-receipts", help="fail-closed check of receipt files")
    verify.add_argument("--receipt", action="append", default=[], metavar="PATH")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "parse-junit":
        env: Dict[str, Any] = {}
        for item in args.env:
            key, sep, value = item.partition("=")
            if not sep or not key.strip():
                raise RuntimeError(f"bad --env entry: {item!r}")
            env[key.strip()] = value.strip()
        measured = parse_junit_xml(_read_text_file(Path(args.xml), what="junit xml"))
        receipt = build_gate_receipt(
            gate=args.gate,
            status=args.status,
            command=args.exec_command,
            source_commit=args.commit,
            build_id=args.build_id,
            environment=env,
            measured={k: measured[k] for k in ("passed", "failed", "errors", "skipped", "xfailed", "deselected", "total")},
            skips=measured["skips"],
            log_sha256=args.log_sha256,
            reason=args.reason,
            started_at=args.started_at or None,
            ended_at=args.ended_at or None,
        )
        Path(args.out).write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.out} gate={receipt['gate']} status={receipt['status']}")
        return 0
    if args.command == "parse-dpkg-status":
        inventory = build_package_inventory(
            packages=parse_dpkg_status(
                _read_text_file(Path(args.status_file), what="dpkg status")
            ),
            collected_from=args.collected_from,
            apt_sources=args.apt_source,
            source_commit=args.commit,
            generated_at=args.generated_at or None,
        )
        Path(args.out).write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.out} packages={inventory['package_count']}")
        return 0
    receipts = []
    for path in args.receipt:
        receipts.append(json.loads(_read_text_file(Path(path), what="gate receipt")))
    verified = verify_release_evidence(
        {"schema": TEST_EVIDENCE_SCHEMA, "gates": {r.get("gate"): r for r in receipts}}
    )
    print(f"evidence ok: {', '.join(sorted(verified))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
