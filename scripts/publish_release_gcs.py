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


def _release_inputs(version: str) -> list[Path]:
    iso = ROOT / "dist" / f"beamo-wipe-{version}-amd64.iso"
    manifest = ROOT / "dist" / f"beamo-wipe-{version}-amd64.manifest.json"
    return [
        iso,
        Path(f"{iso}.sha256"),
        manifest,
        Path(f"{manifest}.sha256"),
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
                "nwipe-boundary.txt",
                "nwipe-invalid-target.txt",
                "bios-serial.txt",
                "bios-qemu.txt",
                "uefi-serial.txt",
                "uefi-qemu.txt",
                "summary.txt",
            )
        ],
    ]


def publish() -> str | None:
    if os.environ.get("PUBLISH_RELEASE", "false") != "true":
        print("Release publication disabled; verified artifacts remain ephemeral.")
        return None
    if os.environ.get("SKIP_ISO", "false") == "true" or os.environ.get("SKIP_QEMU", "false") == "true":
        raise PublishError("refusing release publication with a skipped ISO or QEMU gate")

    version = os.environ.get("BEAMO_WIPE_VERSION", "0.2.1")
    build_id = os.environ.get("BUILD_ID", "")
    if not VERSION_RE.fullmatch(version):
        raise PublishError("invalid BEAMO_WIPE_VERSION")
    if not BUILD_ID_RE.fullmatch(build_id):
        raise PublishError("missing or invalid Cloud Build ID")

    inputs = _release_inputs(version)
    for path in inputs:
        _regular_owned_file(path)
    commit = _verify_source(version)

    sys.path.insert(0, str(ROOT / "src"))
    from beamo_wipe.release_manifest import verify_manifest

    verify_manifest(ROOT / "dist" / f"beamo-wipe-{version}-amd64.manifest.json")
    _verify_sha256sums(ROOT / "dist", version)

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
