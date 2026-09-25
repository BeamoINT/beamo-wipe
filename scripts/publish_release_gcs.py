#!/usr/bin/env python3
"""Explicit, no-overwrite GCS publisher for verified Beamo Wipe releases."""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import BinaryIO
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "beamo-wipe_cloudbuild"
RELEASE_PREFIX = "releases"
STORAGE_HOST = "storage.googleapis.com"
METADATA_HOST = "metadata.google.internal"
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
BUILD_ID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
CHUNK_SIZE = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_QEMU_LOG_LINE_BYTES = 1024 * 1024


class PublishError(RuntimeError):
    """A release precondition or authenticated upload failed."""


def _unique_json_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise PublishError(f"duplicate JSON field in release input: {key}")
        fields[key] = value
    return fields


def _response_bytes(response: http.client.HTTPResponse) -> bytes:
    try:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    finally:
        response.close()
    if len(data) > MAX_RESPONSE_BYTES:
        raise PublishError("Google API response exceeded the safety limit")
    return data


def _metadata_token() -> str:
    connection = http.client.HTTPConnection(METADATA_HOST, timeout=10)
    try:
        try:
            connection.request(
                "GET",
                "/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"},
            )
            response = connection.getresponse()
            body = _response_bytes(response)
            if response.status != 200:
                raise PublishError(f"metadata authentication failed with status {response.status}")
        except (OSError, http.client.HTTPException) as exc:
            raise PublishError("metadata authentication transport failed") from exc
    finally:
        connection.close()
    try:
        payload = json.loads(body)
        token = payload["access_token"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise PublishError("metadata authentication returned an invalid response") from exc
    if not isinstance(token, str) or not 20 <= len(token) <= 8192 or any(ch.isspace() for ch in token):
        raise PublishError("metadata authentication returned an invalid token")
    return token


def _object_name(build_id: str, filename: str) -> str:
    if not BUILD_ID_RE.fullmatch(build_id):
        raise PublishError("missing or invalid Cloud Build ID")
    if not filename or filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise PublishError("invalid release filename")
    return f"{RELEASE_PREFIX}/{build_id}/{filename}"


def _start_resumable_upload(object_name: str, size: int, token: str) -> str:
    query = urlencode(
        {
            "uploadType": "resumable",
            "name": object_name,
            "ifGenerationMatch": "0",
        }
    )
    connection = http.client.HTTPSConnection(STORAGE_HOST, timeout=30)
    try:
        try:
            connection.request(
                "POST",
                f"/upload/storage/v1/b/{quote(BUCKET, safe='')}/o?{query}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Length": "0",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Length": str(size),
                    "X-Upload-Content-Type": "application/octet-stream",
                },
            )
            response = connection.getresponse()
            location = response.getheader("Location", "")
            _response_bytes(response)
            if response.status == 412:
                raise PublishError("release object already exists")
            if response.status not in {200, 201}:
                raise PublishError(f"upload initialization failed with status {response.status}")
        except (OSError, http.client.HTTPException) as exc:
            raise PublishError("upload initialization transport failed") from exc
    finally:
        connection.close()
    try:
        parsed = urlsplit(location)
        valid_endpoint = (
            parsed.scheme == "https"
            and parsed.hostname == STORAGE_HOST
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
        )
    except ValueError as exc:
        raise PublishError(
            "upload initialization returned an invalid endpoint"
        ) from exc
    if not valid_endpoint:
        raise PublishError("upload initialization returned an invalid endpoint")
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _send_upload(location: str, stream: BinaryIO, size: int, token: str) -> None:
    connection = http.client.HTTPSConnection(STORAGE_HOST, timeout=120)
    try:
        try:
            connection.putrequest("PUT", location)
            connection.putheader("Authorization", f"Bearer {token}")
            connection.putheader("Content-Length", str(size))
            connection.putheader("Content-Type", "application/octet-stream")
            connection.endheaders()
            remaining = size
            while remaining:
                chunk = stream.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise PublishError("release input ended before its declared size")
                connection.send(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise PublishError("release input grew during upload")
            response = connection.getresponse()
            _response_bytes(response)
            if response.status not in {200, 201}:
                raise PublishError(f"release upload failed with status {response.status}")
        except (OSError, http.client.HTTPException) as exc:
            # Never include the resumable session URI: it is an upload credential.
            raise PublishError("release upload transport failed") from exc
    finally:
        connection.close()


def _upload_stream(object_name: str, stream: BinaryIO, size: int) -> None:
    token = _metadata_token()
    location = _start_resumable_upload(object_name, size, token)
    _send_upload(location, stream, size, token)


def _upload_file(path: Path, object_name: str) -> None:
    with _open_owned_file(path) as stream:
        _upload_stream(object_name, stream, os.fstat(stream.fileno()).st_size)


def _remote_sha256(object_name: str) -> str:
    token = _metadata_token()
    encoded_object = quote(object_name, safe="")
    connection = http.client.HTTPSConnection(STORAGE_HOST, timeout=120)
    digest = hashlib.sha256()
    try:
        try:
            connection.request(
                "GET",
                f"/storage/v1/b/{quote(BUCKET, safe='')}/o/{encoded_object}?alt=media",
                headers={"Authorization": f"Bearer {token}"},
            )
            response = connection.getresponse()
            if response.status != 200:
                _response_bytes(response)
                raise PublishError(f"uploaded-byte verification failed with status {response.status}")
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
            response.close()
        except (OSError, http.client.HTTPException) as exc:
            raise PublishError("uploaded-byte verification transport failed") from exc
    finally:
        connection.close()
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _open_owned_file(path) as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_owned_file(path: Path) -> None:
    with _open_owned_file(path):
        pass


def _open_owned_parent(path: Path) -> int:
    """Pin every release-input parent without following an ancestor link."""
    parts = path.absolute().parts
    if ".." in parts:
        raise PublishError(f"unsafe release directory for {path.name}")
    fd = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in parts[1:-1]:
            next_fd = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=fd,
            )
            os.close(fd)
            fd = next_fd
        if os.fstat(fd).st_uid != os.getuid():
            raise PublishError(f"unsafe release directory for {path.name}")
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_owned_file(path: Path) -> BinaryIO:
    try:
        parent_fd = _open_owned_parent(path)
    except OSError as exc:
        raise PublishError(f"unsafe release directory for {path.name}") from exc
    try:
        try:
            fd = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise PublishError(f"unsafe release input: {path.name}") from exc
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise PublishError(f"unsafe release input: {path.name}")
            return os.fdopen(fd, "rb")
        except Exception:
            os.close(fd)
            raise
    finally:
        os.close(parent_fd)


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PublishError("source identity verification failed") from exc
    return result.stdout.strip()


def _verify_source(version: str) -> str:
    if _git("status", "--porcelain"):
        raise PublishError("refusing release publication from a dirty source tree")
    commit = _git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PublishError("source commit is invalid")
    tags = _git("tag", "--points-at", commit).splitlines()
    if f"v{version}" not in tags:
        raise PublishError(f"release tag v{version} does not point at the source commit")
    return commit


def _verify_sha256sums(dist: Path, version: str) -> None:
    iso_name = f"beamo-wipe-{version}-amd64.iso"
    manifest_name = f"beamo-wipe-{version}-amd64.manifest.json"
    sums_path = dist / "SHA256SUMS"
    try:
        with _open_owned_file(sums_path) as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise PublishError("SHA256SUMS exceeded the safety limit")
        lines = raw.decode("ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PublishError("SHA256SUMS is unreadable") from exc
    expected_names = [iso_name, manifest_name]
    if len(lines) != len(expected_names):
        raise PublishError("SHA256SUMS has an unexpected number of entries")
    for line, name in zip(lines, expected_names, strict=True):
        expected = f"{_sha256(dist / name)}  {name}"
        if line != expected:
            raise PublishError(f"SHA256SUMS mismatch for {name}")


def _verify_usb_image(dist: Path, version: str) -> tuple[str, str]:
    """Bind the desktop-readable image to the verified ISO before uploading."""
    image = dist / f"beamo-wipe-{version}-amd64.img"
    iso = dist / f"beamo-wipe-{version}-amd64.iso"
    try:
        with _open_owned_file(Path(f"{image}.json")) as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise PublishError("USB image metadata exceeded the safety limit")
        metadata = json.loads(raw, object_pairs_hook=_unique_json_fields)
        with _open_owned_file(Path(f"{image}.sha256")) as stream:
            sidecar = stream.read(4097).decode("ascii")
        with _open_owned_file(image) as stream:
            size = os.fstat(stream.fileno()).st_size
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublishError("USB image metadata is unreadable") from exc
    image_sha = _sha256(image)
    expected = {
        "schema_version": 1,
        "image": image.name,
        "sha256": image_sha,
        "iso": iso.name,
        "iso_sha256": _sha256(iso),
        "layout": "MBR, one active FAT32 partition at sector 2048",
        "size": size,
    }
    if (
        not isinstance(metadata, dict)
        or metadata != expected
        or type(metadata.get("schema_version")) is not int
        or type(metadata.get("size")) is not int
        or size <= 0
        or sidecar != f"{image_sha}  {image.name}\n"
    ):
        raise PublishError("USB image does not match its ISO, metadata, or checksum")
    return image_sha, hashlib.sha256(raw).hexdigest()


def _qemu_tested_usb_sha(root: Path) -> str:
    """Read the image digest retained in the signed QEMU gate log."""
    log_path = root / "dist" / "evidence" / "qemu.log"
    prefix = b"[qemu-verify] usb_image_sha256="
    found = []
    with _open_owned_file(log_path) as stream:
        while line := stream.readline(MAX_QEMU_LOG_LINE_BYTES + 1):
            if len(line) > MAX_QEMU_LOG_LINE_BYTES:
                raise PublishError("QEMU execution log line exceeded the safety limit")
            if line.startswith(prefix):
                value = line[len(prefix):].strip()
                if not re.fullmatch(rb"[0-9a-f]{64}", value):
                    raise PublishError("invalid QEMU-tested USB image digest")
                found.append(value.decode("ascii"))
    if len(found) != 1:
        raise PublishError("missing or ambiguous QEMU-tested USB image digest")
    return found[0]


def _verified_json_input_sha(
    path: Path, expected: object, *, limit: int, label: str
) -> str:
    """Bind a separate JSON evidence file to the signed manifest contents."""
    with _open_owned_file(path) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise PublishError(f"{label} exceeded the safety limit")
    try:
        actual = json.loads(raw, object_pairs_hook=_unique_json_fields)
        canonical_actual = json.dumps(
            actual, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
        canonical_expected = json.dumps(
            expected, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
        if not isinstance(actual, dict) or canonical_actual != canonical_expected:
            raise PublishError(f"{label} differs from verified manifest")
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise PublishError(f"{label} is unreadable") from exc
    return hashlib.sha256(raw).hexdigest()


def _qemu_evidence_names() -> list[str]:
    """Complete flat output inventory of scripts/qemu-verify.sh."""
    names = [
        "run.txt",
        "untested-physical.txt",
        "qemu-version.txt",
        "source-commit.txt",
        "checksums.txt",
        "isoinfo.txt",
        "nwipe-version.txt",
        "fixed-vulnerabilities.txt",
        "accessible-runtime.txt",
        "report-image.txt",
        "report-helper-crash.txt",
        "fake-disk-e2e.txt",
        "qemu-img.txt",
        "nwipe-invalid-target.txt",
        "summary.txt",
    ]
    for label in (
        "uefi",
        "bios-usb",
        "uefi-usb",
        "secureboot-usb",
        "bios-speech-usb",
        "uefi-speech-usb",
    ):
        names.extend(f"{label}-{suffix}.txt" for suffix in ("serial", "qemu", "cmdline"))
    for method in ("everyday", "extra", "quick_zero"):
        for case in (method, f"{method}-repeat"):
            names.extend(
                (
                    f"host-{case}.log",
                    f"host-{case}-nwipe.txt",
                    f"bios-{case}-serial.txt",
                    f"bios-{case}-qemu.txt",
                    f"bios-{case}-cmdline.txt",
                    f"guest-{case}-readback.txt",
                    f"guest-{case}-bundle.txt",
                    f"guest-{case}-fsck.txt",
                    f"guest-{case}-mount.txt",
                )
            )
    return names


def _require_complete_qemu_inputs(hashes: dict[str, str], paths: list[Path]) -> None:
    """Do not mark a release complete with omitted or extra QEMU evidence."""
    names = [path.name for path in paths]
    if len(names) != len(set(names)) or set(names) != set(hashes):
        raise PublishError("QEMU evidence inventory differs from release inputs")


def _release_inputs(version: str) -> list[Path]:
    iso = ROOT / "dist" / f"beamo-wipe-{version}-amd64.iso"
    image = ROOT / "dist" / f"beamo-wipe-{version}-amd64.img"
    manifest = ROOT / "dist" / f"beamo-wipe-{version}-amd64.manifest.json"
    return [
        iso,
        Path(f"{iso}.sha256"),
        image,
        Path(f"{image}.sha256"),
        Path(f"{image}.json"),
        manifest,
        Path(f"{manifest}.sha256"),
        Path(f"{manifest}.sig"),
        ROOT / "dist" / "SHA256SUMS",
        *[ROOT / "qemu-evidence" / name for name in _qemu_evidence_names()],
        *[
            ROOT / "dist" / "evidence" / name
            for gate in (
                "lint",
                "tests",
                "preview",
                "desktop-launchers",
                "negative",
                "iso",
                "qemu",
            )
            for name in (f"{gate}.receipt.json", f"{gate}.log")
        ],
        ROOT / "dist" / "evidence" / "packages.json",
    ]


def _read_signing_key() -> bytes:
    """Load the publisher key from the operator-provided file, fail closed.

    The key file arrives only via an operator-invoked release submission
    (Secret Manager); trigger builds never carry it, so its absence here
    refuses publication instead of publishing unsigned.
    """
    key_path = os.environ.get("BEAMO_WIPE_SIGNING_KEY_FILE", "")
    if not key_path:
        raise PublishError("refusing release publication without signing material")
    path = Path(key_path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PublishError("signing material is unreadable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise PublishError("unsafe signing material")
    if stat.S_IMODE(metadata.st_mode) not in (0o600, 0o400):
        raise PublishError("signing material must be mode 0600 or 0400")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise PublishError("signing material cannot be securely opened") from exc
    try:
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_uid, opened.st_mode) != (
                metadata.st_dev, metadata.st_ino, metadata.st_uid, metadata.st_mode
            ):
                raise PublishError("signing material changed while opening")
            raw = stream.read(33)
    except OSError as exc:
        raise PublishError("signing material cannot be read") from exc
    if len(raw) != 32:
        raise PublishError("signing material must hold 32 raw bytes")
    return raw


def _sign_release_manifest(
    dist: Path, version: str, *, manifest_bytes: bytes | None = None
) -> tuple[Path, str]:
    """Sign the verified manifest and verify the sidecar before upload."""
    sys.path.insert(0, str(ROOT / "src"))
    from beamo_wipe.release_signing import (
        load_key_registry,
        sign_manifest_bytes,
        verify_with_registry,
    )

    manifest = dist / f"beamo-wipe-{version}-amd64.manifest.json"
    if manifest_bytes is None:
        with _open_owned_file(manifest) as stream:
            manifest_bytes = stream.read(16 * 1024 * 1024 + 1)
    if len(manifest_bytes) > 16 * 1024 * 1024:
        raise PublishError("manifest exceeded the safety limit")
    sidecar = sign_manifest_bytes(manifest_bytes, _read_signing_key())
    try:
        registry = load_key_registry(
            json.loads(
                (ROOT / "packaging" / "release-keys" / "keys.json").read_text(
                    encoding="utf-8"
                ),
                object_pairs_hook=_unique_json_fields,
            )
        )
    except (OSError, ValueError) as exc:
        raise PublishError("publisher key registry is unreadable") from exc
    try:
        result = verify_with_registry(manifest_bytes, sidecar, registry)
    except RuntimeError as exc:
        raise PublishError(f"fresh manifest signature rejected: {exc}") from exc
    sig_path = Path(f"{manifest}.sig")
    payload = (json.dumps(sidecar, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        parent_fd = _open_owned_parent(sig_path)
    except OSError as exc:
        raise PublishError("signature sidecar directory is unsafe") from exc
    try:
        try:
            fd = os.open(sig_path.name, flags, 0o600, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise PublishError("stale signature sidecar already exists") from exc
        except OSError as exc:
            raise PublishError("signature sidecar cannot be written") from exc
        owned = os.fstat(fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(payload)
        except OSError as exc:
            if fd >= 0:
                os.close(fd)
            try:
                current = os.stat(
                    sig_path.name, dir_fd=parent_fd, follow_symlinks=False
                )
            except OSError:
                pass
            else:
                if stat.S_ISREG(current.st_mode) and (
                    current.st_dev, current.st_ino
                ) == (owned.st_dev, owned.st_ino):
                    os.unlink(sig_path.name, dir_fd=parent_fd)
            raise PublishError("signature sidecar cannot be written") from exc
    finally:
        os.close(parent_fd)
    print(f"Signed manifest with publisher key {result['key_id']}")
    return sig_path, hashlib.sha256(payload).hexdigest()


def publish() -> str | None:
    if os.environ.get("PUBLISH_RELEASE", "false") != "true":
        print("Release publication disabled; verified artifacts remain ephemeral.")
        return None
    if os.environ.get("SKIP_ISO", "false") == "true" or os.environ.get("SKIP_QEMU", "false") == "true":
        raise PublishError("refusing release publication with a skipped ISO or QEMU gate")

    version = os.environ.get("BEAMO_WIPE_VERSION", "0.2.9")
    build_id = os.environ.get("BUILD_ID", "")
    if not VERSION_RE.fullmatch(version):
        raise PublishError("invalid BEAMO_WIPE_VERSION")
    if not BUILD_ID_RE.fullmatch(build_id):
        raise PublishError("missing or invalid Cloud Build ID")

    inputs = _release_inputs(version)
    sig_name = f"beamo-wipe-{version}-amd64.manifest.json.sig"
    for path in inputs:
        if path.name == sig_name:
            continue  # created by signing below, after manifest verification
        _regular_owned_file(path)
    commit = _verify_source(version)

    sys.path.insert(0, str(ROOT / "src"))
    from beamo_wipe.release_manifest import verify_manifest
    from beamo_wipe.ci_evidence import (
        load_receipts, qemu_evidence_digest, qemu_evidence_hashes,
    )

    manifest_path = ROOT / "dist" / f"beamo-wipe-{version}-amd64.manifest.json"
    validated_manifest = verify_manifest(manifest_path)
    validated_sha = hashlib.sha256(validated_manifest).hexdigest()
    manifest_data = json.loads(
        validated_manifest, object_pairs_hook=_unique_json_fields
    )
    if (manifest_data["source"]["commit"] != commit
            or manifest_data["build"]["release_build_id"] != build_id):
        raise PublishError("manifest does not match the release source and build")
    receipts = {r["gate"]: r for r in load_receipts(ROOT / "dist" / "evidence")}
    if receipts != manifest_data["test_evidence"]["gates"]:
        raise PublishError("execution receipts do not match the verified manifest")
    package_path = ROOT / "dist" / "evidence" / "packages.json"
    package_sha = (
        _verified_json_input_sha(
            package_path, manifest_data.get("installed_packages"),
            limit=32 * 1024 * 1024, label="package inventory",
        )
        if package_path in inputs else None
    )
    receipt_sha = {
        ROOT / "dist" / "evidence" / f"{gate}.receipt.json":
            _verified_json_input_sha(
                ROOT / "dist" / "evidence" / f"{gate}.receipt.json",
                receipt, limit=4 * 1024 * 1024, label="gate receipt",
            )
        for gate, receipt in receipts.items()
        if ROOT / "dist" / "evidence" / f"{gate}.receipt.json" in inputs
    }
    qemu_paths = [path for path in inputs if path.parent == ROOT / "qemu-evidence"]
    qemu_hashes = {}
    if qemu_paths:
        expected_qemu_digest = receipts.get("qemu", {}).get("environment", {}).get(
            "qemu_evidence_sha256"
        )
        if not isinstance(expected_qemu_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_qemu_digest
        ):
            raise PublishError("QEMU receipt does not bind its copied evidence")
        try:
            qemu_hashes = qemu_evidence_hashes(ROOT / "qemu-evidence")
        except RuntimeError as exc:
            raise PublishError("QEMU evidence changed after gate") from exc
        if qemu_evidence_digest(qemu_hashes) != expected_qemu_digest:
            raise PublishError("QEMU evidence changed after gate")
        _require_complete_qemu_inputs(qemu_hashes, qemu_paths)
    expected_log_sha = {
        ROOT / "dist" / "evidence" / f"{gate}.log": receipt["log_sha256"]
        for gate, receipt in receipts.items()
        if receipt["status"] != "skip"
    }
    if _sha256(manifest_path) != validated_sha:
        raise PublishError("manifest changed after verification")
    _verify_sha256sums(ROOT / "dist", version)
    tested_usb_sha = _qemu_tested_usb_sha(ROOT)
    verified_usb_sha, metadata_sha = _verify_usb_image(ROOT / "dist", version)
    if verified_usb_sha != tested_usb_sha:
        raise PublishError("USB image differs from QEMU-tested USB image")

    iso_name = f"beamo-wipe-{version}-amd64.iso"
    image_name = f"beamo-wipe-{version}-amd64.img"
    manifest_name = manifest_path.name
    iso_sha = manifest_data["artifact"]["iso_sha256"]
    expected_sidecars = {
        ROOT / "dist" / f"{iso_name}.sha256": f"{iso_sha}  {iso_name}\n".encode("ascii"),
        ROOT / "dist" / f"{image_name}.sha256": f"{tested_usb_sha}  {image_name}\n".encode("ascii"),
        ROOT / "dist" / f"{manifest_name}.sha256": f"{validated_sha}  {manifest_name}\n".encode("ascii"),
        ROOT / "dist" / "SHA256SUMS": (
            f"{iso_sha}  {iso_name}\n{validated_sha}  {manifest_name}\n"
        ).encode("ascii"),
    }
    # Finish all artifact checks before creating the one-use signature file.
    # A failed preflight can then be repaired and retried without stale output.
    signature_path, signature_sha = _sign_release_manifest(
        ROOT / "dist", version, manifest_bytes=validated_manifest
    )
    if signature_path != ROOT / "dist" / sig_name:
        raise PublishError("signature sidecar path changed during signing")
    _regular_owned_file(signature_path)

    receipt_lines = [
        "release_complete=true",
        f"build_id={build_id}",
        f"version={version}",
        f"source_commit={commit}",
    ]
    for path in inputs:
        object_name = _object_name(build_id, path.name)
        local_sha = _sha256(path)
        if path == manifest_path and local_sha != validated_sha:
            raise PublishError("manifest changed after verification")
        if (
            path.name == f"beamo-wipe-{version}-amd64.iso"
            and local_sha != manifest_data["artifact"]["iso_sha256"]
        ):
            raise PublishError("ISO differs from the verified manifest")
        if path.name == f"beamo-wipe-{version}-amd64.img" and local_sha != tested_usb_sha:
            raise PublishError("USB image differs from QEMU-tested USB image")
        if path in expected_log_sha and local_sha != expected_log_sha[path]:
            raise PublishError("execution log changed after verification")
        if path in qemu_paths and local_sha != qemu_hashes[path.name]:
            raise PublishError("QEMU evidence changed after gate")
        if path == package_path and local_sha != package_sha:
            raise PublishError("package inventory changed after verification")
        if path in receipt_sha and local_sha != receipt_sha[path]:
            raise PublishError("gate receipt changed after verification")
        if path in expected_sidecars and local_sha != hashlib.sha256(expected_sidecars[path]).hexdigest():
            raise PublishError("checksum sidecar changed after verification")
        if path == ROOT / "dist" / f"{image_name}.json" and local_sha != metadata_sha:
            raise PublishError("USB image metadata changed after verification")
        if path == signature_path and local_sha != signature_sha:
            raise PublishError("signature changed after signing")
        _upload_file(path, object_name)
        if _remote_sha256(object_name) != local_sha:
            raise PublishError(f"uploaded byte verification failed for {path.name}")
        receipt_lines.append(f"{local_sha}  {path.name}")

    receipt = ("\n".join(receipt_lines) + "\n").encode("ascii")
    receipt_object = _object_name(build_id, "RELEASE_COMPLETE.txt")
    _upload_stream(receipt_object, io.BytesIO(receipt), len(receipt))
    if _remote_sha256(receipt_object) != hashlib.sha256(receipt).hexdigest():
        raise PublishError("release completion receipt verification failed")

    release_uri = f"gs://{BUCKET}/{RELEASE_PREFIX}/{build_id}/"
    print(f"Published and verified release path: {release_uri}")
    return release_uri


def main() -> int:
    try:
        publish()
    except PublishError as exc:
        print(f"Release publication failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
