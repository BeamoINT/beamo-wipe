"""Package provenance must describe repositories enabled in the image."""

from __future__ import annotations

import json

from beamo_wipe.ci_evidence import collect_inventory


def test_image_inventory_omits_disabled_and_commented_apt_uris(tmp_path):
    image = tmp_path / "image"
    status = image / "var/lib/dpkg/status"
    status.parent.mkdir(parents=True)
    status.write_text(
        "Package: base-files\nStatus: install ok installed\n"
        "Version: 1\nArchitecture: amd64\n"
    )
    sources = image / "etc/apt/sources.list.d"
    sources.mkdir(parents=True)
    (image / "etc/apt/sources.list").write_text(
        "deb https://deb.debian.org/debian bookworm main "
        "# old: https://retired.example.invalid/debian\n"
    )
    (sources / "old.sources").write_text(
        "Types: deb\nURIs: https://disabled.example.invalid/debian\n"
        "Suites: bookworm\nComponents: main\nEnabled: no\n"
    )
    output = tmp_path / "packages.json"

    collect_inventory(image, output, "a" * 40)

    assert json.loads(output.read_text())["apt_sources"] == [
        "https://deb.debian.org/debian"
    ]


def test_image_inventory_reads_active_list_options_and_folded_deb822_uris(tmp_path):
    image = tmp_path / "image"
    status = image / "var/lib/dpkg/status"
    status.parent.mkdir(parents=True)
    status.write_text(
        "Package: base-files\nStatus: install ok installed\n"
        "Version: 1\nArchitecture: amd64\n"
    )
    sources = image / "etc/apt/sources.list.d"
    sources.mkdir(parents=True)
    (image / "etc/apt/sources.list").write_text(
        "deb [arch=amd64 signed-by=/usr/share/keyrings/debian.gpg] "
        "https://deb.debian.org/debian bookworm main\n"
    )
    (sources / "security.sources").write_text(
        "Types: deb\nURIs: https://security.debian.org/debian-security\n"
        " https://mirror.example.invalid/debian-security\n"
        "Suites: bookworm-security\nComponents: main\nEnabled: yes\n"
    )

    output = tmp_path / "packages.json"
    collect_inventory(image, output, "a" * 40)

    assert json.loads(output.read_text())["apt_sources"] == [
        "https://deb.debian.org/debian",
        "https://mirror.example.invalid/debian-security",
        "https://security.debian.org/debian-security",
    ]
