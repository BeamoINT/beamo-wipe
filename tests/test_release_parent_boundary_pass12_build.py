"""Release inputs must stay under directories opened without following links."""

from __future__ import annotations

import pytest

from test_release_publisher import PUBLISHER


def test_release_input_rejects_symlinked_ancestor(tmp_path):
    outside = tmp_path / "outside"
    evidence = outside / "evidence"
    evidence.mkdir(parents=True)
    payload = evidence / "qemu.log"
    payload.write_bytes(b"foreign evidence")

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "dist").symlink_to(outside, target_is_directory=True)
    apparent = checkout / "dist" / "evidence" / "qemu.log"

    with pytest.raises(PUBLISHER.PublishError, match="unsafe release directory"):
        PUBLISHER._regular_owned_file(apparent)
    with pytest.raises(PUBLISHER.PublishError, match="unsafe release directory"):
        PUBLISHER._sha256(apparent)
