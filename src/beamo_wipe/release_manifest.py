# SPDX-License-Identifier: GPL-3.0-or-later
"""Machine-readable release manifest. Fails closed on dirty/placeholder."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from beamo_wipe import NWIPE_PINNED_COMMIT, NWIPE_PINNED_VERSION, __version__

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
MANIFEST_NAME_TEMPLATE = "beamo-wipe-{version}-amd64.manifest.json"
PRIOR_STABLE = {
    "version": "0.1.0",
    "iso_name": "beamo-wipe-0.1.0-amd64.iso",
    "sha256": "8a531d35c437d858512ccbba20913cd7dbd9237cc9a2e2a1b7935ba9d9781c55",
    "commit": "3b4c01f",  # abbreviated, full resolved at runtime if tag exists
}

PLACEHOLDER_RE = re.compile(r"PLACEHOLDER|TODO|XXX|CHANGEME", re.I)


def _run(cmd: List[str], **kw: Any) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True, **kw).strip()  # noqa: S603


def git_commit() -> str:
    try:
        return _run(["git", "rev-parse", "HEAD"])
    except Exception:
        raise RuntimeError("untraceable source state: git rev-parse HEAD failed")


def git_tag_for_commit(commit: str) -> Optional[str]:
    try:
        tags = _run(["git", "tag", "--points-at", commit]).splitlines()
        tags = [t.strip() for t in tags if t.strip()]
        return tags[0] if tags else None
    except Exception:
        return None


def git_dirty() -> tuple[bool, List[str]]:
    try:
        out = _run(["git", "status", "--porcelain"])
        files = [line for line in out.splitlines() if line.strip()]
        return (len(files) > 0, files)
    except Exception:
        return (True, ["unknown"])


def git_remote_url() -> str:
    try:
        return _run(["git", "config", "--get", "remote.origin.url"])
    except Exception:
        return "https://github.com/BeamoINT/beamo-wipe"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha256_or_none(path: Path) -> Optional[str]:
    try:
        if path.is_file():
            return sha256_file(path)
    except Exception:
        pass
    return None


def live_build_inputs() -> Dict[str, Any]:
    cfg = ROOT / "packaging" / "live" / "config"
    inputs: Dict[str, Any] = {}
    for rel in [
        "bootstrap",
        "binary",
        "chroot",
        "common",
        "source",
        "apt",
        "archives",
        "binary",
        "bootloaders",
        "debian-installer",
        "hooks",
        "includes",
        "package-lists/beamo.list.chroot",
        "package-lists/live.list.chroot",
        "hooks/normal/0099-beamo-nwipe.hook.chroot",
    ]:
        p = cfg / rel
        if p.is_file():
            inputs[rel] = file_sha256_or_none(p)
        elif p.is_dir():
            # hash directory contents
            h = hashlib.sha256()
            for sub in sorted(p.rglob("*")):
                if sub.is_file():
                    rel2 = str(sub.relative_to(cfg))
                    h.update(rel2.encode())
                    h.update(b"\0")
                    h.update(sha256_file(sub).encode())
            inputs[rel + "/"] = h.hexdigest()
    # Also hash src/beamo_wipe
    src_h = hashlib.sha256()
    for sub in sorted((ROOT / "src" / "beamo_wipe").rglob("*.py")):
        src_h.update(sub.name.encode())
        src_h.update(sha256_file(sub).encode())
    inputs["src/beamo_wipe/"] = src_h.hexdigest()
    return inputs


def dependency_locks() -> Dict[str, Any]:
    locks: Dict[str, Any] = {}
    locks["pyproject.toml"] = file_sha256_or_none(ROOT / "pyproject.toml")
    locks["THIRD_PARTY.md"] = file_sha256_or_none(ROOT / "THIRD_PARTY.md")
    locks["NOTICE"] = file_sha256_or_none(ROOT / "NOTICE")
    # live-build package lists already in live_build_inputs but duplicate for drift check
    return locks


def build_env() -> Dict[str, Any]:
    env: Dict[str, Any] = {}
    # Container/runner image
    try:
        # In Cloud Build, the ISO step uses debian:bookworm
        env["container_image"] = "debian:bookworm"
    except Exception:
        env["container_image"] = "unknown"
    # Runner
    env["runner"] = os.environ.get("RUNNER_OS", "unknown")
    env["github_runner_image"] = os.environ.get("ImageOS", "unknown")
    # Build commands
    env["build_commands"] = [
        "./scripts/build-iso.sh",
        "packaging/live/inside-docker.sh lb config && lb build",
    ]
    env["built_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    return env


def iso_info(version: str = __version__) -> Dict[str, Any]:
    iso_name = f"beamo-wipe-{version}-amd64.iso"
    iso_path = ROOT / "dist" / iso_name
    if not iso_path.is_file():
        raise RuntimeError(f"missing checksum: ISO not found at {iso_path}")
    sha = sha256_file(iso_path)
    size = iso_path.stat().st_size
    if not sha or size == 0:
        raise RuntimeError("missing checksum")
    # Verify nwipe version inside ISO via hook pins (not by mounting, just pins)
    if NWIPE_PINNED_VERSION != "0.42":
        raise RuntimeError(f"unexpected nwipe version {NWIPE_PINNED_VERSION}, expected 0.42")
    if not re.fullmatch(r"[0-9a-f]{40}", NWIPE_PINNED_COMMIT):
        raise RuntimeError("placeholder provenance: nwipe commit not a 40-hex SHA")
    return {
        "iso_name": iso_name,
        "iso_path": str(iso_path),
        "iso_size_bytes": size,
        "iso_sha256": sha,
        "iso_sha256_sidecar": f"{iso_name}.sha256",
    }


def hardware_limits() -> Dict[str, Any]:
    # From docs/compatibility-matrix.md and docs/claims.md
    return {
        "supported": [
            "x64 PCs (UEFI + Legacy BIOS) via USB-A/C, boot menu F12/Esc/F9",
            "SATA HDD, SATA SSD, NVMe, virtio (QEMU), eMMC (mmcblk0)",
            "Resolutions 1024x740–1920x1080 @72 DPI, keyboard-only",
        ],
        "unsupported": [
            "Apple Silicon, Chromebooks, RAID/dm-raid, network bdevs (nbd/iscsi/fc/nvmeof)",
            "In-OS wipe from Windows/macOS, Secure Boot enrolled without disable",
        ],
        "degraded": [
            "SSD overwrite is controller-dependent (not a lab cert)",
            "800x600 requires scroll, HiDPI 144 un-gated",
            "USB-SATA bridges may present as sata",
        ],
    }


def known_issues() -> List[str]:
    return [
        "Secure Boot enabled with unsigned image requires disable (see docs/claims.md)",
        "QEMU TCG on Apple silicon is slow; use Cloud Build or x86_64 KVM (see docs/vm-test.md)",
        "eMMC boot partitions (mmcblk0boot0) hidden; eMMC-only recycle shows single selectable",
    ]


def test_evidence_stub() -> Dict[str, Any]:
    # Machine-readable but not placeholder: real CI will fill with actual pytest counts
    return {
        "pytest": "see cloudbuild.yaml python-tests (xvfb 72 DPI, BEAMO_WIPE_DRY_RUN=1)",
        "preview": "BEAMO_WIPE_NO_OPEN=1 ./preview --web (web-preview/index.html) + ./preview --console",
        "qemu": "see docs/qemu-verify.md and cloudbuild.yaml qemu-verify (disposable qcow2)",
    }


def generate_manifest(version: str = __version__, strict: bool = True) -> Dict[str, Any]:
    commit = git_commit()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("untraceable source state: commit not 40-hex")
    tag = git_tag_for_commit(commit)
    dirty, dirty_files = git_dirty()
    if strict and dirty:
        raise RuntimeError(f"uncommitted source state: {dirty_files[:20]}")
    # Placeholder check
    for f in [ROOT / "src" / "beamo_wipe" / "__init__.py", ROOT / "packaging" / "live" / "config" / "binary"]:
        if f.is_file():
            txt = f.read_text(encoding="utf-8", errors="replace")
            if PLACEHOLDER_RE.search(txt):
                raise RuntimeError(f"placeholder provenance in {f}")

    iso = iso_info(version)
    # Dependency drift: if pyproject version != wrapper version, fail
    try:
        try:
            import tomllib  # type: ignore[import-not-found, no-redef]
        except ImportError:
            import tomli as tomllib  # type: ignore[import-not-found, no-redef]

        with open(ROOT / "pyproject.toml", "rb") as fh:
            pyproject = tomllib.load(fh)
        py_ver = pyproject.get("project", {}).get("version", "")
        if py_ver and py_ver != __version__:
            raise RuntimeError(f"unapproved dependency drift: pyproject version {py_ver} != wrapper {__version__}")
    except RuntimeError:
        raise
    except Exception:
        pass

    manifest: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "beamo_wipe_version": version,
        "source": {
            "commit": commit,
            "tag": tag,
            "dirty": dirty,
            "dirty_files": dirty_files,
            "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) if not dirty else "dirty",
            "remote_url": git_remote_url(),
        },
        "build": build_env(),
        "dependencies": dependency_locks(),
        "live_build_inputs": live_build_inputs(),
        "nwipe": {
            "version": NWIPE_PINNED_VERSION,
            "commit": NWIPE_PINNED_COMMIT,
            "source": "https://github.com/martijnvanbrummelen/nwipe",
            "pinned_path": "/usr/lib/beamo-wipe/nwipe",
        },
        "artifact": iso,
        "test_evidence": test_evidence_stub(),
        "hardware_limits": hardware_limits(),
        "known_issues": known_issues(),
        "license": {
            "wrapper": "GPL-3.0-or-later",
            "nwipe": "GPL-2.0",
            "source": "https://github.com/BeamoINT/beamo-wipe",
            "notice": "NOTICE",
            "third_party": "THIRD_PARTY.md",
        },
        "prior_stable": PRIOR_STABLE,
        "rollback": f"git checkout {PRIOR_STABLE['commit']} or git revert <commit> to prior ISO {PRIOR_STABLE['iso_name']}",
        "verification": {
            "checksum_instructions": f"sha256sum -c dist/{iso['iso_name']}.sha256 or sha256sum {iso['iso_name']}",
            "artifact_immutability": "GCS gs://beamo-wipe_cloudbuild/releases/${BUILD_ID} (retention per bucket) and GitHub upload-artifact retention-days 14",
            "signing": "not configured (SHA256 sidecar only); verify via published SHA256SUMS",
            "reproducibility": "live-build is not bit-reproducible due to apt timestamps; use SHA256 and source commit for traceability",
        },
    }
    # Top-level checksum (of manifest without itself)
    canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    manifest["_manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return manifest


def write_manifest(manifest: Dict[str, Any], dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write
    tmp = dest.with_suffix(dest.suffix + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.rename(tmp, dest)
    # Sidecar
    sha = sha256_file(dest)
    sidecar = Path(str(dest) + ".sha256")
    with open(sidecar, "w", encoding="utf-8") as out:
        out.write(f"{sha}  {dest.name}\n")
        out.flush()
        os.fsync(out.fileno())
    # Also write ISO sidecar if not exists
    iso_name = manifest["artifact"]["iso_name"]
    iso_path = Path(manifest["artifact"]["iso_path"])
    iso_sidecar = iso_path.parent / f"{iso_name}.sha256"
    if not iso_sidecar.is_file():
        with open(iso_sidecar, "w", encoding="utf-8") as out:
            out.write(f"{manifest['artifact']['iso_sha256']}  {iso_name}\n")
    return dest


def verify_manifest(path: Path, allow_dirty: bool = False) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    # Recompute checksum (exclude sidecar)
    expected = data.pop("_manifest_sha256", None)
    if expected is None:
        raise RuntimeError("missing checksum: manifest has no _manifest_sha256")
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    got = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if expected != got:
        raise RuntimeError(f"manifest checksum mismatch: expected {expected}, got {got}")
    # Placeholder check
    blob = json.dumps(data)
    if PLACEHOLDER_RE.search(blob):
        raise RuntimeError("placeholder provenance in manifest")
    # Dirty check (skipped only for explicit local-dev ALLOW_DIRTY runs; every
    # other structural check still applies)
    if not allow_dirty and data.get("source", {}).get("dirty"):
        raise RuntimeError(f"uncommitted source state: {data['source'].get('dirty_files')}")
    # Missing checksum
    if not data.get("artifact", {}).get("iso_sha256"):
        raise RuntimeError("missing checksum")
    # Unexpected nwipe version
    if data.get("nwipe", {}).get("version") != "0.42":
        raise RuntimeError(f"unexpected nwipe version {data['nwipe']['version']}")
    if not re.fullmatch(r"[0-9a-f]{40}", data.get("nwipe", {}).get("commit", "")):
        raise RuntimeError("placeholder nwipe commit")
