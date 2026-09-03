# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed tests for the standard-library production publisher."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_wipe_release_publisher",
    ROOT / "scripts" / "publish_release_gcs.py",
)
assert SPEC and SPEC.loader
PUBLISHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PUBLISHER
SPEC.loader.exec_module(PUBLISHER)


class FakeResponse:
    def __init__(self, status: int, *, location: str = "", body: bytes = b"{}"):
        self.status = status
        self._location = location
        self._body = io.BytesIO(body)
        self.closed = False

    def getheader(self, name: str, default: str = "") -> str:
        return self._location if name.casefold() == "location" else default

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        self.closed = True


class InitConnection:
    response = FakeResponse(
        200,
        location="https://storage.googleapis.com/upload/storage/v1/b/b/o?upload_id=opaque",
    )
    request_args = None

    def __init__(self, host: str, timeout: int):
        assert host == PUBLISHER.STORAGE_HOST
        assert timeout == 30

    def request(self, *args, **kwargs) -> None:
        type(self).request_args = (args, kwargs)

    def getresponse(self):
        return type(self).response

    def close(self) -> None:
        pass


def test_object_name_rejects_paths_and_invalid_build_ids():
    build_id = "00000000-0000-0000-0000-000000000000"
    assert PUBLISHER._object_name(build_id, "image.iso") == f"releases/{build_id}/image.iso"
    with pytest.raises(PUBLISHER.PublishError):
        PUBLISHER._object_name(build_id, "../image.iso")
    with pytest.raises(PUBLISHER.PublishError):
        PUBLISHER._object_name("not-a-build", "image.iso")


def test_resumable_upload_is_no_overwrite_and_does_not_put_token_in_url(monkeypatch):
    monkeypatch.setattr(PUBLISHER.http.client, "HTTPSConnection", InitConnection)
    token = "sensitive-token-value-long-enough"
    location = PUBLISHER._start_resumable_upload("releases/id/image.iso", 123, token)
    args, kwargs = InitConnection.request_args
    assert args[0] == "POST"
    assert "ifGenerationMatch=0" in args[1]
    assert token not in args[1]
    assert kwargs["headers"]["Authorization"] == f"Bearer {token}"
    assert location.endswith("?upload_id=opaque")


def test_resumable_upload_rejects_existing_object_without_leaking_token(monkeypatch):
    class ExistingConnection(InitConnection):
        response = FakeResponse(412)

    monkeypatch.setattr(PUBLISHER.http.client, "HTTPSConnection", ExistingConnection)
    token = "sensitive-token-value-long-enough"
    with pytest.raises(PUBLISHER.PublishError, match="already exists") as caught:
        PUBLISHER._start_resumable_upload("releases/id/image.iso", 123, token)
    assert token not in str(caught.value)


def test_release_input_must_be_owned_regular_file(tmp_path):
    regular = tmp_path / "regular"
    regular.write_bytes(b"safe")
    PUBLISHER._regular_owned_file(regular)
    link = tmp_path / "link"
    link.symlink_to(regular)
    with pytest.raises(PUBLISHER.PublishError, match="unsafe"):
        PUBLISHER._regular_owned_file(link)


def test_send_upload_rejects_short_or_growing_input_before_success(monkeypatch):
    class SendConnection:
        chunks = []

        def __init__(self, host: str, timeout: int):
            assert host == PUBLISHER.STORAGE_HOST
            assert timeout == 120

        def putrequest(self, method: str, location: str) -> None:
            assert method == "PUT"
            assert location.startswith("/upload/")

        def putheader(self, _name: str, _value: str) -> None:
            pass

        def endheaders(self) -> None:
            pass

        def send(self, chunk: bytes) -> None:
            type(self).chunks.append(chunk)

        def getresponse(self):
            return FakeResponse(200)

        def close(self) -> None:
            pass

    monkeypatch.setattr(PUBLISHER.http.client, "HTTPSConnection", SendConnection)
    with pytest.raises(PUBLISHER.PublishError, match="ended before"):
        PUBLISHER._send_upload("/upload/session", io.BytesIO(b"a"), 2, "token")
    with pytest.raises(PUBLISHER.PublishError, match="grew"):
        PUBLISHER._send_upload("/upload/session", io.BytesIO(b"ab"), 1, "token")
    PUBLISHER._send_upload("/upload/session", io.BytesIO(b"ab"), 2, "token")
