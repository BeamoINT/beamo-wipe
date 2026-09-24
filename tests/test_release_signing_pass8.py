"""Publisher key files and signed JSON must keep one unambiguous meaning."""

import os
import stat
from pathlib import Path

import pytest

from beamo_wipe import release_signing as signing


def test_signed_manifest_duplicate_version_cannot_pass_acceptance():
    private, public = signing.generate_keypair()
    raw = b'{"beamo_wipe_version":"0.1.0","beamo_wipe_version":"9.9.9"}'
    signature = signing.sign_manifest_bytes(raw, private)
    registry = {
        signing.key_id(public): {
            "status": "active",
            "fingerprint": signing.fingerprint(public),
            "public_key": public,
        }
    }
    with pytest.raises(RuntimeError, match="duplicate"):
        signing.verify_release_acceptance(raw, signature, registry, min_version="1.0.0")


def test_keygen_private_file_is_private_before_any_chmod(tmp_path, monkeypatch):
    private_path = tmp_path / "publisher.key"
    public_path = tmp_path / "publisher.pub"
    original_chmod = Path.chmod

    def check_before_chmod(path, mode, *args, **kwargs):
        if path == private_path:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        return original_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", check_before_chmod)
    previous_umask = os.umask(0o022)
    try:
        assert (
            signing.main(
                [
                    "keygen",
                    "--private-out",
                    str(private_path),
                    "--public-out",
                    str(public_path),
                ]
            )
            == 0
        )
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600


def test_keygen_refuses_existing_private_file(tmp_path):
    private_path = tmp_path / "publisher.key"
    private_path.write_bytes(b"keep this unrelated content")
    public_path = tmp_path / "publisher.pub"
    with pytest.raises((FileExistsError, RuntimeError)):
        signing.main(
            [
                "keygen",
                "--private-out",
                str(private_path),
                "--public-out",
                str(public_path),
            ]
        )
    assert private_path.read_bytes() == b"keep this unrelated content"
    assert not public_path.exists()
