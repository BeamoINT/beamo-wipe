# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect execution receipts on CI and finalize provenance after QEMU."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys

from beamo_wipe import __version__
from beamo_wipe.verification_evidence import (
    KNOWN_GATES, build_gate_receipt, build_package_inventory,
    parse_dpkg_status, parse_junit_xml, utc_now_s, verify_gate_receipt,
)


def _write(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def run_gate(gate, command, *, root, evidence_dir, build_id):
    """Run once, retaining the exit status and exact combined output."""
    if gate not in KNOWN_GATES:
        raise RuntimeError("unknown CI gate")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = evidence_dir / f"{gate}.receipt.json"
    log_path = evidence_dir / f"{gate}.log"
    junit = evidence_dir / f"{gate}.xml"
    if any(p.exists() for p in (receipt_path, log_path, junit)):
        raise RuntimeError(f"stale evidence for {gate}; use a fresh build workspace")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env = dict(os.environ, BEAMO_GATE_CHILD="1", BEAMO_GATE_JUNIT=str(junit))
    started = utc_now_s()
    with log_path.open("xb") as log:
        with subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) as proc:
            assert proc.stdout is not None
            for chunk in iter(lambda: proc.stdout.read1(65536), b""):
                log.write(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            code = proc.wait()
    ended = utc_now_s()
    measured = dict(passed=int(code == 0), failed=int(code != 0), errors=0,
                    skipped=0, xfailed=0, deselected=0, total=1)
    skips = []
    status = "pass" if code == 0 else "fail"
    reason = ""
    if gate in ("iso", "qemu") and env.get(f"SKIP_{gate.upper()}") == "true":
        if code == 0:
            status = "skip"
            reason = f"SKIP_{gate.upper()}=true"
            measured.update(passed=0, skipped=1)
            skips = [dict(id=gate, kind="skip", reason=reason)]
    if gate == "tests":
        if not junit.is_file():
            raise RuntimeError("test gate did not produce its JUnit execution report")
        parsed = parse_junit_xml(junit.read_text())
        skips = parsed.pop("skips")
        measured = parsed
    receipt = build_gate_receipt(
        gate=gate, status=status, command=shlex.join(command),
        source_commit=commit, build_id=build_id,
        environment=dict(platform=sys.platform, arch=platform.machine(),
                         python=platform.python_version(), runner="cloudbuild" if build_id != "local" else "local"),
        measured=measured, skips=skips,
        log_sha256="" if status == "skip" else hashlib.sha256(log_path.read_bytes()).hexdigest(),
        reason=reason, started_at=started, ended_at=ended,
    )
    _write(receipt_path, receipt)
    return receipt


def collect_inventory(image_root: Path, dest: Path, commit: str) -> None:
    """Read package status and configured repositories from the mounted image."""
    apt = image_root / "etc/apt"
    sources = set()
    for path in [apt / "sources.list", *(apt / "sources.list.d").glob("*.list"),
                 *(apt / "sources.list.d").glob("*.sources")]:
        if path.is_file():
            for line in path.read_text().splitlines():
                if not line.lstrip().startswith("#"):
                    sources.update(re.findall(r"https?://[^\s]+", line))
    inventory = build_package_inventory(
        packages=parse_dpkg_status((image_root / "var/lib/dpkg/status").read_text()),
        collected_from="squashfs var/lib/dpkg/status", apt_sources=sorted(sources),
        source_commit=commit,
    )
    _write(dest, inventory)


def load_receipts(directory: Path) -> list[dict]:
    """Bind every receipt to the retained execution log before finalization."""
    receipts = []
    for path in sorted(directory.glob("*.receipt.json")):
        receipt = verify_gate_receipt(json.loads(path.read_text()))
        gate = receipt["gate"]
        if path.name != f"{gate}.receipt.json":
            raise RuntimeError("receipt filename does not match its gate")
        if receipt["status"] != "skip":
            from beamo_wipe.release_manifest import sha256_file
            if sha256_file(directory / f"{gate}.log") != receipt["log_sha256"]:
                raise RuntimeError(f"execution log digest mismatch for {gate}")
        receipts.append(receipt)
    return receipts


def finalize(root: Path) -> None:
    from beamo_wipe import release_manifest as rm

    dist = root / "dist"
    dest = dist / f"beamo-wipe-{__version__}-amd64.manifest.json"
    rm.verify_build_manifest(dest)
    previous = json.loads(dest.read_text())
    if (previous["source"]["commit"] != rm.git_commit()
            or previous["build"]["release_build_id"] != os.environ.get("BUILD_ID", "local")):
        raise RuntimeError("built artifact belongs to another source or build")
    receipts = load_receipts(dist / "evidence")
    inventory = json.loads((dist / "evidence/packages.json").read_text())
    manifest = rm.generate_manifest(gate_receipts=receipts, package_inventory=inventory)
    if manifest["artifact"] != previous["artifact"]:
        raise RuntimeError("artifact changed during verification")
    rm.write_manifest(manifest, dest)
    rm.verify_manifest(dest)
    iso = dist / manifest["artifact"]["iso_name"]
    (dist / "SHA256SUMS").write_text(
        f"{rm.sha256_file(iso)}  {iso.name}\n{rm.sha256_file(dest)}  {dest.name}\n"
    )
    print("Final verified evidence: " + json.dumps({
        "source_commit": manifest["source"]["commit"],
        "build_id": manifest["build"]["release_build_id"],
        "iso_sha256": rm.sha256_file(iso),
        "manifest_sha256": rm.sha256_file(dest),
        "gate_count": len(receipts),
        "packages_sha256": rm.sha256_file(dist / "evidence/packages.json"),
    }, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=sorted(KNOWN_GATES) + ["inventory"])
    parser.add_argument("--image-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    evidence = root / "dist/evidence"
    if args.gate == "inventory":
        if args.image_root is None:
            parser.error("inventory requires --image-root")
        from beamo_wipe.release_manifest import git_commit
        evidence.mkdir(parents=True, exist_ok=True)
        collect_inventory(args.image_root, evidence / "packages.json", git_commit())
        return 0
    receipt = run_gate(args.gate, ["bash", "scripts/ci-hosted.sh", args.gate],
                       root=root, evidence_dir=evidence, build_id=os.environ.get("BUILD_ID", "local"))
    if receipt["status"] == "fail":
        return 1
    if args.gate == "qemu" and receipt["status"] == "pass":
        finalize(root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"CI evidence failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
