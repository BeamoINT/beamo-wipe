# SPDX-License-Identifier: GPL-3.0-or-later
"""A package inventory must name actual HTTP(S) apt repositories."""

import pytest

from beamo_wipe.verification_evidence import build_package_inventory


@pytest.mark.parametrize("source", ["not-a-url", "https://", "ftp://example.invalid/debian"])
def test_package_inventory_rejects_non_repository_sources(source):
    with pytest.raises(RuntimeError, match="apt source URI"):
        build_package_inventory(
            packages=[{"name": "base-files", "version": "12.4", "arch": "amd64"}],
            collected_from="squashfs var/lib/dpkg/status",
            apt_sources=[source],
            source_commit="a" * 40,
            generated_at="2026-09-24T00:00:00Z",
        )
