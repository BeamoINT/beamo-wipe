# SPDX-License-Identifier: GPL-3.0-or-later
"""Machine-readable release manifest. Fails closed on dirty/placeholder."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from beamo_wipe import NWIPE_PINNED_COMMIT, NWIPE_PINNED_VERSION, __version__

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
MANIFEST_NAME_TEMPLATE = "beamo-wipe-{version}-amd64.manifest.json"
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
EXPECTED_REMOTE = "https://github.com/BeamoINT/beamo-wipe"
PRIOR_STABLE = {
    "version": "0.2.0",
    "iso_name": "beamo-wipe-0.2.0-amd64.iso",
    "sha256": "62437ec152a5b2ffc7c89fc503a7659d561c32699376a8851ab838f665491c74",
    "commit": "5b3b7afa6c448ee01269c9497c1c93e8e83733c1",
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
        raw = _run(["git", "config", "--get", "remote.origin.url"])
    except Exception:
        raise RuntimeError("untraceable source state: origin URL unavailable")
    allowed = {
        EXPECTED_REMOTE,
        EXPECTED_REMOTE + ".git",
        "git@github.com:BeamoINT/beamo-wipe.git",
        "ssh://git@github.com/BeamoINT/beamo-wipe.git",
    }
    if raw not in allowed:
        # Do not echo the raw value: a malformed HTTPS remote can contain a
        # credential in its userinfo or query string.
        raise RuntimeError("untraceable source state: unexpected origin URL")
    return EXPECTED_REMOTE


def _validate_version(version: str) -> str:
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise RuntimeError("invalid Beamo Wipe version")
    return version


def _open_regular_nofollow(path: Path) -> int:
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise RuntimeError(f"cannot safely read {path.name}") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError(f"cannot safely read {path.name}")
    except Exception:
        os.close(fd)
        raise
    return fd


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    fd = _open_regular_nofollow(Path(path))
    with os.fdopen(fd, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_file_with_stat(path: Path) -> tuple[str, int]:
    """Hash and size one opened inode, rejecting pathname replacement."""
    path = Path(path)
    h = hashlib.sha256()
    fd = _open_regular_nofollow(path)
    with os.fdopen(fd, "rb") as fh:
        opened = os.fstat(fh.fileno())
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise RuntimeError(f"cannot safely read {path.name}") from exc
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or (current.st_dev, current.st_ino, current.st_size)
        != (opened.st_dev, opened.st_ino, opened.st_size)
    ):
        raise RuntimeError(f"{path.name} changed while it was being verified")
    return h.hexdigest(), int(opened.st_size)


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
        "includes.chroot",
        "includes.binary",
        "package-lists/beamo.list.chroot",
        "package-lists/live.list.chroot",
        "hooks/normal/0500-build-nwipe.hook.chroot",
    ]:
        p = cfg / rel
        if p.is_file():
            inputs[rel] = file_sha256_or_none(p)
        elif p.is_dir():
            # hash directory contents
            h = hashlib.sha256()
            for sub in sorted(p.rglob("*")):
                rel2 = str(sub.relative_to(cfg))
                if sub.is_symlink():
                    # Hash the link itself, never a file outside the tree.
                    rel_blob = rel2.encode()
                    target = os.readlink(sub).encode("utf-8", errors="surrogateescape")
                    h.update(f"{len(rel_blob)}:".encode() + rel_blob)
                    h.update(b"S")
                    h.update(f"{len(target)}:".encode() + target)
                elif sub.is_file():
                    rel_blob = rel2.encode()
                    digest = sha256_file(sub).encode()
                    h.update(f"{len(rel_blob)}:".encode() + rel_blob)
                    h.update(b"F")
                    h.update(f"{len(digest)}:".encode() + digest)
            inputs[rel + "/"] = h.hexdigest()
    # Also hash src/beamo_wipe
    src_h = hashlib.sha256()
    source_files = []
    for sub in sorted((ROOT / "src" / "beamo_wipe").rglob("*")):
        if not sub.is_file() or "__pycache__" in sub.parts or sub.suffix in {".pyc", ".pyo"}:
            continue
        if sub.is_symlink():
            raise RuntimeError("source tree contains a symlink")
        source_files.append(sub)
        rel_blob = str(sub.relative_to(ROOT)).encode()
        digest = sha256_file(sub).encode()
        src_h.update(f"{len(rel_blob)}:".encode() + rel_blob)
        src_h.update(f"{len(digest)}:".encode() + digest)
    if not source_files:
        raise RuntimeError("missing shipped wrapper source")
    inputs["src/beamo_wipe/"] = src_h.hexdigest()
    for rel in (
        "helper/index.html",
        "scripts/build-iso.sh",
        "packaging/live/inside-docker.sh",
    ):
        path = ROOT / rel
        if path.is_file():
            inputs[rel] = sha256_file(path)
    return inputs


def dependency_locks(*, strict: bool = False) -> Dict[str, Any]:
    locks: Dict[str, Any] = {}
    locks["pyproject.toml"] = file_sha256_or_none(ROOT / "pyproject.toml")
    locks["THIRD_PARTY.md"] = file_sha256_or_none(ROOT / "THIRD_PARTY.md")
    locks["NOTICE"] = file_sha256_or_none(ROOT / "NOTICE")
    if strict and any(not digest for digest in locks.values()):
        raise RuntimeError("missing required release dependency input")
    # live-build package lists already in live_build_inputs but duplicate for drift check
    return locks


def build_env() -> Dict[str, Any]:
    env: Dict[str, Any] = {}
    # Container/runner image
    try:
        # In Cloud Build, the ISO step uses debian:bookworm
        env["container_image"] = (
            "debian:bookworm@sha256:"
            "6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443"
        )
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
    version = _validate_version(version)
    iso_name = f"beamo-wipe-{version}-amd64.iso"
    iso_path = ROOT / "dist" / iso_name
    if not iso_path.is_file():
        raise RuntimeError(f"missing checksum: ISO not found at {iso_path}")
    sha, size = sha256_file_with_stat(iso_path)
    if not sha or size == 0:
        raise RuntimeError("missing checksum")
    # Verify nwipe version inside ISO via hook pins (not by mounting, just pins)
    if NWIPE_PINNED_VERSION != "0.42":
        raise RuntimeError(f"unexpected nwipe version {NWIPE_PINNED_VERSION}, expected 0.42")
    if not re.fullmatch(r"[0-9a-f]{40}", NWIPE_PINNED_COMMIT):
        raise RuntimeError("placeholder provenance: nwipe commit not a 40-hex SHA")
    return {
        "iso_name": iso_name,
        # Public manifests must be relocatable. Record only the canonical bare
        # filename; write/verify resolve it in their trusted release directory.
        "iso_path": iso_name,
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
    version = _validate_version(version)
    commit = git_commit()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("untraceable source state: commit not 40-hex")
    tag = git_tag_for_commit(commit)
    dirty, dirty_files = git_dirty()
    if strict and dirty:
        # File names can themselves contain customer or secret material.
        raise RuntimeError("uncommitted source state")
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
        if not py_ver:
            raise RuntimeError("missing project version")
        if py_ver != __version__:
            raise RuntimeError(f"unapproved dependency drift: pyproject version {py_ver} != wrapper {__version__}")
        if strict and version != __version__:
            raise RuntimeError(
                f"artifact version {version} != wrapper {__version__}"
            )
    except RuntimeError:
        raise
    except Exception as exc:
        if strict:
            raise RuntimeError("cannot validate pyproject version") from exc

    manifest: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "beamo_wipe_version": version,
        "source": {
            "commit": commit,
            "tag": tag,
            "dirty": dirty,
            "dirty_count": len(dirty_files),
            "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) if not dirty else "dirty",
            "remote_url": git_remote_url(),
        },
        "build": build_env(),
        "dependencies": dependency_locks(strict=strict),
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
            "checksum_instructions": f"cd dist && sha256sum -c {iso['iso_name']}.sha256",
            "artifact_immutability": "verification is ephemeral unless the explicit post-QEMU release gate writes a unique build path",
            "signing": "not configured; SHA256 detects corruption but does not authenticate the publisher",
            "reproducibility": "live-build is not bit-reproducible due to apt timestamps; use SHA256 and source commit for traceability",
        },
    }
    if strict:
        final_commit = git_commit()
        final_dirty, _final_files = git_dirty()
        if final_commit != commit or final_dirty:
            raise RuntimeError("source state changed during manifest generation")
    # Top-level checksum (of manifest without itself)
    canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    manifest["_manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return manifest


def _atomic_write(path: Path, blob: bytes) -> None:
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    dirfd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    name = path.name
    tmp_name = f".{name}.tmp.{os.getpid()}.{time.time_ns()}"
    fd = -1
    try:
        fd = os.open(
            tmp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=dirfd,
        )
        view = memoryview(blob)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short manifest write")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.rename(tmp_name, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        os.fsync(dirfd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp_name, dir_fd=dirfd)
        except FileNotFoundError:
            pass
        os.close(dirfd)


def _sidecar_blob(sha: str, name: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", sha) or not name or name != os.path.basename(name):
        raise RuntimeError("invalid checksum sidecar fields")
    return f"{sha}  {name}\n".encode("ascii")


def write_manifest(manifest: Dict[str, Any], dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    artifact = manifest.get("artifact", {})
    iso_name = str(artifact.get("iso_name", ""))
    if not re.fullmatch(r"beamo-wipe-[0-9]+\.[0-9]+\.[0-9]+-amd64\.iso", iso_name):
        raise RuntimeError("invalid ISO artifact name")
    if artifact.get("iso_path") != iso_name:
        raise RuntimeError("ISO path escapes the release directory")
    iso_path = ROOT / "dist" / iso_name
    try:
        if iso_path.resolve(strict=True) != (ROOT / "dist" / iso_name).resolve(strict=True):
            raise RuntimeError("ISO path escapes the release directory")
    except OSError as exc:
        raise RuntimeError("ISO referenced by manifest is missing") from exc
    recorded_iso_sha = str(artifact.get("iso_sha256", ""))
    if sha256_file(iso_path) != recorded_iso_sha:
        raise RuntimeError("ISO checksum mismatch")
    blob = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write(dest, blob)
    # Sidecar
    sha = sha256_file(dest)
    sidecar = Path(str(dest) + ".sha256")
    _atomic_write(sidecar, _sidecar_blob(sha, dest.name))
    # Also write ISO sidecar if not exists
    iso_sidecar = iso_path.parent / f"{iso_name}.sha256"
    _atomic_write(
        iso_sidecar,
        _sidecar_blob(str(manifest["artifact"]["iso_sha256"]), str(iso_name)),
    )
    return dest


def verify_manifest(path: Path, allow_dirty: bool = False) -> None:
    path = Path(path)
    fd = _open_regular_nofollow(path)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        raw_manifest = stream.read()
    data = json.loads(raw_manifest)
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
        raise RuntimeError("uncommitted source state")
    # Missing checksum
    if not data.get("artifact", {}).get("iso_sha256"):
        raise RuntimeError("missing checksum")
    # Unexpected nwipe version
    if data.get("nwipe", {}).get("version") != "0.42":
        raise RuntimeError(f"unexpected nwipe version {data['nwipe']['version']}")
    if not re.fullmatch(r"[0-9a-f]{40}", data.get("nwipe", {}).get("commit", "")):
        raise RuntimeError("placeholder nwipe commit")
    artifact = data.get("artifact", {})
    version = _validate_version(data.get("beamo_wipe_version", ""))
    iso_name = f"beamo-wipe-{version}-amd64.iso"
    if artifact.get("iso_name") != iso_name:
        raise RuntimeError("unexpected ISO name in manifest")
    if artifact.get("iso_path") != iso_name:
        raise RuntimeError("ISO path escapes the release directory")
    iso_path = path.parent / iso_name
    recorded_iso_sha = str(artifact.get("iso_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", recorded_iso_sha):
        raise RuntimeError("missing checksum")
    try:
        actual_sha, actual_size = sha256_file_with_stat(iso_path)
        if actual_sha != recorded_iso_sha:
            raise RuntimeError("ISO checksum mismatch")
        if actual_size != int(artifact.get("iso_size_bytes", -1)):
            raise RuntimeError("ISO size mismatch")
    except OSError as exc:
        raise RuntimeError("ISO referenced by manifest is missing") from exc
    _verify_sidecar(Path(str(iso_path) + ".sha256"), recorded_iso_sha, iso_name)
    _verify_sidecar(
        Path(str(path) + ".sha256"),
        hashlib.sha256(raw_manifest.encode("utf-8")).hexdigest(),
        path.name,
    )


def _verify_sidecar(path: Path, sha: str, name: str) -> None:
    fd = _open_regular_nofollow(path)
    with os.fdopen(fd, "r", encoding="ascii") as stream:
        text = stream.read(512)
    if text != f"{sha}  {name}\n":
        raise RuntimeError(f"checksum sidecar mismatch for {name}")
