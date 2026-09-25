# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect execution receipts on CI and finalize provenance after QEMU."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import stat
import subprocess
import sys

from beamo_wipe import __version__
from beamo_wipe.verification_evidence import (
    KNOWN_GATES, build_gate_receipt, build_package_inventory,
    _hide_host_paths, parse_dpkg_status, parse_junit_xml, utc_now_s,
    verify_gate_receipt,
)


def _write(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _unique_json_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("duplicate CI evidence field")
        result[key] = value
    return result


def _require_evidence_directory(directory: Path, *, create: bool = False) -> None:
    """Reject a linked path component before writing or trusting CI receipts."""
    path = Path(directory).absolute()
    if ".." in path.parts:
        raise RuntimeError("unsafe CI evidence directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        parent_fd = os.open("/", flags)
        try:
            for component in path.parts[1:]:
                if create:
                    try:
                        os.mkdir(component, 0o700, dir_fd=parent_fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(component, flags, dir_fd=parent_fd)
                old_fd = parent_fd
                parent_fd = next_fd
                os.close(old_fd)
        finally:
            os.close(parent_fd)
    except OSError as exc:
        raise RuntimeError("unsafe CI evidence directory") from exc


def qemu_evidence_hashes(directory: Path) -> dict[str, str]:
    """Hash copied QEMU evidence files, excluding the private staging path."""
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise RuntimeError("QEMU evidence cannot be read") from exc
    try:
        opened_directory = os.fstat(directory_fd)
        files = {}
        names = sorted(os.listdir(directory_fd))
        identities = {}
        for name in names:
            if name == "PATH":
                continue
            child_fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            with os.fdopen(child_fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode):
                    raise RuntimeError("QEMU evidence contains a non-regular file")
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
                    size += len(chunk)
                first_digest = digest.hexdigest()
                # A same-size in-place rewrite can retain the original mtime
                # and appear to retain ctime on coarse-clock filesystems.
                # Re-read the opened inode so those metadata coincidences
                # cannot publish a digest of bytes no longer in the file.
                stream.seek(0)
                repeat = hashlib.sha256()
                repeat_size = 0
                for chunk in iter(lambda: stream.read(65536), b""):
                    repeat.update(chunk)
                    repeat_size += len(chunk)
                if repeat_size != size or repeat.hexdigest() != first_digest:
                    raise RuntimeError("QEMU evidence changed while hashing")
                after = os.fstat(stream.fileno())
                if (
                    (opened.st_dev, opened.st_ino, opened.st_size,
                     opened.st_mtime_ns, opened.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns)
                    or size != opened.st_size
                ):
                    raise RuntimeError("QEMU evidence changed while hashing")
                files[name] = first_digest
                identities[name] = (
                    opened.st_dev, opened.st_ino, opened.st_size,
                    opened.st_mtime_ns, opened.st_ctime_ns,
                )
        if sorted(os.listdir(directory_fd)) != names:
            raise RuntimeError("QEMU evidence files changed while hashing")
        for name, identity in identities.items():
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino, current.st_size,
                    current.st_mtime_ns, current.st_ctime_ns) != identity
            ):
                raise RuntimeError("QEMU evidence file changed while hashing")
        named_directory = os.stat(directory, follow_symlinks=False)
        if (
            not stat.S_ISDIR(named_directory.st_mode)
            or (named_directory.st_dev, named_directory.st_ino,
                named_directory.st_mtime_ns, named_directory.st_ctime_ns)
            != (opened_directory.st_dev, opened_directory.st_ino,
                opened_directory.st_mtime_ns, opened_directory.st_ctime_ns)
        ):
            raise RuntimeError("QEMU evidence directory changed while hashing")
    except OSError as exc:
        raise RuntimeError("QEMU evidence cannot be read") from exc
    finally:
        os.close(directory_fd)
    if not files:
        raise RuntimeError("QEMU evidence is empty")
    return files


def qemu_evidence_digest(files: dict[str, str]) -> str:
    """Bind both evidence filenames and contents in one stable digest."""
    blob = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def run_gate(gate, command, *, root, evidence_dir, build_id):
    """Run once, retaining the exit status and exact combined output."""
    if gate not in KNOWN_GATES:
        raise RuntimeError("unknown CI gate")
    _require_evidence_directory(evidence_dir, create=True)
    receipt_path = evidence_dir / f"{gate}.receipt.json"
    log_path = evidence_dir / f"{gate}.log"
    junit = evidence_dir / f"{gate}.xml"
    # exists() misses a dangling JUnit symlink, which the test runner could
    # follow into a file outside the evidence directory when it creates XML.
    if any(os.path.lexists(p) for p in (receipt_path, log_path, junit)):
        raise RuntimeError(f"stale evidence for {gate}; use a fresh build workspace")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env = dict(os.environ, BEAMO_GATE_CHILD="1", BEAMO_GATE_JUNIT=str(junit))
    started = utc_now_s()
    log_digest = hashlib.sha256()
    log_size = 0
    with log_path.open("xb") as log:
        with subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) as proc:
            assert proc.stdout is not None
            for chunk in iter(lambda: proc.stdout.read1(65536), b""):
                log.write(chunk)
                log_digest.update(chunk)
                log_size += len(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            code = proc.wait()
        logged = os.fstat(log.fileno())
    try:
        current_log = os.stat(log_path, follow_symlinks=False)
    except OSError as exc:
        raise RuntimeError("execution log changed during gate") from exc
    if (
        not stat.S_ISREG(current_log.st_mode)
        or (current_log.st_dev, current_log.st_ino, current_log.st_size)
        != (logged.st_dev, logged.st_ino, log_size)
    ):
        raise RuntimeError("execution log changed during gate")
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
        from beamo_wipe.release_manifest import _open_regular_nofollow

        try:
            junit_fd = _open_regular_nofollow(junit)
        except RuntimeError as exc:
            raise RuntimeError("unsafe JUnit execution report") from exc
        with os.fdopen(junit_fd, "rb") as stream:
            junit_bytes = stream.read(16 * 1024 * 1024 + 1)
        if len(junit_bytes) > 16 * 1024 * 1024:
            raise RuntimeError("JUnit execution report is too large")
        try:
            parsed = parse_junit_xml(junit_bytes.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise RuntimeError("JUnit execution report is not UTF-8") from exc
        skips = parsed.pop("skips")
        measured = parsed
    environment = dict(platform=sys.platform, arch=platform.machine(),
                       python=platform.python_version(),
                       runner="cloudbuild" if build_id != "local" else "local")
    if gate == "qemu" and status == "pass":
        environment["qemu_evidence_sha256"] = qemu_evidence_digest(
            qemu_evidence_hashes(root / "qemu-evidence")
        )
    receipt = build_gate_receipt(
        gate=gate, status=status, command=_hide_host_paths(shlex.join(command)),
        source_commit=commit, build_id=build_id,
        environment=environment,
        measured=measured, skips=skips,
        log_sha256="" if status == "skip" else log_digest.hexdigest(),
        reason=reason, started_at=started, ended_at=ended,
    )
    _write(receipt_path, receipt)
    return receipt


def _image_directory_fd(root: Path, relative: Path) -> int:
    """Open a mounted-image directory without following any component link."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        for component in relative.parts:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _image_text(root: Path, relative: Path, *, required: bool, limit: int) -> str | None:
    """Read a regular image file, never a host file reached through a link."""
    try:
        parent_fd = _image_directory_fd(root, relative.parent)
        try:
            fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            with os.fdopen(fd, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
                    raise RuntimeError("unsafe image inventory input")
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise RuntimeError("unsafe image inventory input")
            return data.decode("utf-8")
        finally:
            os.close(parent_fd)
    except FileNotFoundError as exc:
        if not required:
            return None
        raise RuntimeError("missing image inventory input") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError("unsafe image inventory input") from exc


def _image_source_names(root: Path) -> list[str]:
    try:
        directory_fd = _image_directory_fd(root, Path("etc/apt/sources.list.d"))
        try:
            return sorted(
                name for name in os.listdir(directory_fd)
                if name.endswith((".list", ".sources"))
            )
        finally:
            os.close(directory_fd)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise RuntimeError("unsafe image inventory input") from exc


def _active_apt_uris(path: Path, content: str) -> set[str]:
    """Extract only active APT entries, excluding comments and disabled stanzas."""
    sources = set()
    if path.suffix != ".sources":
        for raw_line in content.splitlines():
            line = raw_line.partition("#")[0].strip()
            match = re.match(r"deb(?:-src)?\s+", line)
            if not match:
                continue
            remainder = line[match.end():].lstrip()
            if remainder.startswith("["):
                closing = remainder.find("]")
                if closing < 0:
                    continue
                remainder = remainder[closing + 1:].lstrip()
            uri = remainder.split(maxsplit=1)[0] if remainder else ""
            if uri.startswith(("http://", "https://")):
                sources.add(uri)
        return sources

    for paragraph in re.split(r"\n\s*\n", content):
        fields: dict[str, str] = {}
        current = ""
        for raw_line in paragraph.splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            if raw_line[0].isspace():
                if current:
                    fields[current] += " " + raw_line.strip()
                continue
            key, separator, value = raw_line.partition(":")
            if not separator:
                continue
            current = key.lower()
            fields[current] = value.partition("#")[0].strip()
        if fields.get("enabled", "yes").lower() == "no":
            continue
        sources.update(
            uri for uri in fields.get("uris", "").split()
            if uri.startswith(("http://", "https://"))
        )
    return sources


def collect_inventory(image_root: Path, dest: Path, commit: str) -> None:
    """Read package status and configured repositories from the mounted image."""
    sources = set()
    paths = [Path("etc/apt/sources.list")]
    paths.extend(Path("etc/apt/sources.list.d") / name for name in _image_source_names(image_root))
    for path in paths:
        content = _image_text(image_root, path, required=False, limit=1024 * 1024)
        if content is not None:
            sources.update(_active_apt_uris(path, content))
    status = _image_text(image_root, Path("var/lib/dpkg/status"), required=True, limit=16 * 1024 * 1024)
    assert status is not None
    inventory = build_package_inventory(
        packages=parse_dpkg_status(status),
        collected_from="squashfs var/lib/dpkg/status", apt_sources=sorted(sources),
        source_commit=commit,
    )
    _write(dest, inventory)


def load_receipts(directory: Path) -> list[dict]:
    """Bind every receipt to the retained execution log before finalization."""
    from beamo_wipe.release_manifest import _open_regular_nofollow

    _require_evidence_directory(directory)
    receipts = []
    for path in sorted(directory.glob("*.receipt.json")):
        fd = _open_regular_nofollow(path)
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise RuntimeError("CI gate receipt is too large")
        receipt = verify_gate_receipt(
            json.loads(raw, object_pairs_hook=_unique_json_fields)
        )
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

    allow_dirty = os.environ.get("ALLOW_DIRTY") == "1"
    dist = root / "dist"
    dest = dist / f"beamo-wipe-{__version__}-amd64.manifest.json"
    verified_manifest = rm.verify_build_manifest(dest, allow_dirty=allow_dirty)
    previous = json.loads(verified_manifest, object_pairs_hook=_unique_json_fields)
    if (previous["source"]["commit"] != rm.git_commit()
            or previous["build"]["release_build_id"] != os.environ.get("BUILD_ID", "local")):
        raise RuntimeError("built artifact belongs to another source or build")
    rm.require_verified_prior_checksum_list(dist, replace_link=True)
    evidence_dir = dist / "evidence"
    receipts = load_receipts(evidence_dir)
    _require_evidence_directory(evidence_dir)
    inventory_path = evidence_dir / "packages.json"
    with os.fdopen(rm._open_regular_nofollow(inventory_path), "rb") as stream:
        raw_inventory = stream.read(32 * 1024 * 1024 + 1)
    if len(raw_inventory) > 32 * 1024 * 1024:
        raise RuntimeError("CI package inventory is too large")
    inventory = json.loads(raw_inventory, object_pairs_hook=_unique_json_fields)
    manifest = rm.generate_manifest(strict=not allow_dirty, gate_receipts=receipts, package_inventory=inventory)
    if manifest["artifact"] != previous["artifact"]:
        raise RuntimeError("artifact changed during verification")
    for field in ("beamo_wipe_version", "source", "dependencies", "live_build_inputs", "nwipe"):
        if manifest[field] != previous[field]:
            raise RuntimeError("build inputs changed during verification")
    rm.write_manifest(manifest, dest)
    rm.verify_manifest(dest, allow_dirty=allow_dirty)
    iso = dist / manifest["artifact"]["iso_name"]
    # Publish beside the verified artifacts without opening a pre-existing
    # checksum path, which may have been replaced by a symlink.
    rm._atomic_write(
        dist / "SHA256SUMS",
        f"{rm.sha256_file(iso)}  {iso.name}\n{rm.sha256_file(dest)}  {dest.name}\n".encode("ascii"),
    )
    print("Final verified evidence: " + json.dumps({
        "source_commit": manifest["source"]["commit"],
        "build_id": manifest["build"]["release_build_id"],
        "iso_sha256": rm.sha256_file(iso),
        "manifest_sha256": rm.sha256_file(dest),
        "gate_count": len(receipts),
        "packages_sha256": rm.sha256_file(dist / "evidence/packages.json"),
    }, sort_keys=True), flush=True)


def print_summary(evidence_dir: Path) -> None:
    """Print pass/fail/skip and elapsed seconds for every written receipt."""
    if not evidence_dir.is_dir():
        print("CI timing summary: no evidence directory")
        return
    from beamo_wipe.release_manifest import _open_regular_nofollow

    _require_evidence_directory(evidence_dir)
    rows = []
    for path in sorted(evidence_dir.glob("*.receipt.json")):
        with os.fdopen(_open_regular_nofollow(path), "rb") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise RuntimeError("CI gate receipt is too large")
        receipt = verify_gate_receipt(
            json.loads(raw, object_pairs_hook=_unique_json_fields)
        )
        if path.name != f"{receipt['gate']}.receipt.json":
            raise RuntimeError("receipt filename does not match its gate")
        started = receipt.get("started_at", "")
        ended = receipt.get("ended_at", "")
        elapsed = "unknown"
        try:
            start = datetime.datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")
            end = datetime.datetime.strptime(ended, "%Y-%m-%dT%H:%M:%SZ")
            elapsed = f"{int((end - start).total_seconds())}s"
        except (TypeError, ValueError):
            pass
        rows.append((receipt["gate"], receipt["status"], elapsed))
    print("CI timing summary")
    for gate, status, elapsed in rows:
        print(f"  {gate}: {status} {elapsed}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=sorted(KNOWN_GATES) + ["inventory", "summary"])
    parser.add_argument("--image-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    evidence = root / "dist/evidence"
    if args.gate == "summary":
        print_summary(evidence)
        return 0
    if args.gate == "inventory":
        if args.image_root is None:
            parser.error("inventory requires --image-root")
        from beamo_wipe.release_manifest import git_commit
        _require_evidence_directory(evidence, create=True)
        collect_inventory(args.image_root, evidence / "packages.json", git_commit())
        return 0
    receipt = run_gate(args.gate, ["bash", "scripts/ci-hosted.sh", args.gate],
                       root=root, evidence_dir=evidence, build_id=os.environ.get("BUILD_ID", "local"))
    if receipt["status"] == "fail":
        return 1
    if args.gate == "qemu" and receipt["status"] == "pass":
        finalize(root)
        print_summary(evidence)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"CI evidence failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
