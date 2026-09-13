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


class PublishError(RuntimeError):
    """A release precondition or authenticated upload failed."""


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
    parsed = urlsplit(location)
    if parsed.scheme != "https" or parsed.hostname != STORAGE_HOST or parsed.username or parsed.password:
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
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise PublishError(f"missing release directory for {path.name}") from exc
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid():
        raise PublishError(f"unsafe release directory for {path.name}")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PublishError(f"missing release input: {path.name}") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise PublishError(f"unsafe release input: {path.name}")


def _open_owned_file(path: Path) -> BinaryIO:
    _regular_owned_file(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise PublishError(f"cannot securely open release input: {path.name}") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise PublishError(f"unsafe release input: {path.name}")
        return os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise


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


def _verify_usb_image(dist: Path, version: str) -> None:
    """Bind the desktop-readable image to the verified ISO before uploading."""
    image = dist / f"beamo-wipe-{version}-amd64.img"
    iso = dist / f"beamo-wipe-{version}-amd64.iso"
    try:
        with _open_owned_file(Path(f"{image}.json")) as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise PublishError("USB image metadata exceeded the safety limit")
        metadata = json.loads(raw)
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
        *[
            ROOT / "qemu-evidence" / name
            for name in (
                "run.txt",
                "qemu-version.txt",
                "source-commit.txt",
                "checksums.txt",
                "isoinfo.txt",
                "nwipe-version.txt",
                "fixed-vulnerabilities.txt",
                "fake-disk-e2e.txt",
                "qemu-img.txt",
                "nwipe-invalid-target.txt",
                "uefi-serial.txt",
                "uefi-qemu.txt",
                "bios-usb-serial.txt",
                "bios-usb-qemu.txt",
                "uefi-usb-serial.txt",
                "uefi-usb-qemu.txt",
                "secureboot-usb-serial.txt",
                "secureboot-usb-qemu.txt",
                "bios-speech-usb-serial.txt",
                "bios-speech-usb-qemu.txt",
                "uefi-speech-usb-serial.txt",
                "uefi-speech-usb-qemu.txt",
                "summary.txt",
            )
        ],
        *[
            ROOT / "qemu-evidence" / name
            for base_method in ("everyday", "extra", "quick_zero")
            for method in (base_method, f"{base_method}-repeat")
            for name in (
                f"host-{method}.log", f"host-{method}-nwipe.txt",
                f"bios-{method}-serial.txt", f"bios-{method}-qemu.txt",
                f"bios-{method}-cmdline.txt", f"guest-{method}-readback.txt",
                f"guest-{method}-bundle.txt", f"guest-{method}-fsck.txt",
            )
        ],
        *[
            ROOT / "dist" / "evidence" / name
            for gate in ("lint", "tests", "preview", "negative", "iso", "qemu")
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


def _sign_release_manifest(dist: Path, version: str) -> Path:
    """Sign the verified manifest and verify the sidecar before upload."""
    sys.path.insert(0, str(ROOT / "src"))
    from beamo_wipe.release_signing import (
        load_key_registry,
        sign_manifest_bytes,
        verify_with_registry,
    )

    manifest = dist / f"beamo-wipe-{version}-amd64.manifest.json"
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
                )
            )
        )
    except (OSError, ValueError) as exc:
        raise PublishError("publisher key registry is unreadable") from exc
    try:
        result = verify_with_registry(manifest_bytes, sidecar, registry)
    except RuntimeError as exc:
        raise PublishError(f"fresh manifest signature rejected: {exc}") from exc
    sig_path = Path(f"{manifest}.sig")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(sig_path, flags, 0o600)
    except FileExistsError as exc:
        raise PublishError("stale signature sidecar already exists") from exc
    except OSError as exc:
        raise PublishError("signature sidecar cannot be written") from exc
    try:
        payload = (json.dumps(sidecar, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
    except OSError as exc:
        raise PublishError("signature sidecar cannot be written") from exc
    print(f"Signed manifest with publisher key {result['key_id']}")
    return sig_path


def publish() -> str | None:
    if os.environ.get("PUBLISH_RELEASE", "false") != "true":
        print("Release publication disabled; verified artifacts remain ephemeral.")
        return None
    if os.environ.get("SKIP_ISO", "false") == "true" or os.environ.get("SKIP_QEMU", "false") == "true":
        raise PublishError("refusing release publication with a skipped ISO or QEMU gate")

    version = os.environ.get("BEAMO_WIPE_VERSION", "0.2.7")
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
    from beamo_wipe.ci_evidence import load_receipts

    manifest_path = ROOT / "dist" / f"beamo-wipe-{version}-amd64.manifest.json"
    verify_manifest(manifest_path)
    manifest_data = json.loads(manifest_path.read_text())
    if (manifest_data["source"]["commit"] != commit
            or manifest_data["build"]["release_build_id"] != build_id):
        raise PublishError("manifest does not match the release source and build")
    receipts = {r["gate"]: r for r in load_receipts(ROOT / "dist" / "evidence")}
    if receipts != manifest_data["test_evidence"]["gates"]:
        raise PublishError("execution receipts do not match the verified manifest")
    _sign_release_manifest(ROOT / "dist", version)
    _regular_owned_file(ROOT / "dist" / sig_name)
    _verify_sha256sums(ROOT / "dist", version)
    _verify_usb_image(ROOT / "dist", version)

    receipt_lines = [
        "release_complete=true",
        f"build_id={build_id}",
        f"version={version}",
        f"source_commit={commit}",
    ]
    for path in inputs:
        object_name = _object_name(build_id, path.name)
        local_sha = _sha256(path)
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
