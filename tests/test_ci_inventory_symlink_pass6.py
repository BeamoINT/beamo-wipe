# SPDX-License-Identifier: GPL-3.0-or-later
"""Mounted-image inventory must not read the host through image symlinks."""

from __future__ import annotations

import json

import pytest

from beamo_wipe.ci_evidence import collect_inventory


@pytest.mark.parametrize("linked_input", ("status", "sources"))
def test_inventory_rejects_symlink_to_host_file(tmp_path, linked_input):
    image = tmp_path / "image"
    status = image / "var/lib/dpkg/status"
    sources = image / "etc/apt/sources.list"
    status.parent.mkdir(parents=True)
    sources.parent.mkdir(parents=True)
    status_text = "Package: base-files\nStatus: install ok installed\nVersion: 1\nArchitecture: amd64\n"
    source_text = "deb https://deb.debian.org/debian bookworm main\n"
    if linked_input == "status":
        outside = tmp_path / "host-status"
        outside.write_text(status_text)
        status.symlink_to(outside)
        sources.write_text(source_text)
    else:
        status.write_text(status_text)
        outside = tmp_path / "host-sources"
        outside.write_text(source_text)
        sources.symlink_to(outside)
    destination = tmp_path / "packages.json"
    with pytest.raises(RuntimeError, match="image inventory input"):
        collect_inventory(image, destination, "a" * 40)
    assert not destination.exists()


def test_inventory_rejects_symlinked_sources_directory(tmp_path):
    image = tmp_path / "image"
    status = image / "var/lib/dpkg/status"
    status.parent.mkdir(parents=True)
    status.write_text("Package: base-files\nStatus: install ok installed\nVersion: 1\nArchitecture: amd64\n")
    apt = image / "etc/apt"
    apt.mkdir(parents=True)
    outside = tmp_path / "host-sources"
    outside.mkdir()
    (apt / "sources.list.d").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="unsafe image inventory input"):
        collect_inventory(image, tmp_path / "packages.json", "a" * 40)


def test_inventory_reads_regular_deb822_sources_from_image(tmp_path):
    image = tmp_path / "image"
    status = image / "var/lib/dpkg/status"
    status.parent.mkdir(parents=True)
    status.write_text("Package: base-files\nStatus: install ok installed\nVersion: 1\nArchitecture: amd64\n")
    source_dir = image / "etc/apt/sources.list.d"
    source_dir.mkdir(parents=True)
    (source_dir / "debian.sources").write_text("URIs: https://deb.debian.org/debian\n")
    destination = tmp_path / "packages.json"
    collect_inventory(image, destination, "a" * 40)
    assert "https://deb.debian.org/debian" in json.loads(destination.read_text())["apt_sources"]
