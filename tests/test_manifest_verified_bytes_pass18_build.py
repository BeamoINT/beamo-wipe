"""Release finalization must consume the exact bounded bytes it verified."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from beamo_wipe import ci_evidence
from beamo_wipe import release_manifest as rm


def test_finalizer_uses_verified_manifest_bytes_after_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUILD_ID", "local")
    dist = tmp_path / "dist"
    dist.mkdir()
    dest = dist / "beamo-wipe-0.2.10-amd64.manifest.json"
    verified = {
        "source": {"commit": "a" * 40},
        "build": {"release_build_id": "local"},
    }
    verified_bytes = json.dumps(verified).encode()
    dest.write_bytes(verified_bytes)

    def verify_and_replace(_path: Path, *, allow_dirty: bool = False) -> bytes:
        assert _path == dest
        dest.write_text('{"source":{},"build":{}}')
        return verified_bytes

    monkeypatch.setattr(rm, "verify_build_manifest", verify_and_replace)
    monkeypatch.setattr(rm, "git_commit", lambda: "a" * 40)
    monkeypatch.setattr(ci_evidence, "load_receipts", lambda _path: (_ for _ in ()).throw(RuntimeError("reached receipts")))
    with pytest.raises(RuntimeError, match="reached receipts"):
        ci_evidence.finalize(tmp_path)


def test_manifest_verifier_rejects_oversize_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "beamo-wipe-0.2.10-amd64.manifest.json"
    with path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    parsed = False

    def record_parse(*_args, **_kwargs):
        nonlocal parsed
        parsed = True
        raise AssertionError("oversized manifest reached JSON parser")

    monkeypatch.setattr(rm.json, "loads", record_parse)
    with pytest.raises(RuntimeError, match="manifest.*(large|limit)"):
        rm.verify_build_manifest(path, allow_dirty=True)
    assert not parsed
