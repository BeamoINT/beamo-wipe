"""A late release-output directory swap must not write a signature elsewhere."""

from __future__ import annotations

import pytest

from test_release_publisher import PUBLISHER


def _stub_signing(monkeypatch):
    from beamo_wipe import release_signing

    monkeypatch.setattr(PUBLISHER, "_read_signing_key", lambda: b"x" * 32)
    monkeypatch.setattr(
        release_signing,
        "sign_manifest_bytes",
        lambda _manifest, _key: {"key_id": "fixture"},
    )
    monkeypatch.setattr(release_signing, "load_key_registry", lambda _raw: {})
    monkeypatch.setattr(
        release_signing,
        "verify_with_registry",
        lambda _manifest, _sidecar, _registry: {"key_id": "fixture"},
    )


def test_signing_refuses_linked_output_parent(tmp_path, monkeypatch):
    _stub_signing(monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "dist"
    linked.symlink_to(outside, target_is_directory=True)
    version = "0.2.9"
    signature = outside / f"beamo-wipe-{version}-amd64.manifest.json.sig"

    with pytest.raises(PUBLISHER.PublishError, match="unsafe|signature"):
        PUBLISHER._sign_release_manifest(linked, version, manifest_bytes=b"{}")
    assert not signature.exists()


def test_failed_signature_write_removes_only_its_new_partial_file(
    tmp_path, monkeypatch
):
    _stub_signing(monkeypatch)
    version = "0.2.9"
    signature = tmp_path / f"beamo-wipe-{version}-amd64.manifest.json.sig"
    real_fdopen = PUBLISHER.os.fdopen

    class FailingStream:
        def __init__(self, fd, *args, **kwargs):
            self.stream = real_fdopen(fd, *args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def write(self, payload):
            self.stream.write(payload[:1])
            raise OSError("simulated full release filesystem")

    monkeypatch.setattr(PUBLISHER.os, "fdopen", FailingStream)
    with pytest.raises(
        PUBLISHER.PublishError, match="signature sidecar cannot be written"
    ):
        PUBLISHER._sign_release_manifest(tmp_path, version, manifest_bytes=b"{}")
    assert not signature.exists()


def test_failed_signature_write_preserves_replacement(tmp_path, monkeypatch):
    _stub_signing(monkeypatch)
    version = "0.2.9"
    signature = tmp_path / f"beamo-wipe-{version}-amd64.manifest.json.sig"
    real_fdopen = PUBLISHER.os.fdopen

    class ReplacingStream:
        def __init__(self, fd, *args, **kwargs):
            self.stream = real_fdopen(fd, *args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def write(self, payload):
            self.stream.write(payload[:1])
            signature.unlink()
            signature.write_bytes(b"replacement from another writer")
            raise OSError("simulated interrupted release write")

    monkeypatch.setattr(PUBLISHER.os, "fdopen", ReplacingStream)
    with pytest.raises(
        PUBLISHER.PublishError, match="signature sidecar cannot be written"
    ):
        PUBLISHER._sign_release_manifest(tmp_path, version, manifest_bytes=b"{}")
    assert signature.read_bytes() == b"replacement from another writer"
